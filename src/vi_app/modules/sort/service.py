# src/vi_app/modules/sort/service.py
from pathlib import Path

from .schemas import SortRequest, SortStrategy
from .strategies import by_date, by_location


def _select(strategy: SortStrategy):
    return by_date if strategy == SortStrategy.date else by_location


def plan(req: SortRequest):
    strat = _select(req.strategy)
    return strat.plan(Path(req.src_root), Path(req.dst_root) if req.dst_root else None)


def apply(req: SortRequest):
    moves = plan(req)
    if req.dry_run:
        return moves
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
    return moves
