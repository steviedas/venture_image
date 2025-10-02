from fastapi import APIRouter

from . import service
from .schemas import DedupItem, DedupRequest

router = APIRouter(prefix="/dedup", tags=["dedup"])


@router.post("/plan", response_model=list[DedupItem])
def plan(req: DedupRequest):
    return service.plan(req)


@router.post("/apply", response_model=list[DedupItem])
def apply(req: DedupRequest):
    return service.apply(req)
