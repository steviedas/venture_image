import os
import shutil
from datetime import datetime
from PIL import Image, ExifTags
import pillow_heif
import imagehash
from tqdm import tqdm  # progress bar

# Register HEIC/HEIF support
pillow_heif.register_heif_opener()

# Input and Output paths
path_to_process = r"C:\Users\stevi\Desktop\to_sort"
output_path = r"C:\Users\stevi\Desktop\Organised Photos"
unprocessable_path = r"C:\Users\stevi\Desktop\Unprocessed Photos"

# Supported formats
image_extensions = (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".cr2", ".heic", ".heif")

# Ensure output dirs exist
os.makedirs(output_path, exist_ok=True)
os.makedirs(unprocessable_path, exist_ok=True)


def get_exif_date(path):
    """Extract all EXIF date fields and return the earliest available date. Falls back to filesystem dates."""
    exif_dates = []
    try:
        image = Image.open(path)
        exif_data = image.getexif()
        if exif_data:
            for tag_id, value in exif_data.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                    try:
                        exif_dates.append(datetime.strptime(value, "%Y:%m:%d %H:%M:%S"))
                    except Exception:
                        pass
    except Exception:
        pass

    # Add filesystem creation/modification times
    try:
        stat = os.stat(path)
        exif_dates.append(datetime.fromtimestamp(stat.st_ctime))
        exif_dates.append(datetime.fromtimestamp(stat.st_mtime))
    except Exception:
        pass

    return min(exif_dates) if exif_dates else datetime.now()


def get_perceptual_hash(path):
    """Compute perceptual hash (pHash) of an image for visual similarity detection."""
    try:
        with Image.open(path) as img:
            return imagehash.phash(img)
    except Exception as e:
        print(f"[HASH ERROR] {path}: {e}")
        return None


def safe_move(src, dst, fallback_dir=None):
    """Safely move file, fallback to unprocessable dir if needed."""
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return True
    except Exception as e:
        print(f"[ERROR] Moving {src} -> {dst}: {e}")
        if fallback_dir:
            try:
                os.makedirs(fallback_dir, exist_ok=True)
                fallback_path = os.path.join(fallback_dir, os.path.basename(src))
                shutil.move(src, fallback_path)
                print(f"[MOVED TO UNPROCESSABLE] {src} -> {fallback_path}")
            except Exception as e2:
                print(f"[FAILED TO MOVE UNPROCESSABLE] {src}: {e2}")
        return False


def list_all_files():
    """Return a list of all files under path_to_process."""
    file_list = []
    for root, _, filenames in os.walk(path_to_process):
        for filename in filenames:
            file_list.append(os.path.join(root, filename))
    return file_list


def collect_files():
    """Collect metadata (path, ext, hash, date, size) for all supported images."""
    files = []
    all_files = list_all_files()
    total_files = len(all_files)

    with tqdm(total=total_files, desc="Processing files", unit="file") as pbar:
        for full_path in all_files:
            ext = os.path.splitext(full_path)[1].lower()

            if ext not in image_extensions:
                safe_move(full_path, os.path.join(unprocessable_path, os.path.basename(full_path)))
                pbar.update(1)
                continue

            try:
                file_hash = get_perceptual_hash(full_path)
                if file_hash is None:
                    safe_move(full_path, os.path.join(unprocessable_path, os.path.basename(full_path)))
                    pbar.update(1)
                    continue
                date_taken = get_exif_date(full_path)
                file_size = os.path.getsize(full_path)
                files.append((full_path, ext, str(file_hash), date_taken, file_size))
            except Exception as e:
                print(f"[SKIPPED] {full_path}: {e}")
                safe_move(full_path, os.path.join(unprocessable_path, os.path.basename(full_path)))

            pbar.update(1)  # progress bar tick
    return files


def process_images():
    files = collect_files()
    files.sort(key=lambda x: x[3])  # sort by date

    hash_map = {}
    name_map = {}
    counter = 1

    for full_path, ext, file_hash, date_taken, file_size in files:
        if file_hash not in hash_map:
            new_name = f"IMG_{counter:06d}{ext}"
            hash_map[file_hash] = [counter, 0, date_taken, file_size, full_path]
            main_date = date_taken
            counter += 1
            new_path = os.path.join(output_path, new_name)
        else:
            main_index, dupes_count, main_date, main_size, main_path = hash_map[file_hash]
            if file_size > main_size:
                dupes_count += 1
                hash_map[file_hash] = [main_index, dupes_count, date_taken, file_size, full_path]
                dupe_name = f"IMG_{main_index:06d}_dupe({dupes_count}){os.path.splitext(main_path)[1]}"
                dupe_path = os.path.join(output_path, dupe_name)

                if safe_move(main_path, dupe_path, unprocessable_path):
                    print(f"[REPLACED] Kept larger {full_path}, moved smaller {main_path} -> {dupe_path}")

                new_name = f"IMG_{main_index:06d}{ext}"
                new_path = os.path.join(output_path, new_name)
            else:
                dupes_count += 1
                hash_map[file_hash][1] = dupes_count
                new_name = f"IMG_{main_index:06d}_dupe({dupes_count}){ext}"
                new_path = os.path.join(output_path, new_name)

        name_map[new_path] = main_date
        safe_move(full_path, new_path, unprocessable_path)

    return name_map


def organize_by_date(name_map):
    """Move processed files into year/month folders, keeping dupes with main file."""
    for file_path, date_taken in name_map.items():
        filename = os.path.basename(file_path)
        year = str(date_taken.year)
        month = f"{date_taken.month:02d}"
        dest_dir = os.path.join(output_path, year, month)
        dest_path = os.path.join(dest_dir, filename)

        safe_move(file_path, dest_path, unprocessable_path)


if __name__ == "__main__":
    name_map = process_images()
    organize_by_date(name_map)
    print("\n✅ Processing complete!")
