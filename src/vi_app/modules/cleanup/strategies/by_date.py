# src/vi_app/modules/cleanup/strategies/by_date.py
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image

from vi_app.core.paths import sanitize_filename

IMG_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".heic",
    ".heif",
}


def _iter_images(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            yield p


def _exif_datetime(p: Path) -> datetime | None:
    try:
        with Image.open(p) as im:
            exif = im.getexif() or {}
            # Normalize tag names
            tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            ts = (
                tags.get("DateTimeOriginal")
                or tags.get("DateTime")
                or tags.get("CreateDate")
            )
            if isinstance(ts, bytes):
                ts = ts.decode(errors="ignore")
            if isinstance(ts, str):
                # Common EXIF: "YYYY:MM:DD HH:MM:SS"
                ts = ts.replace("-", ":")
                try:
                    return datetime.strptime(ts, "%Y:%m:%d %H:%M:%S")
                except Exception:
                    # Try ISO-ish
                    with_s = ts.split(".")[0].replace("/", "-").replace(":", "-", 2)
                    try:
                        return datetime.fromisoformat(with_s)
                    except Exception:
                        return None
    except Exception:
        return None
    return None


def _fs_datetime(p: Path) -> datetime:
    # Use modification time as a stable fallback
    try:
        return datetime.fromtimestamp(p.stat().st_mtime)
    except Exception:
        return datetime(1970, 1, 1)


def plan(src_root: Path, dst_root: Path | None) -> list[tuple[Path, Path]]:
    """
    Returns list of (src, dst) moves like:
    dst_root/YYYY/MM/filename
    """
    src_root = src_root.resolve()
    dst_root = (dst_root or src_root).resolve()

    moves: list[tuple[Path, Path]] = []
    for src in _iter_images(src_root):
        dt = _exif_datetime(src) or _fs_datetime(src)
        year = f"{dt.year:04d}"
        month = f"{dt.month:02d}"
        dst_dir = dst_root / year / month
        dst = dst_dir / sanitize_filename(src.name)
        moves.append((src, dst))
    return moves
