# src/vi_app/modules/dedup/strategies/metadata.py
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image  # only used to rank resolution if possible

from ..schemas import DedupItem

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


@dataclass(frozen=True)
class _Item:
    path: Path
    sha256: str
    pixels: int
    size: int


def _iter_images(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            yield p


def _sha256_file(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for part in iter(lambda: f.read(chunk), b""):
            h.update(part)
    return h.hexdigest()


def _pixels(p: Path) -> int:
    try:
        with Image.open(p) as im:
            im.load()
            return im.width * im.height
    except Exception:
        return 0


def _best_of(group: list[_Item]) -> _Item:
    # Higher resolution, then bigger bytes, then path alpha
    return max(group, key=lambda it: (it.pixels, it.size, str(it.path)))


def run(root: Path) -> list[DedupItem]:
    """
    Compute SHA-256 and group exact duplicates.
    """
    root = root.resolve()
    buckets: dict[str, list[_Item]] = {}

    for p in _iter_images(root):
        try:
            sha = _sha256_file(p)
            size = p.stat().st_size
            px = _pixels(p)
        except Exception:
            # unreadable; skip
            continue
        buckets.setdefault(sha, []).append(_Item(p, sha, px, size))

    results: list[DedupItem] = []
    for _sha, group in buckets.items():
        if len(group) <= 1:
            continue
        keeper = _best_of(group)
        dups = [str(it.path) for it in group if it.path != keeper.path]
        if dups:
            results.append(DedupItem(keep=str(keeper.path), duplicates=dups))

    return results
