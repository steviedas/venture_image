from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from vi_app.core.errors import to_http

from .schemas import FindMarkedDupesRequest, RemoveFilesRequest, RemoveFoldersRequest
from .service import find_marked_dupes, remove_files, remove_folders

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


@router.post("/remove-files")
def remove_files_endpoint(req: RemoveFilesRequest):
    try:
        deleted = remove_files(
            Path(req.root), req.patterns, req.dry_run, req.remove_empty_dirs
        )
        return {
            "count": len(deleted),
            "paths": [str(p) for p in deleted],
            "dry_run": req.dry_run,
        }
    except Exception as err:  # noqa: BLE001 (if you enable that rule later)
        raise to_http(err) from err


@router.post("/remove-folders")
def remove_folders_endpoint(req: RemoveFoldersRequest):
    try:
        removed = remove_folders(Path(req.root), req.folder_names, req.dry_run)
        return {
            "count": len(removed),
            "paths": [str(p) for p in removed],
            "dry_run": req.dry_run,
        }
    except Exception as err:
        raise to_http(err) from err


@router.post("/find-marked-dupes")
def find_marked_dupes_endpoint(req: FindMarkedDupesRequest):
    try:
        items = find_marked_dupes(Path(req.root), req.suffix_pattern)
        return {"count": len(items), "paths": [str(p) for p in items]}
    except Exception as err:
        raise to_http(err) from err
