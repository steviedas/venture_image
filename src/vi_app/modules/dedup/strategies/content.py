from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import imagehash  # perceptual hashing
from PIL import Image  # pillow

from ..schemas import DedupItem

# ---- configuration knobs (tune as you like) ----
HASH_FN = imagehash.phash  # or imagehash.dhash, ahash, whash
HASH_SIZE = 16  # 16 -> 256-bit; 8 -> 64-bit
NEAR_DUP_HAMMING_THRESHOLD = 6  # <=6 is usually a good "near-dup" cutoff

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
    hash: int
    pixels: int
    size: int


def _iter_images(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            yield p


def _safe_open_image(p: Path) -> Image.Image | None:
    try:
        im = Image.open(p)
        # lazy-loading file handlers need load/verify gymnastics sometimes;
        # convert() ensures we can read size reliably.
        im.load()
        return im
    except Exception:
        return None


def _phash_int(p: Path) -> tuple[int, int]:
    """Return (int_hash, pixels). pixels used for 'best copy' ranking."""
    im = _safe_open_image(p)
    if im is None:
        return 0, 0
    try:
        h = HASH_FN(im, hash_size=HASH_SIZE)
        pixels = im.width * im.height
        return int(str(h), 16), pixels
    except Exception:
        return 0, 0
    finally:
        try:
            im.close()
        except Exception:
            pass


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _best_of(group: list[_Item]) -> _Item:
    # Prefer higher resolution, then larger file-size, then lexicographic path
    return max(group, key=lambda it: (it.pixels, it.size, str(it.path)))


def run(root: Path) -> list[DedupItem]:
    """
    Compute perceptual hashes per image and group near-duplicates.
    Return a list of clusters as DedupItem(keep=<best>, duplicates=[...]).
    """
    root = root.resolve()
    items: list[_Item] = []
    for p in _iter_images(root):
        hv, pixels = _phash_int(p)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        items.append(_Item(path=p, hash=hv, pixels=pixels, size=size))

    # Greedy clustering (O(n^2) worst-case, fine for thousands of images).
    # Sort by quality so the cluster "seed" tends to be the best copy.
    remaining = sorted(
        items, key=lambda it: (it.pixels, it.size, str(it.path)), reverse=True
    )
    clusters: list[list[_Item]] = []

    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        still: list[_Item] = []
        for it in remaining:
            if _hamming(seed.hash, it.hash) <= NEAR_DUP_HAMMING_THRESHOLD:
                cluster.append(it)
            else:
                still.append(it)
        remaining = still
        if len(cluster) > 1:
            clusters.append(cluster)

    results: list[DedupItem] = []
    for grp in clusters:
        keeper = _best_of(grp)
        dups = [str(it.path) for it in grp if it.path != keeper.path]
        if dups:
            results.append(DedupItem(keep=str(keeper.path), duplicates=dups))

    return results
