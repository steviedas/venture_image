# src/vi_app/modules/cleanup/service.py
from __future__ import annotations

import errno
import re
import shutil
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image

from vi_app.core.errors import BadRequest
from vi_app.core.paths import ensure_within_root

from .schemas import MoveItem, SortRequest, SortStrategy
from .strategies import by_date as sort_by_date
from .strategies import by_location as sort_by_location

# Try to register HEIC/HEIF opener if available (safe if missing)
try:
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:
    pass

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .schemas import (
    RenameBySequenceRequest,
    RenameBySequenceResponse,
    RenamedItem,
)

_IMAGE_EXTS = {
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


def _iter_files(root: Path) -> Iterable[Path]:
    return (p for p in root.rglob("*") if p.is_file())


def _iter_dirs(root: Path) -> Iterable[Path]:
    # bottom-up to remove empty dirs safely
    yield from sorted(
        (d for d in root.rglob("*") if d.is_dir()),
        key=lambda x: len(x.parts),
        reverse=True,
    )


def remove_files(
    root: Path, patterns: list[str], dry_run: bool, remove_empty_dirs: bool
) -> list[Path]:
    if not patterns:
        raise BadRequest("At least one pattern is required.")

    root = root.resolve()
    # Compile substrings to case-insensitive regexes or accept globs
    regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
    to_delete: list[Path] = []

    for f in _iter_files(root):
        s = str(f)
        if any(r.search(s) for r in regexes):
            to_delete.append(f)

    if not dry_run:
        for f in to_delete:
            ensure_within_root(f, root)
            try:
                f.unlink(missing_ok=True)
            except Exception:
                # continue best-effort; could log
                pass

        if remove_empty_dirs:
            for d in _iter_dirs(root):
                if not any(d.iterdir()):
                    try:
                        d.rmdir()
                    except Exception:
                        pass

    return to_delete


def remove_folders(root: Path, folder_names: list[str], dry_run: bool) -> list[Path]:
    if not folder_names:
        raise BadRequest("At least one folder name is required.")

    root = root.resolve()
    targets = []
    names_lower = {n.lower() for n in folder_names}

    for d in _iter_dirs(root):
        if d.name.lower() in names_lower:
            targets.append(d)

    if not dry_run:
        for d in targets:
            ensure_within_root(d, root)
            # remove tree
            for p in sorted(d.rglob("*"), key=lambda x: len(x.parts), reverse=True):
                if p.is_file():
                    p.unlink(missing_ok=True)
                else:
                    p.rmdir()
            d.rmdir()

    return targets


def find_marked_dupes(root: Path, suffix_regex: str) -> list[Path]:
    root = root.resolve()
    rx = re.compile(suffix_regex, re.IGNORECASE)
    return [p for p in _iter_files(root) if rx.search(p.stem)]


def _select_sort_plan(strategy: SortStrategy):
    # each strategy exposes: plan(src_root: Path, dst_root: Path|None) -> list[tuple[Path, Path]]
    if strategy == SortStrategy.by_location:
        return sort_by_location.plan
    return sort_by_date.plan


def _safe_move(src: Path, dst: Path) -> None:
    """Rename if possible; if cross-device (EXDEV), copy+delete. Avoid clobbering."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst = _unique_path(dst)
    try:
        src.rename(dst)
    except OSError as e:
        if e.errno == errno.EXDEV:
            shutil.move(str(src), str(dst))  # copy then remove
        else:
            raise


def _make_sort_moves(req: SortRequest) -> list[tuple[Path, Path]]:
    plan_fn = _select_sort_plan(req.strategy)
    return plan_fn(Path(req.src_root), Path(req.dst_root) if req.dst_root else None)


def sort_plan(req: SortRequest) -> list[MoveItem]:
    moves = _make_sort_moves(req)
    return [MoveItem(src=str(s), dst=str(d)) for s, d in moves]


def sort_apply(req: SortRequest) -> list[MoveItem]:
    moves = _make_sort_moves(req)
    for src, dst in moves:
        try:
            if src.resolve() == dst.resolve():
                continue  # nothing to do
        except Exception:
            pass
        _safe_move(src, dst)
    return [MoveItem(src=str(s), dst=str(d)) for s, d in moves]


def _walk_dirs(root: Path, recurse: bool) -> Iterator[Path]:
    root = root.resolve()
    yield root
    if recurse:
        for p in root.rglob("*"):
            if p.is_dir():
                yield p


def _iter_images(dir_path: Path) -> list[Path]:
    return sorted(
        [
            p
            for p in dir_path.iterdir()
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
        ]
    )


# EXIF tag ids we care about
_EXIF_DATE_TAGS = {
    36867,  # DateTimeOriginal
    36868,  # DateTimeDigitized
    306,  # DateTime (fallback)
}


def _parse_exif_datetime(value: str) -> datetime | None:
    # Common EXIF format: "YYYY:MM:DD HH:MM:SS"
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    return None


def _get_datetime_taken(path: Path) -> datetime | None:
    """
    Try EXIF DateTimeOriginal / Digitized / DateTime.
    If absent, fall back to the earliest available filesystem time (ctime/mtime).
    """
    try:
        with Image.open(path) as im:
            exif = im.getexif()  # PIL returns a dict-like of tag->value
            if exif:
                # Prefer DateTimeOriginal, then Digitized, then DateTime
                for tag in (36867, 36868, 306):
                    v = exif.get(tag)
                    if isinstance(v, bytes):
                        try:
                            v = v.decode(errors="ignore")
                        except Exception:
                            v = None
                    if v:
                        dt = _parse_exif_datetime(str(v))
                        if dt:
                            return dt
    except Exception:
        # Ignore unreadable EXIF / unsupported formats
        pass

    # Filesystem fallback: earliest timestamp we can get
    try:
        stat = path.stat()
        # On many platforms, ctime may be creation time; pick earliest known
        candidates = [
            getattr(stat, n)
            for n in ("st_ctime", "st_mtime", "st_atime")
            if hasattr(stat, n)
        ]
        if candidates:
            return datetime.fromtimestamp(min(candidates))
    except Exception:
        pass
    return None


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


def _stage_path_for(src: Path) -> Path:
    """
    Create a unique temporary path in the same directory as `src`.
    Using a reserved marker so we can recognize temps if needed.
    """
    parent = src.parent
    stem, suffix = src.stem, src.suffix
    # Example: IMG_000123.__vi_tmp__a1b2c3d4.PNG
    while True:
        candidate = parent / f"{stem}.__vi_tmp__{uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate


def _safe_rename(src: Path, dst: Path) -> None:
    """
    Rename if possible; if the destination exists (different file), pick a unique variant.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Avoid clobbering existing unrelated files
    if dst.exists():
        try:
            if src.resolve() != dst.resolve():
                dst = _unique_path(dst)
        except Exception:
            dst = _unique_path(dst)
    try:
        src.rename(dst)
    except OSError as e:
        # Very rare for same-dir renames, but be defensive
        if e.errno == errno.EXDEV:
            shutil.move(str(src), str(dst))
        else:
            raise


def rename_by_sequence_plan(
    req: RenameBySequenceRequest,
    on_discover: Callable[[int], None] | None = None,
) -> list[RenamedItem]:
    root = Path(req.root).resolve()
    items: list[RenamedItem] = []
    discovered = 0  # <--- add this

    # use the renamed walker to avoid clobbering _iter_dirs used elsewhere
    for d in _walk_dirs(root, req.recurse):
        files = _iter_images(d)
        if not files:
            continue

        # live discovery callback (updates the spinner text)
        discovered += len(files)
        if on_discover:
            on_discover(discovered)

        for src, dst in _sequence_names(d, files, req.zero_pad):
            if src.name == dst.name:
                continue
            items.append(RenamedItem(src=str(src), dst=str(dst)))
    return items


def rename_by_sequence_apply(req: RenameBySequenceRequest) -> RenameBySequenceResponse:
    targets = enumerate_rename_targets(req)
    results = _apply_two_phase(targets)

    # Build response from successful items
    items = [
        RenamedItem(src=str(src), dst=str(final)) for src, final, ok, _ in results if ok
    ]
    groups_count = len({Path(src).parent for src, _, ok, _ in results if ok})
    renamed_count = len(items)

    return RenameBySequenceResponse(
        items=items,
        groups_count=groups_count,
        renamed_count=renamed_count,
    )


def rename_by_sequence(req: RenameBySequenceRequest) -> RenameBySequenceResponse:
    if req.dry_run:
        items = rename_by_sequence_plan(req)  # list[RenamedItem]
        groups = {str(Path(i.dst).parent) for i in items}
        return RenameBySequenceResponse(
            dry_run=True,
            groups_count=len(groups),
            files_count=len(items),
            renamed_count=0,  # plan => no renames performed yet
            items=items,
        )
    else:
        # apply path already returns RenameBySequenceResponse
        return rename_by_sequence_apply(req)


def enumerate_rename_targets(
    req: RenameBySequenceRequest,
    on_discover: Callable[[int], None] | None = None,
) -> list[tuple[Path, Path]]:
    plan_req = RenameBySequenceRequest(
        root=req.root, recurse=req.recurse, zero_pad=req.zero_pad, dry_run=True
    )
    # call the plan with the live-discovery callback
    items = rename_by_sequence_plan(plan_req, on_discover=on_discover)
    return [(Path(it.src), Path(it.dst)) for it in items]


def _apply_two_phase(
    targets: list[tuple[Path, Path]],
) -> list[tuple[Path, Path, bool, str | None]]:
    """
    Execute a two-phase rename for all targets:
      1) stage:  src -> tmp (in same folder)
      2) final:  tmp -> dst  (dst uniquified if pre-existing)
    Returns a list of (original_src, final_dst, ok, reason).
    """
    results: list[tuple[Path, Path, bool, str | None]] = []
    staged: list[tuple[Path, Path, Path]] = []  # (orig_src, tmp, dst)

    # Phase 1: stage everything
    for src, dst in targets:
        try:
            if src.resolve() == dst.resolve():
                # Already named as desired
                results.append((src, dst, False, "already_named"))
                continue

            tmp = _stage_path_for(src)
            src.rename(tmp)
            staged.append((src, tmp, dst))
        except Exception as e:
            results.append((src, dst, False, f"stage_error:{e.__class__.__name__}"))

    # Phase 2: move staged -> final (respect existing files by uniquifying)
    for orig_src, tmp, dst in staged:
        try:
            final = dst
            try:
                # If something already occupies the target name, pick a unique underscore path
                if final.exists() and tmp.resolve() != final.resolve():
                    final = _unique_path(final)  # your underscore-style helper
            except Exception:
                final = _unique_path(final)

            tmp.rename(final)
            results.append((orig_src, final, True, None))
        except Exception as e:
            # Best-effort rollback to original name (avoid leaving tmp files)
            try:
                if not orig_src.exists() and tmp.exists():
                    tmp.rename(orig_src)
            except Exception:
                pass
            results.append(
                (orig_src, dst, False, f"final_error:{e.__class__.__name__}")
            )

    return results


def iter_rename_by_sequence(
    req: RenameBySequenceRequest,
    targets: list[tuple[Path, Path]] | None = None,
) -> Iterator[tuple[Path, Path, bool, str | None]]:
    """
    Iterate through the prepared plan and perform a two-phase rename.
    Yields (original_src, final_dst, ok, reason).
    """
    if targets is None:
        targets = enumerate_rename_targets(req)

    if req.dry_run:
        for src, dst in targets:
            yield (src, dst, True, "dry_run")
        return

    # Two-phase apply; yield per file after the final move
    for src, final, ok, reason in _apply_two_phase(targets):
        yield (src, final, ok, reason)


def _auto_worker_count() -> int:
    """
    Choose a sensible default number of threads for I/O-bound metadata reads.
    Override via env VI_RENAME_WORKERS, e.g. VI_RENAME_WORKERS=12.
    """
    override = os.getenv("VI_RENAME_WORKERS")
    if override:
        try:
            n = int(override)
            return max(1, min(64, n))
        except ValueError:
            pass
    ncpu = os.cpu_count() or 4
    return max(4, min(16, ncpu * 2))  # I/O-bound heuristic


def _sequence_names(
    dir_path: Path, files: list[Path], zero_pad: int
) -> list[tuple[Path, Path]]:
    """
    Decide the new names within a single directory. Sort by date taken (asc), then name.
    Returns (src, dst) pairs. Keeps original extension, normalizes to upper-case 'IMG_' prefix.
    Parallelized date extraction for speed.
    """
    # --- collect (dt, path) in parallel ---
    results: list[tuple[datetime, Path]] = []
    workers = _auto_worker_count()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_get_datetime_taken, p): p for p in files}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                dt = fut.result() or datetime.min
            except Exception:
                dt = datetime.min
            results.append((dt, p))

    # --- sort and build pairs ---
    results.sort(key=lambda t: (t[0], t[1].name.lower()))
    pairs: list[tuple[Path, Path]] = []
    for idx, (_, p) in enumerate(results, start=1):
        seq = f"{idx:0{zero_pad}d}"
        new_name = f"IMG_{seq}{p.suffix.upper()}"
        pairs.append((p, dir_path / new_name))
    return pairs
