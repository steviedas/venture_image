# src/vi_app/modules/cleanup/router.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from vi_app.core.errors import to_http

from .schemas import (
    FindMarkedDupesRequest,
    FindMarkedDupesResponse,
    MoveItem,
    RemoveFilesRequest,
    RemoveFilesResponse,
    RemoveFoldersRequest,
    RemoveFoldersResponse,
    # existing models...
    RenameBySequenceRequest,
    RenameBySequenceResponse,
    SortRequest,
)
from .service import (
    FindMarkedDupesService,
    RemoveFilesService,
    RemoveFoldersService,
    RenameService,
    SortService,
)

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


@router.post(
    "/remove-files",
    response_model=RemoveFilesResponse,
    summary="Remove files by pattern",
    description="Delete files matching glob/regex/substring patterns. Supports dry-run and optional empty dir pruning.",
)
def remove_files_endpoint(req: RemoveFilesRequest):
    try:
        svc = RemoveFilesService(Path(req.root))
        deleted = svc.run(req.patterns, req.dry_run, req.remove_empty_dirs)
        return RemoveFilesResponse(
            count=len(deleted), paths=deleted, dry_run=req.dry_run
        )
    except Exception as err:
        raise to_http(err) from err


@router.post(
    "/remove-folders",
    response_model=RemoveFoldersResponse,
    summary="Remove whole folders by name",
    description="Delete folders (recursively) whose base name matches. Supports dry-run.",
)
def remove_folders_endpoint(req: RemoveFoldersRequest):
    try:
        svc = RemoveFoldersService(Path(req.root))
        removed = svc.run(req.folder_names, req.dry_run)
        return RemoveFoldersResponse(
            count=len(removed), paths=removed, dry_run=req.dry_run
        )
    except Exception as err:
        raise to_http(err) from err


@router.post(
    "/find-marked-dupes",
    response_model=FindMarkedDupesResponse,
    summary="Find files that look like duplicates by name pattern",
    description="Search for common duplicate markers (e.g. 'copy', '(1)') via regex/substring.",
)
def find_marked_dupes_endpoint(req: FindMarkedDupesRequest):
    try:
        svc = FindMarkedDupesService(Path(req.root))
        items = svc.run(req.suffix_pattern)
        return FindMarkedDupesResponse(count=len(items), paths=items)
    except Exception as err:
        raise to_http(err) from err


@router.post(
    "/sort",
    response_model=list[MoveItem],
    summary="Sort images (by date or location)",
    description="Plan or apply moving images to structured folders. Respect dry-run.",
)
def sort_endpoint(req: SortRequest):
    try:
        svc = SortService(Path(req.src_root))
        moves = svc.plan(req) if req.dry_run else svc.apply(req)
        return moves
    except Exception as err:
        raise to_http(err) from err


@router.post(
    "/rename",
    response_model=RenameBySequenceResponse,
    summary="Per directory, rename images to IMG_XXXXXX ordered by date taken",
    description="Stable, deterministic renaming with two-phase apply. Dry-run prints the full plan.",
)
def rename_endpoint(req: RenameBySequenceRequest):
    try:
        svc = RenameService(Path(req.root), recurse=req.recurse, zero_pad=req.zero_pad)
        if req.dry_run:
            items = svc.plan()
            groups = {str(Path(i.dst).parent) for i in items}
            return RenameBySequenceResponse(
                items=items,
                groups_count=len(groups),
                renamed_count=0,
                dry_run=True,
            )
        return svc.apply()
    except Exception as err:
        raise to_http(err) from err
