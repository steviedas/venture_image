import os
import shutil
import exifread
from PIL import Image
from PIL.ExifTags import TAGS
from datetime import datetime
import pillow_heif  # Direct import (requires: pip install pillow-heif)

# Register HEIF/HEIC opener so Pillow can read them
pillow_heif.register_heif_opener()

path_to_sort = r"Z:\Dumps\USB Dumps"
picture_target_path = r"Z:\Dumps\Date Sorted Pictures"
video_target_path = r"Z:\Dumps\Videos"

# Supported formats
image_extensions = (
    ".jpg",
    ".jpeg", 
    ".png",
    ".tiff",
    ".bmp",
    ".cr2",
    ".CR2",
    ".heic",
    ".heif"
)
video_extensions = (".m4v", ".mov", ".mp4", ".gif")

def get_exif_date_pillow(path):
    try:
        image = Image.open(path)

        # Prefer modern getexif() over _getexif()
        exif_data = image.getexif()
        if not exif_data:
            return None

        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "DateTimeOriginal":
                return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")

    except Exception as e:
        print(f"[EXIF ERROR - Pillow] {path}: {e}")
    return None

def get_exif_date_cr2(path):
    try:
        with open(path, 'rb') as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
            date_tag = tags.get("EXIF DateTimeOriginal")
            if date_tag:
                return datetime.strptime(str(date_tag), "%Y:%m:%d %H:%M:%S")
    except Exception as e:
        print(f"[EXIF ERROR - CR2] {path}: {e}")
    return None

def get_exif_date(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cr2":
        return get_exif_date_cr2(path)
    else:
        return get_exif_date_pillow(path)

def get_filesystem_date(path):
    try:
        stat = os.stat(path)
        creation_time = datetime.fromtimestamp(stat.st_ctime)
        modification_time = datetime.fromtimestamp(stat.st_mtime)
        return min(creation_time, modification_time)
    except Exception as e:
        print(f"[FS DATE ERROR] {path}: {e}")
        return None

def get_earliest_date(path):
    exif_date = get_exif_date(path)
    fs_date = get_filesystem_date(path)

    if exif_date and fs_date:
        return min(exif_date, fs_date)
    return exif_date or fs_date

def get_unique_filename(dest_dir, filename):
    """
    If filename already exists, append _(1), _(2), etc.
    """
    name, ext = os.path.splitext(filename)
    counter = 1
    new_filename = filename

    while os.path.exists(os.path.join(dest_dir, new_filename)):
        new_filename = f"{name}_({counter}){ext}"
        counter += 1

    return new_filename

def move_image(full_path, date_taken):
    """
    Move image into year/month subfolders inside picture_target_path.
    """
    year = str(date_taken.year)
    month = f"{date_taken.month:02d}"
    dest_dir = os.path.join(picture_target_path, year, month)
    os.makedirs(dest_dir, exist_ok=True)

    filename = os.path.basename(full_path)
    unique_filename = get_unique_filename(dest_dir, filename)
    dest_file = os.path.join(dest_dir, unique_filename)

    try:
        shutil.move(full_path, dest_file)
        print(f"[MOVED] {full_path} -> {dest_file}")
    except Exception as e:
        print(f"[ERROR] Moving {full_path} -> {dest_file}: {e}")

def move_video(full_path, ext):
    """
    Move video into subfolder named by its UPPERCASE extension (no year/month).
    """
    ext_folder = ext.lstrip(".").upper()
    dest_dir = os.path.join(video_target_path, ext_folder)
    os.makedirs(dest_dir, exist_ok=True)

    filename = os.path.basename(full_path)
    unique_filename = get_unique_filename(dest_dir, filename)
    dest_file = os.path.join(dest_dir, unique_filename)

    try:
        shutil.move(full_path, dest_file)
        print(f"[MOVED] {full_path} -> {dest_file}")
    except Exception as e:
        print(f"[ERROR] Moving {full_path} -> {dest_file}: {e}")

def move_media():
    for root, _, files in os.walk(path_to_sort):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            full_path = os.path.join(root, file)

            if ext in image_extensions:
                date_taken = get_earliest_date(full_path)
                if not date_taken:
                    print(f"[SKIPPED] No valid date: {full_path}")
                    continue
                move_image(full_path, date_taken)

            elif ext in video_extensions:
                move_video(full_path, ext)

if __name__ == "__main__":
    move_media()
