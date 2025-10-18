# src/vi_app/modules/cleanup/strategies/by_date.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image

from vi_app.core.paths import sanitize_filename
from vi_app.core.progress import ProgressReporter

from .base import SortStrategyBase


class SortByDateStrategy(SortStrategyBase):
    """Sort images into dst_root/YYYY/MM/filename based on EXIF or filesystem dates."""

    def run(
        self,
        src_root: Path,
        dst_root: Path | None,
        reporter: ProgressReporter | None = None,
    ) -> list[tuple[Path, Path]]:
        src_root = src_root.resolve()
        dst_root = (dst_root or src_root).resolve()

        moves: list[tuple[Path, Path]] = []
        for src in self.iter_images(src_root, reporter=reporter):
            dt = self._exif_datetime(src) or self._fs_datetime(src)
            year = f"{dt.year:04d}"
            month = f"{dt.month:02d}"
            dst_dir = dst_root / year / month
            dst = dst_dir / sanitize_filename(src.name)
            moves.append((src, dst))

        if reporter:
            reporter.start("select", total=len(moves), text="Planning moves…")
            reporter.end("select")
        return moves

    # ---- helpers (encapsulated) ----
    @staticmethod
    def _exif_datetime(p: Path) -> datetime | None:
        try:
            with Image.open(p) as im:
                exif = im.getexif() or {}
                tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
                ts = (
                    tags.get("DateTimeOriginal")
                    or tags.get("DateTime")
                    or tags.get("CreateDate")
                )
                if isinstance(ts, bytes):
                    ts = ts.decode(errors="ignore")
                if isinstance(ts, str):
                    ts = ts.replace("-", ":")
                    try:
                        return datetime.strptime(ts, "%Y:%m:%d %H:%M:%S")
                    except Exception:
                        with_s = ts.split(".")[0].replace("/", "-").replace(":", "-", 2)
                        try:
                            return datetime.fromisoformat(with_s)
                        except Exception:
                            return None
        except Exception:
            return None
        return None

    @staticmethod
    def _fs_datetime(p: Path) -> datetime:
        try:
            return datetime.fromtimestamp(p.stat().st_mtime)
        except Exception:
            return datetime(1970, 1, 1)
