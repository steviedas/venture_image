# src/vi_app/modules/dedup/service.py
from __future__ import annotations

import shutil
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from vi_app.core.progress import ProgressReporter

from .schemas import DedupItem, DedupRequest, DedupStrategy
from .strategies.base import get_worker_count
from .strategies.content import ContentStrategy
from .strategies.metadata import MetadataStrategy


class DedupService:
    """OOP wrapper around planning and applying dedup operations."""

    # ---- strategy resolution -------------------------------------------------
    def _select(self, strategy: DedupStrategy):
        if strategy == DedupStrategy.content:
            return ContentStrategy()
        return MetadataStrategy()

    # ---- public API ----------------------------------------------------------
    def plan(
        self, req: DedupRequest, reporter: ProgressReporter | None = None
    ) -> list[DedupItem]:
        """Compute duplicate clusters using the selected strategy."""
        strat = self._select(req.strategy)
        return strat.run(Path(req.root), reporter=reporter)

    def apply(
        self, req: DedupRequest, reporter: ProgressReporter | None = None
    ) -> list[DedupItem]:
        """
        Move duplicates, renaming them to '<keeper_stem>_dupe(n)<dup_ext>' into the duplicate folder
        (or req.move_duplicates_to when provided). Runs moves in parallel with progress reporting.
        """
        clusters = self.plan(req, reporter=reporter)
        if req.dry_run:
            return clusters

        # Prepare move tasks: (src, dst)
        def _moves() -> Iterable[tuple[Path, Path]]:
            for cluster in clusters:
                keep = Path(cluster.keep).resolve()
                counter = 1  # per-cluster numbering
                for dup in cluster.duplicates:
                    src = Path(dup)
                    try:
                        # Skip if src is missing or is the keeper itself
                        if not src.exists() or src.resolve() == keep:
                            yield (src, src)  # sentinel "skip"
                            counter += 1
                            continue
                    except Exception:
                        # If resolve fails, attempt to move anyway
                        pass

                    # Choose target dir: explicit param or sibling 'duplicate'
                    target_dir = Path(
                        req.move_duplicates_to or (src.parent / "duplicate")
                    )
                    target_dir.mkdir(parents=True, exist_ok=True)

                    # Compute first candidate for this duplicate
                    dst = self._next_dupe_path(
                        keeper=keep, dup=src, target_dir=target_dir, start_n=counter
                    )
                    counter += 1  # advance nominal per-cluster counter

                    yield (src, dst)

        todo: list[tuple[Path, Path]] = list(_moves())
        total = len(todo)

        # MOVE (parallel) with reporter
        workers = get_worker_count(io_bound=True)
        if reporter:
            reporter.start(
                "move", total=total, text=f"Moving duplicates… (workers={workers})"
            )

        def _move_one(src: Path, dst: Path) -> tuple[Path, bool, str | None]:
            # Sentinel skip (src == dst) or non-existent source
            if src == dst or not src.exists():
                return (src, False, "skip")

            try:
                # If destination exists for any reason, bump until free
                if dst.exists():
                    dst = self._bump_until_free(dst)

                shutil.move(str(src), str(dst))
                return (src, True, None)
            except Exception:
                # One more attempt with a bumped name (handles rare races)
                try:
                    fallback = self._bump_until_free(dst)
                    shutil.move(str(src), str(fallback))
                    return (src, True, None)
                except Exception as e2:
                    return (src, False, f"error:{e2.__class__.__name__}")

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_move_one, s, d): (s, d) for (s, d) in todo}
            for fut in as_completed(futs):
                s, _d = futs[fut]
                try:
                    _src, _ok, _reason = fut.result()
                except Exception as e:
                    _ok, _reason = False, f"error:{e.__class__.__name__}"
                if reporter:
                    reporter.update("move", 1, text=s.name)

        if reporter:
            reporter.end("move")

        return clusters

    # ---- helpers -------------------------------------------------------------
    @staticmethod
    def _next_dupe_path(
        keeper: Path, dup: Path, target_dir: Path, start_n: int = 1
    ) -> Path:
        """
        Build a destination path like '<keeper_stem>_dupe(n)<dup_ext>' in target_dir,
        bumping n until the path is free.
        """
        base_stem = keeper.stem
        ext = dup.suffix  # keep the duplicate's own extension
        n = max(1, int(start_n))
        while True:
            candidate = target_dir / f"{base_stem}_dupe({n}){ext}"
            if not candidate.exists():
                return candidate
            n += 1

    @staticmethod
    def _bump_until_free(dst: Path) -> Path:
        """
        If 'dst' exists, keep incrementing the (n) suffix until a free filename is found.
        Expects filenames with pattern '<stem>_dupe(n)<ext>'.
        """
        stem = dst.stem
        ext = dst.suffix
        # Extract trailing '(n)' if present; otherwise start from 1.
        base, _, tail = stem.rpartition("_dupe(")
        if base and tail.endswith(")"):
            num_str = tail[:-1]
            try:
                n = int(num_str)
            except ValueError:
                base = stem
                n = 1
        else:
            base = stem
            n = 1

        while True:
            candidate = dst.with_name(f"{base}_dupe({n}){ext}")
            if not candidate.exists():
                return candidate
            n += 1
