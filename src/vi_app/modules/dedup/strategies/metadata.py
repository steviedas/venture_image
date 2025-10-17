# vi_app/modules/dedup/strategies/metadata.py
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..schemas import DedupItem
from .base import DedupStrategyBase, ProgressReporter, get_worker_count


@dataclass(frozen=True)
class _Item:
    path: Path
    sha256: str
    pixels: int
    size: int


class MetadataStrategy(DedupStrategyBase):
    """
    Exact-byte duplicate detection via SHA-256; ranks keepers by resolution/size/path.
    Reports progress for: scan -> hash -> bucket -> select.
    Hash phase is parallelised with a thread pool.
    """

    def __init__(self, exts: set[str] | None = None) -> None:
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

        # HASH (parallel sha256)
        workers = get_worker_count(
            io_bound=True
        )  # hashlib (C) + disk IO -> threads scale
        if reporter:
            reporter.start(
                "hash",
                total=len(files),
                text=f"Hashing files (SHA-256)… (workers={workers})",
            )

        items: list[_Item] = []

        def _hash_one(p: Path) -> _Item:
            sha = self._sha256_file(p)
            px = self._pixels(p)
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            return _Item(p, sha, px, size)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_hash_one, p): p for p in files}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    it = fut.result()
                    items.append(it)
                except Exception:
                    items.append(_Item(p, "", 0, 0))
                if reporter:
                    reporter.update("hash", 1, text=p.name)

        if reporter:
            reporter.end("hash")

        # BUCKET
        if reporter:
            reporter.start(
                "bucket", total=len(items), text="Bucketing exact duplicates…"
            )
        buckets: dict[str, list[_Item]] = {}
        for it in items:
            buckets.setdefault(it.sha256, []).append(it)
            if reporter:
                reporter.update("bucket", 1, text=it.path.name)
        if reporter:
            reporter.end("bucket")

        # SELECT
        dup_buckets = [grp for grp in buckets.values() if len(grp) > 1]
        if reporter:
            reporter.start("select", total=len(dup_buckets), text="Selecting keepers…")
        results: list[DedupItem] = []
        for grp in dup_buckets:
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

    @staticmethod
    def _sha256_file(p: Path, chunk: int = 1024 * 1024) -> str:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for part in iter(lambda: f.read(chunk), b""):
                h.update(part)
        return h.hexdigest()

    @staticmethod
    def _pixels(p: Path) -> int:
        try:
            with Image.open(p) as im:
                im.load()
                return im.width * im.height
        except Exception:
            return 0

    @staticmethod
    def _best_of(group: list[_Item]) -> _Item:
        return max(group, key=lambda it: (it.pixels, it.size, str(it.path)))
