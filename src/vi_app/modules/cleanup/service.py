# src/vi_app/modules/cleanup/service.py
from __future__ import annotations

import errno
import re
import shutil
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

from PIL import Image

from vi_app.core.errors import BadRequest
from vi_app.core.paths import ensure_within_root

from .schemas import MoveItem, SortRequest, SortStrategy

# import strategies (we'll move the files in step 3)
from .strategies import by_date as sort_by_date
from .strategies import by_location as sort_by_location

# Try to register HEIC/HEIF opener if available (safe if missing)
try:
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:
    pass

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


def _unique_path(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem, suffix = dst.stem, dst.suffix
    i = 1
    while True:
        cand = dst.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
        i += 1


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


def _iter_dirs(root: Path, recurse: bool) -> Iterator[Path]:
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


def _sequence_names(
    dir_path: Path, files: list[Path], zero_pad: int
) -> list[tuple[Path, Path]]:
    """
    Decide the new names within a single directory. Sort by date taken (asc), then name.
    Returns (src, dst) pairs. Keeps original extension, normalizes to upper-case 'IMG_' prefix.
    """
    # Sort files by (date_taken, name)
    with_dates = []
    for p in files:
        dt = _get_datetime_taken(p) or datetime.min
        with_dates.append((dt, p))
    with_dates.sort(key=lambda t: (t[0], t[1].name.lower()))

    pairs: list[tuple[Path, Path]] = []
    for idx, (_, p) in enumerate(with_dates, start=1):
        seq = f"{idx:0{zero_pad}d}"
        new_name = f"IMG_{seq}{p.suffix.upper()}"
        pairs.append((p, dir_path / new_name))
    return pairs


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


def rename_by_sequence_plan(req: RenameBySequenceRequest) -> list[RenamedItem]:
    root = Path(req.root).resolve()
    items: list[RenamedItem] = []
    for d in _iter_dirs(root, req.recurse):
        files = _iter_images(d)
        if not files:
            continue
        for src, dst in _sequence_names(d, files, req.zero_pad):
            if src.name == dst.name:
                # Already in correct format/position
                continue
            items.append(RenamedItem(src=str(src), dst=str(dst)))
    return items


def rename_by_sequence_apply(req: RenameBySequenceRequest) -> list[RenamedItem]:
    planned = rename_by_sequence_plan(req)
    # To avoid chain conflicts (A->B while B->C), do a two-phase rename:
    # 1) Temp-stamp each source to a hidden/unique intermediary within the same dir
    # 2) Move from temp to final name
    # This is robust and avoids overwrite/cycle issues.

    # Phase 1: create temporary unique names
    temp_pairs: list[tuple[Path, Path]] = []
    for it in planned:
        src = Path(it.src)
        tmp = src.with_name(f".___tmp___{src.name}")
        # ensure uniqueness
        if tmp.exists():
            tmp = _unique_path(tmp)
        src.rename(tmp)
        temp_pairs.append((tmp, Path(it.dst)))

    # Phase 2: move to final destinations
    for tmp, final in temp_pairs:
        _safe_rename(tmp, final)

    return planned


def rename_by_sequence(req: RenameBySequenceRequest) -> RenameBySequenceResponse:
    items = (
        rename_by_sequence_plan(req) if req.dry_run else rename_by_sequence_apply(req)
    )
    # Count groups: # of distinct directories that had at least one item
    groups = {str(Path(i.dst).parent) for i in items} or set()
    # Files considered = number of renames (we only count renamable files); if you want total files scanned, adjust.
    return RenameBySequenceResponse(
        dry_run=req.dry_run,
        groups_count=len(groups),
        files_count=len(items),
        renamed_count=len(items) if not req.dry_run else len(items),
        items=items,
    )
