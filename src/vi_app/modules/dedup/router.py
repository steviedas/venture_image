# src/vi_app/modules/dedup/router.py
from fastapi import APIRouter

from vi_app.core.errors import to_http

from . import service
from .schemas import DedupRequest, DedupResponse

router = APIRouter(prefix="/dedup", tags=["dedup"])


@router.post(
    path="",
    response_model=DedupResponse,
    summary="Detect duplicates and (optionally) move them",
    description=(
        "Find duplicate images under `root` using the selected `strategy`.\n\n"
        "- `content`: perceptual/near-duplicate matching (similar images)\n"
        "- `metadata`: exact byte-identical matching\n\n"
        "If `dry_run` is **true** (default), this only **reports** clusters. "
        "If `dry_run` is **false**, each duplicate is moved to `move_duplicates_to` "
        "(or a sibling `duplicate/` folder when not provided)."
    ),
)
def dedup(req: DedupRequest) -> DedupResponse:
    try:
        clusters = service.plan(req) if req.dry_run else service.apply(req)
        dup_count = sum(len(c.duplicates) for c in clusters)
        return DedupResponse(
            dry_run=req.dry_run,
            strategy=req.strategy,
            clusters_count=len(clusters),
            duplicates_count=dup_count,
            move_target=(req.move_duplicates_to if not req.dry_run else None),
            clusters=clusters,
        )
    except Exception as err:
        raise to_http(err) from err
