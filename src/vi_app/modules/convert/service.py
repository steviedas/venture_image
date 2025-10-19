# src/vi_app/modules/convert/service.py
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageCms

from vi_app.core.progress import ProgressReporter
from vi_app.modules.cleanup.service import CleanupService  # reuse base: HEIF + workers

try:
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
    _HEIF_OK = True
except Exception:
    _HEIF_OK = False

from vi_app.core.paths import mirrored_output_path, sanitize_filename

_SUPPORTED_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".heic",
    ".heif",
    ".gif",
}
DEFAULT_CONVERT_SUBDIR = "converted"


class ConvertService(CleanupService):
    """
    Plan + parallel apply image conversions to JPEG, mirroring directory structure.
    Mirrors CleanupService/RenameService style: plan() / iter_apply() / apply().
    """

    def __init__(
        self,
        src_root: Path,
        dst_root: Path | None,
        recurse: bool,
        quality: int,
        overwrite: bool,
        flatten_alpha: bool,
        only_exts: set[str] | None = None,
        dry_run: bool = True,
    ):
        super().__init__(root=src_root)
        self.src_root = Path(src_root).expanduser().resolve()
        self.dst_root = (
            Path(dst_root).expanduser().resolve()
            if dst_root is not None
            else (self.src_root / DEFAULT_CONVERT_SUBDIR)
        )
        self.recurse = recurse
        self.quality = quality
        self.overwrite = overwrite
        self.flatten_alpha = flatten_alpha
        self.only_exts = {e.lower() for e in (only_exts or _SUPPORTED_EXTS)}
        self.dry_run = dry_run

    # ---------- planning ----------
    def _iter_images(self, reporter: ProgressReporter | None = None) -> Iterable[Path]:
        """Yield source images, optionally reporting 'scan' progress."""
        it = (
            (p for p in self.src_root.rglob("*"))
            if self.recurse
            else (p for p in self.src_root.iterdir())
        )
        for p in it:
            if p.is_file() and p.suffix.lower() in self.only_exts:
                if reporter:
                    reporter.update("scan", 1, text=p.name)
                yield p

    def enumerate_targets(
        self, reporter: ProgressReporter | None = None
    ) -> list[tuple[Path, Path]]:
        """Plan conversions as (src, dst) pairs and optionally report 'scan' start/end."""
        if reporter:
            reporter.start("scan", total=None, text="Discovering images…")
        pairs: list[tuple[Path, Path]] = []
        for src in self._iter_images(reporter=reporter):
            new_name = sanitize_filename(src.stem) + ".jpeg"
            dst = mirrored_output_path(src, self.src_root, self.dst_root, new_name)
            pairs.append((src, dst))
        if reporter:
            reporter.end("scan")
        return pairs

    # ---------- single conversion ----------
    def _to_jpeg(self, src: Path, dst: Path) -> tuple[bool, str | None]:
        if dst.exists() and not self.overwrite:
            return False, "exists"
        if self.dry_run:
            return True, "dry_run"

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                # capture metadata BEFORE transforms
                exif_bytes = im.info.get("exif")
                xmp_bytes = im.info.get("xmp")
                icc_bytes = im.info.get("icc_profile")

                # color management to sRGB if possible
                try:
                    if "icc_profile" in im.info and im.info["icc_profile"]:
                        srgb = ImageCms.createProfile("sRGB")
                        src_profile = ImageCms.ImageCmsProfile(
                            bytes(im.info["icc_profile"])
                        )
                        im = ImageCms.profileToProfile(
                            im, src_profile, srgb, outputMode="RGB"
                        )
                        icc_bytes = None  # don't embed old profile after conversion
                except Exception:
                    pass

                # alpha flattening
                if im.mode in ("RGBA", "LA") and self.flatten_alpha:
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    if im.mode != "RGBA":
                        im = im.convert("RGBA")
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")

                save_kwargs: dict[str, object] = {
                    "format": "JPEG",
                    "quality": self.quality,
                    "optimize": True,
                    "progressive": True,
                }
                if exif_bytes:
                    save_kwargs["exif"] = exif_bytes
                if xmp_bytes:
                    save_kwargs["xmp"] = xmp_bytes
                if icc_bytes:
                    save_kwargs["icc_profile"] = icc_bytes

                im.save(dst, **save_kwargs)

            return True, None
        except Exception as e:
            if src.suffix.lower() in {".heic", ".heif"} and not _HEIF_OK:
                return False, "heic_not_supported"
            return False, f"error:{e.__class__.__name__}"

    # ---------- high-level facade (mirrors DedupService style) ----------
    def plan(self, reporter: ProgressReporter | None = None) -> list[tuple[Path, Path]]:
        """Public plan API (phase-aware)."""
        return self.enumerate_targets(reporter=reporter)

    # ---------- apply (parallel) ----------
    def iter_apply(
        self,
        targets: Sequence[tuple[Path, Path]] | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> Iterator[tuple[Path, Path, bool, str | None]]:
        """
        Yield (src, dst, ok, reason) for each target. Runs in parallel using a thread pool.
        """
        targets = list(targets or self.enumerate_targets())
        if not targets:
            return iter(())  # empty iterator

        # dry-run fast path (no threads)
        if self.dry_run:
            for src, dst in targets:
                yield (src, dst, True, "dry_run")
                if on_progress:
                    on_progress(1)
            return

        workers = self._auto_worker_count()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(self._to_jpeg, src, dst): (src, dst) for src, dst in targets
            }
            for fut in as_completed(futs):
                src, dst = futs[fut]
                ok, reason = False, None
                try:
                    ok, reason = fut.result()
                except Exception as e:  # very defensive
                    ok, reason = False, f"error:{e.__class__.__name__}"
                if on_progress:
                    on_progress(1)
                yield (src, dst, ok, reason)

    def apply(
        self, reporter: ProgressReporter | None = None
    ) -> list[tuple[Path, Path, bool, str | None]]:
        """Public apply API (phase-aware)."""
        targets = self.enumerate_targets(reporter=reporter)
        total = len(targets)
        if reporter:
            reporter.start("convert", total=total, text="Converting to JPEG…")

        results: list[tuple[Path, Path, bool, str | None]] = []
        for src, dst, ok, reason in self.iter_apply(
            targets=targets,
            on_progress=(lambda n: reporter.update("convert", n) if reporter else None),
        ):
            results.append((src, dst, ok, reason))

        if reporter:
            reporter.end("convert")
        return results


# ----------------------------
# Video -> MP4 conversion
# ----------------------------


_VIDEO_EXTS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".mts",
    ".m2ts",
    ".3gp",
    ".wmv",
}


class Mp4ConvertService(CleanupService):
    """
    Plan + apply video conversions to MP4 (H.264/AAC), mirroring the directory structure.
    Parity with ConvertService: plan() / iter_apply() / apply(), with ProgressReporter phases.
    """

    def __init__(
        self,
        src_root: Path,
        dst_root: Path | None,
        recurse: bool,
        overwrite: bool,
        crf: int = 0,
        preset: str = "ultrafast",
        audio_bitrate: str = "320k",
        only_exts: set[str] | None = None,
        workers: int | None = None,
        extra_ffmpeg_args: list[str] | None = None,
        dry_run: bool = True,
    ):
        super().__init__(root=src_root)
        self.src_root = Path(src_root).expanduser().resolve()
        self.dst_root = (
            Path(dst_root).expanduser().resolve()
            if dst_root is not None
            else (self.src_root / DEFAULT_CONVERT_SUBDIR)
        )
        self.recurse = recurse
        self.overwrite = overwrite
        self.crf = crf
        self.preset = preset
        self.audio_bitrate = audio_bitrate
        self.only_exts = {e.lower() for e in (only_exts or _VIDEO_EXTS)}
        self.workers = max(1, workers if workers is not None else (os.cpu_count() or 1))
        self.encoder = "libx264"
        self.gpu_index = None
        self.extra_ffmpeg_args = list(extra_ffmpeg_args or [])
        self.dry_run = dry_run

    # ---------- planning ----------
    def _iter_videos(self, reporter: ProgressReporter | None = None) -> Iterable[Path]:
        it = (self.src_root.rglob("*")) if self.recurse else self.src_root.iterdir()
        for p in it:
            if p.is_file() and p.suffix.lower() in self.only_exts:
                if reporter:
                    reporter.update("scan", 1, text=p.name)
                yield p

    def enumerate_targets(
        self, reporter: ProgressReporter | None = None
    ) -> list[tuple[Path, Path]]:
        if reporter:
            reporter.start("scan", total=None, text="Discovering videos…")
        pairs: list[tuple[Path, Path]] = []
        for src in self._iter_videos(reporter=reporter):
            new_name = sanitize_filename(src.stem) + ".mp4"
            dst = mirrored_output_path(src, self.src_root, self.dst_root, new_name)
            pairs.append((src, dst))
        if reporter:
            reporter.end("scan")
        return pairs

    def plan(self, reporter: ProgressReporter | None = None) -> list[tuple[Path, Path]]:
        return self.enumerate_targets(reporter=reporter)

    # ---------- single conversion ----------
    def _ffmpeg_path(self) -> str:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise FileNotFoundError("ffmpeg executable not found on PATH")
        return exe

    def _to_mp4(self, src: Path, dst: Path) -> tuple[bool, str | None]:
        if dst.exists() and not self.overwrite:
            return False, "exists"
        if self.dry_run:
            return True, "dry_run"

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            ffmpeg = self._ffmpeg_path()

            base = [
                ffmpeg,
                "-y" if self.overwrite else "-n",
                "-i",
                str(src),
                "-map_metadata",
                "0",
            ]

            # CPU-only path (forced): libx264
            v_args = [
                "-c:v",
                "libx264",
                "-crf",
                str(self.crf),
                "-preset",
                self.preset,
                "-pix_fmt",
                "yuv420p",
            ]

            a_args = ["-c:a", "aac", "-b:a", self.audio_bitrate]
            tail = ["-movflags", "+faststart"]

            cmd = (
                base
                + v_args
                + a_args
                + tail
                + list(self.extra_ffmpeg_args)
                + [str(dst)]
            )
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                return False, f"error:ffmpeg:{proc.returncode}"
            return True, None
        except FileNotFoundError:
            return False, "ffmpeg_not_found"
        except Exception as exc:
            return False, f"error:{exc.__class__.__name__}"

    # ---------- parallel apply ----------
    def iter_apply(
        self,
        targets: Sequence[tuple[Path, Path]] | None = None,
        on_progress: Callable[[int], None] | None = None,
        workers: int | None = None,
    ) -> Iterator[tuple[Path, Path, bool, str | None]]:
        targets = targets or self.enumerate_targets()

        def _one(src: Path, dst: Path) -> tuple[Path, Path, bool, str | None]:
            ok, reason = self._to_mp4(src, dst)
            return src, dst, ok, reason

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, s, d): (s, d) for (s, d) in targets}
            for fut in as_completed(futs):
                src, dst, ok, reason = fut.result()
                if on_progress:
                    on_progress(1)
                yield src, dst, ok, reason

    def apply(
        self,
        reporter: ProgressReporter | None = None,
        workers: int | None = None,  # NEW
    ) -> list[tuple[Path, Path, bool, str | None]]:
        targets = self.enumerate_targets(reporter=reporter)
        total = len(targets)
        if reporter:
            reporter.start("convert", total=total, text="Converting to MP4…")
        results: list[tuple[Path, Path, bool, str | None]] = []
        for src, dst, ok, reason in self.iter_apply(
            targets=targets,
            on_progress=(lambda n: reporter.update("convert", n) if reporter else None),
            workers=workers,  # NEW
        ):
            results.append((src, dst, ok, reason))
        if reporter:
            reporter.end("convert")
        return results
