# src/vi_app/modules/dedup/service.py
from pathlib import Path

from .schemas import DedupItem, DedupRequest, DedupStrategy
from .strategies import content as content_strat
from .strategies import metadata as metadata_strat


def _select(strategy: DedupStrategy):
    return content_strat if strategy == DedupStrategy.content else metadata_strat


def plan(req: DedupRequest) -> list[DedupItem]:
    strat = _select(req.strategy)
    return strat.run(Path(req.root))


def apply(req: DedupRequest) -> list[DedupItem]:
    items = plan(req)
    if req.dry_run:
        return items
    # move duplicates into a sibling "duplicate" folder (or configured path)
    for cluster in items:
        keep = Path(cluster.keep)
        for dup in cluster.duplicates:
            p = Path(dup)
            if not p.exists() or p.resolve() == keep.resolve():
                continue
            target_dir = Path(req.move_duplicates_to or (p.parent / "duplicate"))
            target_dir.mkdir(parents=True, exist_ok=True)
            p.rename(target_dir / p.name)
    return items
