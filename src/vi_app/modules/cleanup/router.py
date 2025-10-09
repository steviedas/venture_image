# src/vi_app/modules/cleanup/router.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from vi_app.core.errors import to_http

from .schemas import (
    FindMarkedDupesRequest,
    FindMarkedDupesResponse,
    RemoveFilesRequest,
    RemoveFilesResponse,
    RemoveFoldersRequest,
    RemoveFoldersResponse,
    # existing models...
    RenameBySequenceRequest,
    RenameBySequenceResponse,
    SortRequest,
    SortResponse,
)
from .service import (
    find_marked_dupes,
    remove_files,
    remove_folders,
    # existing service funcs...
    rename_by_sequence,
    sort_apply,
    sort_plan,
)

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


@router.post(
    path="/remove-files",
    response_model=RemoveFilesResponse,
    summary="Find and (optionally) delete files matching regex patterns",
    description=(
        "Recursively scans **root** and selects files whose full path matches any of "
        "the provided case-insensitive **regular expressions** in `patterns`. "
        "If `dry_run` is `true`, the endpoint only reports what *would* be deleted. "
        "When `dry_run` is `false`, it deletes the matched files and, if "
        "`remove_empty_dirs` is `true`, prunes any now-empty directories. "
        "Safety guardrails ensure deletions remain within `root`.\n\n"
        "**Note:** patterns are regex (not globs). Examples: `\\.tmp$`, "
        "`_dupe\\(\\d+\\)`, `(?i)thumbs\\.db$`."
    ),
)
def remove_files_endpoint(req: RemoveFilesRequest) -> RemoveFilesResponse:
    try:
        deleted = remove_files(
            Path(req.root), req.patterns, req.dry_run, req.remove_empty_dirs
        )
        return RemoveFilesResponse(
            count=len(deleted),
            paths=[str(p) for p in deleted],
            dry_run=req.dry_run,
        )
    except Exception as err:
        raise to_http(err) from err


@router.post(
    path="/remove-folders",
    response_model=RemoveFoldersResponse,
    summary="Find and (optionally) remove directories by name",
    description=(
        "Recursively scans `root` for directories whose **name** matches any in "
        "`folder_names` (case-insensitive). If `dry_run` is true, it only reports the "
        "directories that would be removed. If false, it removes each matched directory "
        "and its entire subtree. Safety checks ensure paths remain within `root`."
    ),
)
def remove_folders_endpoint(req: RemoveFoldersRequest) -> RemoveFoldersResponse:
    try:
        removed = remove_folders(Path(req.root), req.folder_names, req.dry_run)
        return RemoveFoldersResponse(
            count=len(removed),
            paths=[str(p) for p in removed],
            dry_run=req.dry_run,
        )
    except Exception as err:
        raise to_http(err) from err


@router.post(
    "/find-marked-dupes",
    response_model=FindMarkedDupesResponse,
    summary="List files marked as duplicates by a filename-suffix regex",
    description=(
        "Recursively scans `root` and returns files whose **filename stem** "
        "(without extension) matches `suffix_pattern` (regex). "
        "Useful for locating files previously marked like `*_dupe(1)`."
    ),
)
def find_marked_dupes_endpoint(req: FindMarkedDupesRequest) -> FindMarkedDupesResponse:
    try:
        items = find_marked_dupes(Path(req.root), req.suffix_pattern)
        return FindMarkedDupesResponse(count=len(items), paths=[str(p) for p in items])
    except Exception as err:
        raise to_http(err) from err


@router.post(
    path="/sort",
    response_model=SortResponse,
    summary="Sort images (by date or location) as part of cleanup",
    description=(
        "Plan or apply sorting of images under `src_root` using the selected `strategy`.\n\n"
        "- `by_date` → `YYYY/MM/filename`\n"
        "- `by_location` → `City_Country/filename` (falls back to Country or `Unknown`)\n\n"
        "`dry_run=true` returns planned moves only; `dry_run=false` applies them."
    ),
)
def cleanup_sort_endpoint(req: SortRequest) -> SortResponse:
    try:
        moves = sort_plan(req) if req.dry_run else sort_apply(req)
        return SortResponse(
            dry_run=req.dry_run,
            strategy=req.strategy,
            moves_count=len(moves),
            moves=moves,
        )
    except Exception as err:
        raise to_http(err) from err


@router.post(
    path="/rename",
    response_model=RenameBySequenceResponse,
    summary="Rename images in each directory to IMG_XXXXXX ordered by date taken",
    description=(
        "For each directory (and sub-directory when `recurse=true`), sort images by "
        "**date taken** (EXIF DateTimeOriginal/Digitized/DateTime). If missing, fall back to the earliest "
        "available filesystem timestamp. Then rename within that directory to `IMG_000001`, `IMG_000002`, ... "
        "preserving the original file extension and resetting the sequence **per directory**.\n\n"
        "When `dry_run=true` (default), returns the planned renames only. "
        "When `dry_run=false`, performs the renames safely (two-phase to avoid collisions)."
    ),
)
def rename_sequence_endpoint(req: RenameBySequenceRequest) -> RenameBySequenceResponse:
    try:
        return rename_by_sequence(req)
    except Exception as err:
        raise to_http(err) from err
