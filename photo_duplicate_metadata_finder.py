import os
import hashlib
import shutil
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS
import pillow_heif

# Register HEIC/HEIF support
pillow_heif.register_heif_opener()

# Input folder
path_to_process = r"C:\Users\stevi\Desktop\to_sort"
processed_dir = os.path.join(path_to_process, "processed")

# Supported formats
image_extensions = (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".cr2", ".heic", ".heif")

# Ensure processed dir exists
os.makedirs(processed_dir, exist_ok=True)


def get_file_hash(path, block_size=65536):
    """Compute SHA256 hash of file contents."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_exif_date(path):
    """Extract all EXIF date fields and return the earliest available date. Falls back to filesystem dates."""
    exif_dates = []
    try:
        image = Image.open(path)
        exif_data = image.getexif()
        if exif_data:
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
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

    # Return the earliest date found
    if exif_dates:
        return min(exif_dates)
    else:
        # As a last resort, return current time
        return datetime.now()


def collect_files():
    """Collect metadata (path, ext, hash, date) for all supported images."""
    files = []
    for root, _, filenames in os.walk(path_to_process):
        if root.startswith(processed_dir):
            continue
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in image_extensions:
                continue
            full_path = os.path.join(root, filename)
            try:
                print(f"[HASHING] {full_path}")
                file_hash = get_file_hash(full_path)
                date_taken = get_exif_date(full_path)
                files.append((full_path, ext, file_hash, date_taken))
            except Exception as e:
                print(f"[SKIPPED] {full_path}: {e}")
    return files


def process_images():
    files = collect_files()
    files.sort(key=lambda x: x[3])  # sort by date

    hash_map = {}  # file_hash -> (main_index, dupes_count, main_date)
    name_map = {}  # final file path -> main_date
    counter = 1

    for full_path, ext, file_hash, date_taken in files:
        if file_hash not in hash_map:
            # Unique file
            new_name = f"IMG_{counter:06d}{ext}"
            hash_map[file_hash] = [counter, 0, date_taken]  # store date
            main_date = date_taken
            counter += 1
        else:
            # Duplicate file
            main_index, dupes_count, main_date = hash_map[file_hash]
            dupes_count += 1
            hash_map[file_hash][1] = dupes_count
            new_name = f"IMG_{main_index:06d}_dupe({dupes_count}){ext}"

        new_path = os.path.join(processed_dir, new_name)
        name_map[new_path] = main_date  # tie all files (main + dupes) to main date

        try:
            shutil.move(full_path, new_path)
            print(f"[MOVED] {full_path} -> {new_path}")
        except Exception as e:
            print(f"[ERROR] Moving {full_path} -> {new_path}: {e}")

    return name_map


def organize_by_date(name_map):
    """Move processed files into year/month folders, keeping dupes with main file."""
    for file_path, date_taken in name_map.items():
        filename = os.path.basename(file_path)

        year = str(date_taken.year)
        month = f"{date_taken.month:02d}"
        dest_dir = os.path.join(processed_dir, year, month)
        os.makedirs(dest_dir, exist_ok=True)

        dest_path = os.path.join(dest_dir, filename)
        try:
            shutil.move(file_path, dest_path)
            print(f"[ORGANISED] {filename} -> {dest_path}")
        except Exception as e:
            print(f"[ERROR] Organising {filename}: {e}")


if __name__ == "__main__":
    name_map = process_images()
    organize_by_date(name_map)
