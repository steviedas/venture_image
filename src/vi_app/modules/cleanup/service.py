# src/vi_app/modules/cleanup/service.py
from __future__ import annotations

import errno
import os
import re
import shutil
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image
from pillow_heif import register_heif_opener

from vi_app.core.errors import BadRequest
from vi_app.core.paths import ensure_within_root
from vi_app.core.progress import ProgressReporter

from .schemas import (
    MoveItem,
    RenameBySequenceResponse,
    RenamedItem,
    SortRequest,
    SortStrategy,
)
from .strategies.base import SortStrategyBase
from .strategies.by_date import SortByDateStrategy
from .strategies.by_location import SortByLocationStrategy


class CleanupService:
    """Base class with shared helpers; no module-level functions."""

    IMAGE_EXTS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".tif",
        ".tiff",
        ".bmp",
        ".webp",
        ".heic",
        ".heif",
        ".gif",
    }

    # NEW: supported video formats
    VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".wmv", ".3gp", ".webm"}

    _HEIF_REGISTERED = False  # lazy, best-effort

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._ensure_heif_registered()

    # ---- env / platform helpers -------------------------------------------------

    @classmethod
    def _ensure_heif_registered(cls) -> None:
        if cls._HEIF_REGISTERED:
            return
        try:
            register_heif_opener()
            cls._HEIF_REGISTERED = True
        except Exception:
            cls._HEIF_REGISTERED = True

    @staticmethod
    def _auto_worker_count() -> int:
        override = os.getenv("VI_RENAME_WORKERS")
        if override:
            try:
                n = int(override)
                return max(1, min(64, n))
            except ValueError:
                pass
        ncpu = os.cpu_count() or 4
        return max(4, min(16, ncpu * 2))  # I/O-bound heuristic

    # ---- filesystem traversal ---------------------------------------------------

    def _iter_files(self) -> Iterable[Path]:
        return (p for p in self.root.rglob("*") if p.is_file())

    @staticmethod
    def _iter_dirs_bottom_up(root: Path) -> Iterable[Path]:
        yield from sorted(
            (d for d in root.rglob("*") if d.is_dir()),
            key=lambda x: len(x.parts),
            reverse=True,
        )

    @staticmethod
    def _walk_dirs(root: Path, recurse: bool) -> Iterator[Path]:
        root = root.resolve()
        yield root
        if recurse:
            for p in root.rglob("*"):
                if p.is_dir():
                    yield p

    @classmethod
    def _iter_images(cls, dir_path: Path) -> list[Path]:
        return sorted(
            [
                p
                for p in dir_path.iterdir()
                if p.is_file() and p.suffix.lower() in cls.IMAGE_EXTS
            ]
        )

    # NEW: videos in a directory
    @classmethod
    def _iter_videos(cls, dir_path: Path) -> list[Path]:
        return sorted(
            [
                p
                for p in dir_path.iterdir()
                if p.is_file() and p.suffix.lower() in cls.VIDEO_EXTS
            ]
        )

    # ---- generic file ops -------------------------------------------------------

    @staticmethod
    def _unique_path(dst: Path) -> Path:
        if not dst.exists():
            return dst
        stem, suffix = dst.stem, dst.suffix
        i = 1
        while True:
            cand = dst.with_name(f"{stem}_{i}{suffix}")
            if not cand.exists():
                return cand
            i += 1

    @classmethod
    def _safe_move(cls, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst = cls._unique_path(dst)
        try:
            src.rename(dst)
        except OSError as e:
            if e.errno == errno.EXDEV:
                shutil.move(str(src), str(dst))
            else:
                raise

    @classmethod
    def _safe_rename(cls, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            try:
                if src.resolve() != dst.resolve():
                    dst = cls._unique_path(dst)
            except Exception:
                dst = cls._unique_path(dst)
        try:
            src.rename(dst)
        except OSError as e:
            if e.errno == errno.EXDEV:
                shutil.move(str(src), str(dst))
            else:
                raise

    # ---- exif/datetime helpers --------------------------------------------------

    @staticmethod
    def _parse_exif_datetime(value: str) -> datetime | None:
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S%z"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def _filesystem_earliest_dt(path: Path) -> datetime:
        stat = path.stat()
        candidates = [
            getattr(stat, n)
            for n in ("st_ctime", "st_mtime", "st_atime")
            if hasattr(stat, n)
        ]
        return (
            datetime.fromtimestamp(min(candidates))
            if candidates
            else datetime.fromtimestamp(0)
        )

    def _get_datetime_taken(self, path: Path) -> datetime:
        try:
            with Image.open(path) as im:
                exif = im.getexif()
                if exif:
                    for tag in (
                        36867,
                        36868,
                        306,
                    ):  # DateTimeOriginal, Digitized, DateTime
                        v = exif.get(tag)
                        if isinstance(v, bytes):
                            try:
                                v = v.decode(errors="ignore")
                            except Exception:
                                v = None
                        if v:
                            dt = self._parse_exif_datetime(str(v))
                            if dt:
                                return dt
        except Exception:
            pass
        return self._filesystem_earliest_dt(path)


# ------------------------------------------------------------------------------
# Services
# ------------------------------------------------------------------------------


class RemoveFilesService(CleanupService):
    def run(
        self, patterns: list[str], dry_run: bool, remove_empty_dirs: bool
    ) -> list[Path]:
        if not patterns:
            raise BadRequest("At least one pattern is required.")

        compiled: list[re.Pattern[str]] = []
        for pat in patterns:
            if any(ch in pat for ch in r".*+?^$[](){}|\\"):
                compiled.append(re.compile(pat, re.IGNORECASE))
            else:
                compiled.append(re.compile(re.escape(pat), re.IGNORECASE))

        to_delete: list[Path] = []
        for f in self._iter_files():
            s = str(f)
            if any(rx.search(s) for rx in compiled):
                to_delete.append(f)

        if not dry_run:
            for f in to_delete:
                ensure_within_root(f, self.root)
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass

            if remove_empty_dirs:
                for d in self._iter_dirs_bottom_up(self.root):
                    try:
                        next(d.iterdir())
                    except StopIteration:
                        try:
                            d.rmdir()
                        except Exception:
                            pass

        return to_delete


class RemoveFoldersService(CleanupService):
    def run(self, folder_names: list[str], dry_run: bool) -> list[Path]:
        if not folder_names:
            raise BadRequest("At least one folder name is required.")

        targets: list[Path] = []
        names_lower = {n.lower() for n in folder_names}

        for d in self._iter_dirs_bottom_up(self.root):
            if d.name.lower() in names_lower:
                targets.append(d)

        if not dry_run:
            for d in targets:
                ensure_within_root(d, self.root)
                shutil.rmtree(d, ignore_errors=True)

        return targets


class SortService(CleanupService):
    """Delegates to sort strategies, then applies safe moves."""

    @staticmethod
    def _select(strategy: SortStrategy) -> SortStrategyBase:
        return (
            SortByLocationStrategy()
            if strategy == SortStrategy.by_location
            else SortByDateStrategy()
        )

    def plan(
        self, req: SortRequest, reporter: ProgressReporter | None = None
    ) -> list[MoveItem]:
        strat = self._select(req.strategy)
        pairs = strat.run(
            self.root, Path(req.dst_root) if req.dst_root else None, reporter=reporter
        )
        return [MoveItem(src=str(s), dst=str(d)) for s, d in pairs]

    def apply(
        self, req: SortRequest, reporter: ProgressReporter | None = None
    ) -> list[MoveItem]:
        strat = self._select(req.strategy)
        pairs = strat.run(
            self.root, Path(req.dst_root) if req.dst_root else None, reporter=reporter
        )
        for src, dst in pairs:
            try:
                if src.resolve() == dst.resolve():
                    continue
            except Exception:
                pass
            self._safe_move(src, dst)
        return [MoveItem(src=str(s), dst=str(d)) for s, d in pairs]


class RenameService(CleanupService):
    """Parallel planning, two-phase apply, stable per-directory numbering."""

    def __init__(self, root: Path, recurse: bool, zero_pad: int):
        super().__init__(root)
        self.recurse = recurse
        self.zero_pad = zero_pad

    # ---- planning (parallel date extraction) -----------------------------------

    def _sequence_names(
        self, dir_path: Path, files: list[Path]
    ) -> list[tuple[Path, Path]]:
        results: list[tuple[datetime, Path]] = []
        workers = self._auto_worker_count()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self._get_datetime_taken, p): p for p in files}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    dt = fut.result() or datetime.min
                except Exception:
                    dt = datetime.min
                results.append((dt, p))

        results.sort(key=lambda t: (t[0], t[1].name.lower()))
        pairs: list[tuple[Path, Path]] = []
        for idx, (_, p) in enumerate(results, start=1):
            seq = f"{idx:0{self.zero_pad}d}"
            new_name = f"IMG_{seq}{p.suffix.upper()}"
            pairs.append((p, dir_path / new_name))
        return pairs

    # NEW: plan video names per format (per directory)
    def _sequence_video_names(
        self, dir_path: Path, files: list[Path], zero_pad: int
    ) -> list[tuple[Path, Path]]:
        """
        Group by file extension and create sequences per format:
        VID_000001.MP4, VID_000002.MP4, … and separately VID_000001.MOV, …
        Order within a format is by earliest filesystem datetime, then name.
        """
        groups: dict[str, list[Path]] = {}
        for p in files:
            groups.setdefault(p.suffix.lower(), []).append(p)

        pairs: list[tuple[Path, Path]] = []
        for _ext, group in sorted(groups.items()):
            items = sorted(
                ((self._filesystem_earliest_dt(p), p) for p in group),
                key=lambda t: (t[0], t[1].name.lower()),
            )
            for idx, (_, p) in enumerate(items, start=1):
                seq = f"{idx:0{zero_pad}d}"
                new_name = f"VID_{seq}{p.suffix.upper()}"
                pairs.append((p, dir_path / new_name))
        return pairs

    def plan(
        self, on_discover: Callable[[int], None] | None = None
    ) -> list[RenamedItem]:
        items: list[RenamedItem] = []
        discovered = 0
        for d in self._walk_dirs(self.root, self.recurse):
            files = self._iter_images(d)
            if not files:
                continue
            discovered += len(files)
            if on_discover:
                on_discover(discovered)
            for src, dst in self._sequence_names(d, files):
                if src.name == dst.name:
                    continue
                items.append(RenamedItem(src=str(src), dst=str(dst)))
        return items

    def enumerate_targets(
        self, on_discover: Callable[[int], None] | None = None
    ) -> list[tuple[Path, Path]]:
        items = self.plan(on_discover=on_discover)
        return [(Path(it.src), Path(it.dst)) for it in items]

    # NEW: enumerate video targets with a caller-provided zero-pad
    def enumerate_video_targets(
        self, zero_pad: int, on_discover: Callable[[int], None] | None = None
    ) -> list[tuple[Path, Path]]:
        items: list[RenamedItem] = []
        discovered = 0
        for d in self._walk_dirs(self.root, self.recurse):
            files = self._iter_videos(d)
            if not files:
                continue
            discovered += len(files)
            if on_discover:
                on_discover(discovered)
            for src, dst in self._sequence_video_names(d, files, zero_pad):
                if src.name == dst.name:
                    continue
                items.append(RenamedItem(src=str(src), dst=str(dst)))
        return [(Path(it.src), Path(it.dst)) for it in items]

    # ---- apply (two-phase) ------------------------------------------------------

    @staticmethod
    def _stage_path_for(src: Path) -> Path:
        parent = src.parent
        stem, suffix = src.stem, src.suffix
        while True:
            candidate = parent / f"{stem}.__vi_tmp__{uuid4().hex[:8]}{suffix}"
            if not candidate.exists():
                return candidate

    def _apply_two_phase(
        self, targets: list[tuple[Path, Path]]
    ) -> list[tuple[Path, Path, bool, str | None]]:
        results: list[tuple[Path, Path, bool, str | None]] = []
        staged: list[tuple[Path, Path, Path]] = []  # (orig_src, tmp, dst)

        # Phase 1: stage everything
        for src, dst in targets:
            try:
                if src.resolve() == dst.resolve():
                    results.append((src, dst, False, "already_named"))
                    continue
                tmp = self._stage_path_for(src)
                src.rename(tmp)
                staged.append((src, tmp, dst))
            except Exception as e:
                results.append((src, dst, False, f"stage_error:{e.__class__.__name__}"))

        # Phase 2: move staged -> final
        for orig_src, tmp, dst in staged:
            try:
                final = dst
                try:
                    if final.exists() and tmp.resolve() != final.resolve():
                        final = self._unique_path(final)
                except Exception:
                    final = self._unique_path(final)
                tmp.rename(final)
                results.append((orig_src, final, True, None))
            except Exception as e:
                try:
                    if not orig_src.exists() and tmp.exists():
                        tmp.rename(orig_src)
                except Exception:
                    pass
                results.append(
                    (orig_src, dst, False, f"final_error:{e.__class__.__name__}")
                )

        return results

    def iter_apply(
        self, targets: list[tuple[Path, Path]] | None = None
    ) -> Iterator[tuple[Path, Path, bool, str | None]]:
        if targets is None:
            targets = self.enumerate_targets(on_discover=None)
        yield from self._apply_two_phase(targets)

    def apply(self) -> RenameBySequenceResponse:
        targets = self.enumerate_targets(on_discover=None)
        results = self._apply_two_phase(targets)
        items = [
            RenamedItem(src=str(src), dst=str(final))
            for src, final, ok, _ in results
            if ok
        ]
        groups_count = len({Path(src).parent for src, _, ok, _ in results if ok})
        return RenameBySequenceResponse(
            items=items,
            groups_count=groups_count,
            renamed_count=len(items),
        )
