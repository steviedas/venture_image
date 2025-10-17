# vi_app/modules/dedup/strategies/base.py
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from ..schemas import DedupItem

__all__ = [
    "Phase",
    "ProgressReporter",
    "DedupStrategyBase",
    "NoOpReporter",
    "get_worker_count",
]

# Phases the strategies/service may report
Phase = Literal["scan", "hash", "bucket", "cluster", "select", "move"]


@runtime_checkable
class ProgressReporter(Protocol):
    def start(self, phase: Phase, total: int | None = None, text: str | None = None) -> None: ...
    def update(self, phase: Phase, advance: int = 1, text: str | None = None) -> None: ...
    def end(self, phase: Phase) -> None: ...


class DedupStrategyBase(ABC):
    """Strategy interface for dedup implementations."""
    @abstractmethod
    def run(self, root: Path, reporter: ProgressReporter | None = None) -> list[DedupItem]:
        raise NotImplementedError


class NoOpReporter:
    def start(self, phase: Phase, total: int | None = None, text: str | None = None) -> None:  # noqa: D401
        pass
    def update(self, phase: Phase, advance: int = 1, text: str | None = None) -> None:  # noqa: D401
        pass
    def end(self, phase: Phase) -> None:  # noqa: D401
        pass


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
