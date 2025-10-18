# src\vi_app\modules\dedup\strategies\image_base.py
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from vi_app.core.progress import ProgressReporter
from .base import DedupStrategyBase


class ImageStrategyBase(DedupStrategyBase):
    """Small DRY base for strategies that operate over image files."""

    def __init__(self, exts: set[str] | None = None) -> None:
        self.exts = exts or {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".tif",
            ".tiff",
            ".bmp",
            ".heic",
            ".heif",
        }

    def _iter_images(self, root: Path, reporter: ProgressReporter | None = None) -> Iterable[Path]:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in self.exts:
                if reporter:
                    reporter.update("scan", 1, text=p.name)
                yield p
