#!/usr/bin/env python3
"""
Detect near-duplicate images (same content at different resolutions) per leaf directory.

For each leaf directory (a folder with no subfolders) under PATH_TO_PROCESS:
  - Compute a perceptual hash (dHash) per image
  - Group images whose hashes are within HAMMING_THRESHOLD
  - For each group, KEEP the highest-resolution image IN PLACE (no 'final' folder)
    and move all other duplicates into ./duplicate/

Run once with DRY_RUN = True to preview actions, then set DRY_RUN = False to apply.

Requires: Pillow
"""

from __future__ import annotations

import os
import sys
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from PIL import Image

# ==================== EDIT THESE ====================
PATH_TO_PROCESS      = r"C:\Users\stevi\Desktop\dedup_1"  # root directory to scan
DRY_RUN              = True                            # True = preview only; False = actually move files
HASH_SIZE            = 16                              # dHash dimension (higher = stronger, slower). Common: 8-16
HAMMING_THRESHOLD    = 6                               # max bit distance to consider "same content" (try 5-8)
INCLUDE_EXTS         = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}  # case-insensitive
EXCLUDE_DIR_NAMES    = {"duplicate"}                   # names to skip inside each leaf
# ====================================================

# ----- lightweight coloured logger -----
_ENABLE_COLOR = os.environ.get("NO_COLOR", "").lower() not in {"1", "true", "yes"}
try:
    if os.name == "nt" and _ENABLE_COLOR:
        import colorama  # type: ignore
        colorama.just_fix_windows_console()
except Exception:
    pass

def _c(code: str) -> str:
    return code if _ENABLE_COLOR else ""

RESET = _c("\033[0m")
RED   = _c("\033[31m")
GREEN = _c("\033[32m")
YEL   = _c("\033[33m")

def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")

def log_ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}" if _ENABLE_COLOR else f"[OK] {msg}")

def log_warn(msg: str) -> None:
    print(f"{YEL}[WARN]{RESET} {msg}" if _ENABLE_COLOR else f"[WARN] {msg}", file=sys.stderr)

def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{RESET} {msg}" if _ENABLE_COLOR else f"[ERROR] {msg}", file=sys.stderr)
# --------------------------------------


def iter_leaf_dirs(root: Path) -> Iterable[Path]:
    """
    Yield all leaf directories (no subdirectories) under root.
    We don't descend into 'duplicate' subfolders.
    """
    for dirpath, dirnames, _ in os.walk(root):
        # Prune excluded names so we don't descend into them
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        if not dirnames:  # no subdirectories -> leaf
            yield Path(dirpath)


@dataclass
class ImgInfo:
    path: Path
    width: int
    height: int
    area: int
    size_bytes: int
    dhash: int


def dhash(img: Image.Image, hash_size: int = 8) -> int:
    """
    Perceptual difference hash (dHash):
      - grayscale
      - resize to (hash_size+1, hash_size)
      - compare adjacent columns to build bits
    """
    gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = gray.load()
    bits = 0
    for y in range(hash_size):
        for x in range(hash_size):
            left = pixels[x, y]
            right = pixels[x + 1, y]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming_distance(a: int, b: int) -> int:
    x = a ^ b
    cnt = 0
    while x:
        x &= x - 1
        cnt += 1
    return cnt


def load_image_info(path: Path, hash_size: int) -> ImgInfo | None:
    try:
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                try:
                    im.seek(0)
                except Exception:
                    pass
            width, height = im.size
            d = dhash(im, hash_size=hash_size)
        stat = path.stat()
        return ImgInfo(
            path=path,
            width=width,
            height=height,
            area=width * height,
            size_bytes=stat.st_size,
            dhash=d,
        )
    except Exception as e:
        log_warn(f"Failed to read image {path}: {e}")
        return None


def pick_best(images: List[ImgInfo]) -> ImgInfo:
    """
    Choose the best representative to KEEP IN PLACE:
      1) Largest area (w*h)
      2) Then largest file size (bytes)
      3) Then lexicographically smallest path name (stable tie-break)
    """
    return max(images, key=lambda x: (x.area, x.size_bytes, str(x.path).lower()))


def cluster_by_hash(imgs: List[ImgInfo], threshold: int) -> List[List[ImgInfo]]:
    """
    Greedy clustering by dHash with Hamming distance threshold.
    Each cluster's leader is the first image added; others join if within threshold.
    """
    clusters: List[List[ImgInfo]] = []
    leaders: List[ImgInfo] = []
    for info in imgs:
        placed = False
        for i, leader in enumerate(leaders):
            if hamming_distance(info.dhash, leader.dhash) <= threshold:
                clusters[i].append(info)
                placed = True
                break
        if not placed:
            clusters.append([info])
            leaders.append(info)
    return clusters


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def unique_dest(dest_dir: Path, filename: str) -> Path:
    """
    If filename exists in dest_dir, append a numeric suffix before extension.
    """
    base = Path(filename).stem
    ext = Path(filename).suffix
    candidate = dest_dir / filename
    i = 1
    while candidate.exists():
        candidate = dest_dir / f"{base}_{i}{ext}"
        i += 1
    return candidate


def process_leaf_dir(leaf: Path) -> None:
    log_info(f"Processing leaf: {leaf}")

    dup_dir = leaf / "duplicate"
    ensure_dir(dup_dir)

    # Collect candidate image files (exclude 'duplicate' folder contents)
    files: list[Path] = []
    for p in leaf.iterdir():
        if p.is_dir() and p.name in EXCLUDE_DIR_NAMES:
            continue
        if p.is_file() and p.suffix.lower() in INCLUDE_EXTS:
            files.append(p)

    if not files:
        log_info("No images found in this leaf.")
        return

    # Compute image info + hashes
    infos: list[ImgInfo] = []
    for f in files:
        info = load_image_info(f, hash_size=HASH_SIZE)
        if info:
            infos.append(info)

    if not infos:
        log_info("No readable images in this leaf.")
        return

    # Cluster near-duplicates
    clusters = cluster_by_hash(infos, threshold=HAMMING_THRESHOLD)

    moved_dups = 0
    kept = 0

    for group in clusters:
        if len(group) == 1:
            # Unique: keep in place
            kept += 1
            log_info(f"[unique] keep in place -> {group[0].path.name}")
            continue

        # duplicates present
        best = pick_best(group)
        dupes = [g for g in group if g.path != best.path]

        # Keep best IN PLACE
        kept += 1
        log_ok(f"[keep] {best.path.name} (stays in {leaf})")

        # Move duplicates to ./duplicate/
        for d in dupes:
            dest = unique_dest(dup_dir, d.path.name)
            if DRY_RUN:
                log_info(f"[dup ] would move: {d.path.name} -> {dest}")
            else:
                try:
                    shutil.move(str(d.path), str(dest))
                    moved_dups += 1
                    log_ok(f"[dup ] moved: {d.path.name} -> {dest}")
                except Exception as e:
                    log_error(f"Failed to move {d.path} -> {dest}: {e}")

    summary = f"Done leaf: kept {kept} file(s) in place, moved {moved_dups} duplicate(s)."
    if DRY_RUN:
        summary = "(dry-run) " + summary
    log_info(summary)


def main() -> None:
    root = Path(PATH_TO_PROCESS).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        log_error(f"PATH_TO_PROCESS not found or not a directory: {root}")
        sys.exit(1)

    log_info(f"Root: {root}")
    log_info(f"DRY_RUN: {DRY_RUN} | HASH_SIZE: {HASH_SIZE} | THRESHOLD: {HAMMING_THRESHOLD}")

    leafs = list(iter_leaf_dirs(root))
    if not leafs:
        log_warn("No leaf directories found (directories without subfolders).")
        return

    for leaf in leafs:
        if leaf.name in EXCLUDE_DIR_NAMES:
            continue
        process_leaf_dir(leaf)

    log_info("All done.")


if __name__ == "__main__":
    main()
