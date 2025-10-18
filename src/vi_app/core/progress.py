# src\vi_app\core\progress.py
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable


# Phases the strategies/service may report
Phase = Literal["scan", "hash", "bucket", "cluster", "select", "move"]


@runtime_checkable
class ProgressReporter(Protocol):
    def start(self, phase: Phase, total: int | None = None, text: str | None = None) -> None: ...
    def update(self, phase: Phase, advance: int = 1, text: str | None = None) -> None: ...
    def end(self, phase: Phase) -> None: ...


class NoOpReporter:
    def start(self, phase: Phase, total: int | None = None, text: str | None = None) -> None:
        pass

    def update(self, phase: Phase, advance: int = 1, text: str | None = None) -> None:
        pass

    def end(self, phase: Phase) -> None:
        pass
