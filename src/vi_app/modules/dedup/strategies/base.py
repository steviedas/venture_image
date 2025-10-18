# src/vi_app/modules/dedup/strategies/base.py
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from vi_app.core.progress import ProgressReporter

__all__ = [
    "DedupStrategyBase",
    "get_worker_count",
]


class DedupStrategyBase(ABC):
    """Strategy interface for dedup implementations."""

    @abstractmethod
    def run(self, root: Path, reporter: ProgressReporter | None = None) -> list["DedupItem"]:
        raise NotImplementedError


def get_worker_count(
    *,
    env_var: str = "VI_DEDUP_WORKERS",
    io_bound: bool = True,
    minimum: int = 4,
    cap: int = 64,
) -> int:
    """
    Decide a sensible default pool size. Override via env var `VI_DEDUP_WORKERS`.

    io_bound=True  -> allow more threads (e.g., hashing/decoding + disk IO)
    io_bound=False -> closer to CPU count
    """
    # explicit override
    val = os.getenv(env_var)
    if val:
        try:
            n = int(val)
            return max(1, n)
        except ValueError:
            pass

    cpu = os.cpu_count() or 4
    n = (cpu * 4) if io_bound else cpu
    n = max(minimum, min(cap, n))
    return n
