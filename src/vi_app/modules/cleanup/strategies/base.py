# src/vi_app/modules/cleanup/strategies/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from vi_app.core.media_types import IMAGE_EXTS
from vi_app.core.progress import ProgressReporter


class SortStrategyBase(ABC):
    """DRY base for cleanup sorting strategies."""

    exts = IMAGE_EXTS

    def iter_images(
        self, root: Path, reporter: ProgressReporter | None = None
    ) -> Iterable[Path]:
        root = root.resolve()
        if reporter:
            reporter.start("scan", total=None, text="Discovering images…")
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in self.exts:
                if reporter:
                    reporter.update("scan", 1, text=p.name)
                yield p
        if reporter:
            reporter.end("scan")

    @abstractmethod
    def run(
        self,
        src_root: Path,
        dst_root: Path | None,
        reporter: ProgressReporter | None = None,
    ) -> list[tuple[Path, Path]]:
        """Return a list of (src, dst) pairs."""
        raise NotImplementedError
