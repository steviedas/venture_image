# vi_app/modules/dedup/strategies/content.py
from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

from ..schemas import DedupItem
from .base import DedupStrategyBase, ProgressReporter, get_worker_count


@dataclass(frozen=True)
class _Item:
    path: Path
    hash: int
    pixels: int
    size: int


class ContentStrategy(DedupStrategyBase):
    """
    Perceptual (near-duplicate) strategy using pHash (configurable).
    Reports progress for: scan -> hash -> cluster -> select.
    Hash phase is parallelised with a thread pool.
    """

    def __init__(
        self,
        hash_fn=imagehash.phash,
        hash_size: int = 16,  # 256-bit pHash
        hamming_threshold: int = 6,
        exts: set[str] | None = None,
    ) -> None:
        self.hash_fn = hash_fn
        self.hash_size = hash_size
        self.hamming_threshold = hamming_threshold
        self.exts = exts or {
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

    # ---- public API ----
    def run(
        self, root: Path, reporter: ProgressReporter | None = None
    ) -> list[DedupItem]:
        root = root.resolve()

        # SCAN
        if reporter:
            reporter.start("scan", total=None, text="Discovering images…")
        files = list(self._iter_images(root, reporter=reporter))
        if reporter:
            reporter.end("scan")

        # HASH (parallel)
        workers = get_worker_count(
            io_bound=True
        )  # PIL decode + hashing benefit from threads
        if reporter:
            reporter.start(
                "hash", total=len(files), text=f"Computing pHash… (workers={workers})"
            )

        items: list[_Item] = []

        def _compute_item(p: Path) -> _Item:
            hv, pixels = self._phash_int(p)
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            return _Item(path=p, hash=hv, pixels=pixels, size=size)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_compute_item, p): p for p in files}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    it = fut.result()
                    items.append(it)
                except Exception:
                    # Failed hash/open => treat as zeroed item, still advance progress
                    items.append(_Item(path=p, hash=0, pixels=0, size=0))
                if reporter:
                    reporter.update("hash", 1, text=p.name)

        if reporter:
            reporter.end("hash")

        # CLUSTER (greedy, sequential)
        if reporter:
            reporter.start("cluster", total=len(items), text="Clustering near-dupes…")
        remaining = sorted(
            items, key=lambda it: (it.pixels, it.size, str(it.path)), reverse=True
        )
        clusters: list[list[_Item]] = []
        while remaining:
            seed = remaining.pop(0)
            if reporter:
                reporter.update("cluster", 1, text=seed.path.name)
            cluster = [seed]
            still: list[_Item] = []
            for it in remaining:
                if self._hamming(seed.hash, it.hash) <= self.hamming_threshold:
                    cluster.append(it)
                else:
                    still.append(it)
            remaining = still
            if len(cluster) > 1:
                clusters.append(cluster)
        if reporter:
            reporter.end("cluster")

        # SELECT best per cluster
        if reporter:
            reporter.start("select", total=len(clusters), text="Selecting keepers…")
        results: list[DedupItem] = []
        for grp in clusters:
            keeper = self._best_of(grp)
            dups = [str(it.path) for it in grp if it.path != keeper.path]
            if dups:
                results.append(DedupItem(keep=str(keeper.path), duplicates=dups))
            if reporter:
                reporter.update("select", 1, text=Path(keeper.path).name)
        if reporter:
            reporter.end("select")

        return results

    # ---- helpers ----
    def _iter_images(
        self, root: Path, reporter: ProgressReporter | None = None
    ) -> Iterable[Path]:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in self.exts:
                if reporter:
                    reporter.update("scan", 1, text=p.name)
                yield p

    def _safe_open_image(self, p: Path) -> Image.Image | None:
        try:
            im = Image.open(p)
            im.load()
            return im
        except Exception:
            return None

    def _phash_int(self, p: Path) -> tuple[int, int]:
        im = self._safe_open_image(p)
        if im is None:
            return 0, 0
        try:
            h = self.hash_fn(im, hash_size=self.hash_size)
            pixels = im.width * im.height
            return int(str(h), 16), pixels
        except Exception:
            return 0, 0
        finally:
            try:
                im.close()
            except Exception:
                pass

    @staticmethod
    def _hamming(a: int, b: int) -> int:
        return (a ^ b).bit_count()

    @staticmethod
    def _best_of(group: list[_Item]) -> _Item:
        return max(group, key=lambda it: (it.pixels, it.size, str(it.path)))
