#!/usr/bin/env python3
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

# ------------- Config -------------
PATH_TO_PROCESS = r"C:\Users\stevi\Desktop\XX Scans"  # <- set this
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".cr2", ".heic", ".heif")
TARGET_PREFIX = "IMG_"
TARGET_PAD = 6  # IMG_000001
TEMP_SUFFIX = ".__renametmp__"
DRY_RUN = False           # set False to actually make changes
INCLUDE_ROOT = True     # True = also rename files in the root folder itself
# ----------------------------------

# Optional deps
try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# exifread improves EXIF coverage (esp. RAW/CR2); optional
try:
    import exifread
except ImportError:
    exifread = None

# HEIC/HEIF conversion support (optional)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_OK = True
except Exception:
    HEIF_OK = False


def read_exif_datetime_exifread(path: Path) -> Optional[datetime]:
    if exifread is None:
        return None
    try:
        with path.open("rb") as f:
            tags = exifread.process_file(f, details=False, stop_tag="EXIF DateTimeOriginal")
        for k in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
            if k in tags:
                val = str(tags[k])
                try:
                    return datetime.strptime(val, "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    try:
                        return datetime.fromisoformat(val.replace(":", "-", 2))
                    except Exception:
                        pass
    except Exception:
        pass
    return None


def read_exif_datetime_pillow(path: Path) -> Optional[datetime]:
    try:
        with Image.open(path) as img:
            exif = getattr(img, "_getexif", lambda: None)()
            if exif:
                for tag_id in (36867, 36868, 306):  # DateTimeOriginal, Digitized, DateTime
                    if tag_id in exif:
                        val = exif[tag_id]
                        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                            try:
                                return datetime.strptime(val, fmt)
                            except Exception:
                                continue
            if isinstance(img.info, dict):
                for key in ("date", "creation_time", "DateTime"):
                    if key in img.info:
                        val = str(img.info[key])
                        try:
                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                                try:
                                    return datetime.strptime(val, fmt)
                                except ValueError:
                                    continue
                            return datetime.fromisoformat(val.replace("Z", "+00:00"))
                        except Exception:
                            pass
    except Exception:
        pass
    return None


def get_date_taken(path: Path) -> datetime:
    dt = read_exif_datetime_exifread(path)
    if dt:
        return dt
    dt = read_exif_datetime_pillow(path)
    if dt:
        return dt
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except Exception:
        return datetime(1970, 1, 1)


def convert_heif_to_jpeg(src: Path, dest: Path) -> None:
    if not HEIF_OK:
        raise RuntimeError("HEIC/HEIF support not available. Install with: pip install pillow-heif")
    with Image.open(src) as im:
        im = im.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, format="JPEG", quality=95, optimize=True)


def plan_operations_for_dir(directory: Path) -> List[Tuple[Path, Path, Optional[str]]]:
    items: List[Tuple[Path, datetime]] = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            items.append((p, get_date_taken(p)))
    if not items:
        return []

    items.sort(key=lambda t: (t[1], t[0].name.lower()))

    ops: List[Tuple[Path, Path, Optional[str]]] = []
    counter = 1
    for src, _dt in items:
        ext = src.suffix.lower()
        if ext in (".heic", ".heif"):
            new_ext = ".jpeg"
            action = "convert"
        else:
            new_ext = ext
            action = None
        target_name = f"{TARGET_PREFIX}{str(counter).zfill(TARGET_PAD)}{new_ext}"
        ops.append((src, directory / target_name, action))
        counter += 1
    return ops


def two_phase_apply(ops: List[Tuple[Path, Path, Optional[str]]], dry_run: bool) -> None:
    if not ops:
        return

    temp_targets: List[Tuple[Path, Path, Optional[str]]] = []
    for src, final_target, action in ops:
        temp = final_target.with_name(final_target.name + TEMP_SUFFIX)
        idx = 1
        while temp.exists():
            temp = final_target.with_name(final_target.stem + f".tmp{idx}" + final_target.suffix + TEMP_SUFFIX)
            idx += 1
        temp_targets.append((src, temp, action))

    for src, temp, action in temp_targets:
        if dry_run:
            msg = "Convert" if action == "convert" else "Rename"
            print(f"[DRY-RUN] {msg} {src.name} -> {temp.name.replace(TEMP_SUFFIX, '')} (via temp)")
            continue
        if action == "convert":
            convert_heif_to_jpeg(src, temp)
        else:
            temp.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(temp))

    if not dry_run:
        for (_, temp, _), (_, final, _) in zip(temp_targets, ops):
            if final.exists():
                final.unlink()
            temp.rename(final)
        for (src, _, action) in temp_targets:
            if action == "convert" and src.exists():
                try:
                    src.unlink()
                except Exception as e:
                    print(f"Warning: could not remove original {src}: {e}", file=sys.stderr)


def process_root(path_to_process: Path, dry_run: bool) -> None:
    if not path_to_process.exists() or not path_to_process.is_dir():
        print(f"ERROR: '{path_to_process}' is not a directory.", file=sys.stderr)
        sys.exit(2)

    for dirpath, dirnames, filenames in os.walk(path_to_process):
        current_dir = Path(dirpath)
        if not INCLUDE_ROOT and current_dir == path_to_process:
            continue  # process subdirectories only

        ops = plan_operations_for_dir(current_dir)
        if not ops:
            continue

        rel = current_dir if current_dir == path_to_process else current_dir.relative_to(path_to_process)
        print(f"\nProcessing: {rel}  ({len(ops)} file(s))")
        two_phase_apply(ops, dry_run=dry_run)


def main():
    root = Path(PATH_TO_PROCESS).expanduser().resolve()
    print(f"Root: {root}")
    if not HEIF_OK:
        print("Note: HEIC/HEIF conversion unavailable. Install: pip install pillow-heif", file=sys.stderr)
    process_root(root, dry_run=DRY_RUN)
    print("\nDone.")


if __name__ == "__main__":
    main()
