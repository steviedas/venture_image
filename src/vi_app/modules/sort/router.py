# src/vi_app/modules/sort/router.py
from fastapi import APIRouter

from . import service
from .schemas import SortRequest

router = APIRouter(prefix="/sort", tags=["sort"])


@router.post("/plan")
def plan(req: SortRequest):
    return [(str(s), str(d)) for s, d in service.plan(req)]


@router.post("/apply")
def apply(req: SortRequest):
    return [(str(s), str(d)) for s, d in service.apply(req)]
