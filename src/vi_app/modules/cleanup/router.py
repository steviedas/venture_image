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
)
from .service import find_marked_dupes, remove_files, remove_folders

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
