# src\vi_app\commands\convert_videos.py
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vi_app.commands.common import resolve_dry_run
from vi_app.core.rich_progress import make_phase_progress
from vi_app.modules.convert.service import Mp4ConvertService


class _Mp4Runner:
    def __init__(
        self,
        src_root: Path,
        dst_root: Path | None,
        recurse: bool,
        overwrite: bool,
        crf: int,
        preset: str,
        audio_bitrate: str,
        dry_run: bool,
    ) -> None:
        self.src_root = src_root
        self.dst_root = dst_root
        self.recurse = recurse
        self.overwrite = overwrite
        self.crf = crf
        self.preset = preset
        self.audio_bitrate = audio_bitrate
        self.dry_run = dry_run
        self.console = Console()

    def _build_service(self, dry_run: bool) -> Mp4ConvertService:
        return Mp4ConvertService(
            src_root=self.src_root,
            dst_root=self.dst_root,
            recurse=self.recurse,
            overwrite=self.overwrite,
            crf=self.crf,
            preset=self.preset,
            audio_bitrate=self.audio_bitrate,
            dry_run=dry_run,
        )

    def run(self) -> None:
        if self.dry_run:
            # PLAN path: show plan and offer to apply
            svc = self._build_service(dry_run=True)
            progress, reporter = make_phase_progress(self.console)
            with progress:
                pairs = svc.plan(reporter=reporter)
            total = len(pairs)
            if total == 0:
                typer.echo("No convertible videos found.")
                return

            for src, dst in pairs:
                typer.echo(f"{src} -> {dst}")
            typer.echo(f"[PLAN] Would convert {total} file(s).")

            if not typer.confirm("Apply these conversions now?", default=False):
                return

            # fallthrough to apply
            svc_apply = self._build_service(dry_run=False)
            progress2, reporter2 = make_phase_progress(self.console)
            t0 = time.perf_counter()
            with progress2:
                results = svc_apply.apply(reporter=reporter2)
            total = len(results)  # compute from actual apply
        else:
            # APPLY path: no plan printed, go straight to apply
            svc_apply = self._build_service(dry_run=False)
            progress2, reporter2 = make_phase_progress(self.console)
            t0 = time.perf_counter()
            with progress2:
                results = svc_apply.apply(reporter=reporter2)
            total = len(results)

        converted = sum(1 for _s, _d, ok, _r in results if ok)
        skipped = total - converted
        elapsed = time.perf_counter() - t0
        rate = total / elapsed if elapsed > 0 else 0.0

        skipped_rows = [(s, r) for s, _d, ok, r in results if not ok]
        if skipped_rows:
            table = Table(title="Skipped files", show_lines=False)
            table.add_column("Source", overflow="fold")
            table.add_column("Reason", overflow="fold")
            for s, reason in skipped_rows:
                table.add_row(str(s), reason or "")
            self.console.print(table)

        self.console.print(
            f"Converted {converted} file(s), skipped {skipped} out of {total} in {elapsed:.2f}s (~{rate:.1f} files/s).",
            style="bold green",
        )


def register(app: typer.Typer) -> None:
    """Attach video conversion commands to the given Typer app."""

    @app.command(
        "folder-to-mp4",
        help="Convert supported videos under a folder to MP4 (H.264 + AAC).",
    )
    def convert_folder_to_mp4_cmd(
        src_root: Path | None = typer.Argument(
            None, exists=False, file_okay=False, dir_okay=True
        ),
        dst_root: Path | None = typer.Option(
            None, "--dst-root", "-d", help="Destination root (mirror if omitted)."
        ),
        recurse: bool | None = typer.Option(
            None, "--recurse/--no-recurse", help="Scan subfolders recursively."
        ),
        overwrite: bool | None = typer.Option(
            None, "--overwrite/--no-overwrite", help="Overwrite destination if exists."
        ),
        crf: int | None = typer.Option(
            None,
            "--crf",
            min=0,
            max=51,
            help="H.264 CRF (lower = higher quality, 18–23 typical).",
        ),
        preset: str | None = typer.Option(
            None, "--preset", help="x264 preset: ultrafast…veryslow."
        ),
        audio_bitrate: str | None = typer.Option(
            None, "--audio-bitrate", "-ab", help="Audio bitrate like '192k'."
        ),
        apply: bool = typer.Option(False, "--apply", help="Perform writes."),
        plan: bool = typer.Option(False, "--plan", help="Plan only (default)."),
    ):
        # Prompts
        if src_root is None:
            src_root = Path(typer.prompt("src (folder to scan)")).expanduser()
        if not src_root.exists() or not src_root.is_dir():
            raise typer.BadParameter(
                f"src_root does not exist or is not a directory: {src_root}"
            )

        if dst_root is None:
            dst_str = typer.prompt(
                "dst (destination root; press Enter to use default '<src>/converted')",
                default="",
            )
            dst_root = Path(dst_str).expanduser() if dst_str else None

        if recurse is None:
            recurse = typer.confirm("recurse into subfolders?", default=True)
        if overwrite is None:
            overwrite = typer.confirm(
                "overwrite destination files if they already exist?", default=False
            )

        # CRF: default to lossless (0)
        if crf is None:
            crf = typer.prompt(
                "CRF (0–51, lower = higher quality; 0 = lossless)", default=0, type=int
            )
            if not (0 <= crf <= 51):
                raise typer.BadParameter("crf must be between 0 and 51")

        # Preset: show all options, default ultrafast
        valid = {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }
        if preset is None:
            preset = (
                typer.prompt(
                    f"x264 preset ({', '.join(sorted(valid))})",
                    default="ultrafast",
                )
                .strip()
                .lower()
            )
        if preset not in valid:
            raise typer.BadParameter(
                f"preset must be one of: {', '.join(sorted(valid))}"
            )

        # Audio bitrate: show options, default to highest
        bitrate_opts = ["96k", "128k", "160k", "192k", "256k", "320k"]
        if audio_bitrate is None:
            audio_bitrate = (
                typer.prompt(
                    f"audio bitrate ({', '.join(bitrate_opts)})",
                    default="320k",
                )
                .strip()
                .lower()
            )
        if audio_bitrate not in set(bitrate_opts):
            raise typer.BadParameter(
                f"audio_bitrate must be one of: {', '.join(bitrate_opts)}"
            )

        if not apply and not plan:
            mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
            if mode not in {"plan", "apply"}:
                raise typer.BadParameter("option must be 'plan' or 'apply'")
            plan, apply = (mode == "plan"), (mode == "apply")

        dry_run = resolve_dry_run(apply, plan)
        _Mp4Runner(
            src_root=src_root,
            dst_root=dst_root,
            recurse=recurse,
            overwrite=overwrite,
            crf=crf,
            preset=preset,
            audio_bitrate=audio_bitrate,
            dry_run=dry_run,
        ).run()

    def _create_synthetic_clips(
        dst_dir: Path,
        count: int,
        seconds: int,
        res: str,
        fps: int,
        *,
        target_mb: int | None = None,
        v_bitrate: str | None = None,
        a_bitrate: str = "192k",
        v_codec: str = "libx264",
        preset: str = "ultrafast",
    ) -> None:
        """
        Generate 'count' MP4 clips using ffmpeg test sources.

        Size control:
        - If v_bitrate is provided (e.g. "8000k"), we use that directly.
        - Else if target_mb is provided, we compute an approximate video bitrate:
                size_bits ≈ (target_mb * 8 * 1024 * 1024)
                video_bitrate_bps ≈ max( (size_bits - audio_bitrate_bps * seconds) / seconds, 500_000 )
        - Else we fall back to a transparent-ish quality (CRF 18).

        Requires ffmpeg on PATH.
        """

        def _parse_kbps(s: str) -> int:
            # "192k" -> 192000, "320k" -> 320000
            m = re.fullmatch(r"(\d+)\s*[kK]", s.strip())
            if not m:
                raise ValueError(
                    f"Invalid bitrate string: {s!r} (expected like '192k')"
                )
            return int(m.group(1)) * 1000

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH; required for --autogen")

        dst_dir.mkdir(parents=True, exist_ok=True)
        a_bps = _parse_kbps(a_bitrate)

        for i in range(1, count + 1):
            vf = "testsrc2" if i % 2 == 1 else "smptebars"
            out = dst_dir / f"sample_{i:03d}.mp4"

            base = [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"{vf}=size={res}:rate={fps}",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:sample_rate=48000",
                "-t",
                str(seconds),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                a_bitrate,
                "-movflags",
                "+faststart",
            ]

            # Decide video quality/bitrate
            v_args: list[str]
            if v_bitrate:
                # explicit bitrate
                v_args = [
                    "-c:v",
                    v_codec,
                    "-b:v",
                    v_bitrate,
                    "-maxrate",
                    v_bitrate,
                    "-bufsize",
                    "2M",
                    "-preset",
                    preset,
                ]
            elif target_mb:
                # compute approximate bitrate to hit target size
                size_bits = target_mb * 8 * 1024 * 1024
                video_bits = max(size_bits - (a_bps * seconds), 500_000 * seconds)
                v_bps = int(video_bits // max(seconds, 1))
                v_k = max(v_bps // 1000, 500)  # floor to kbps; min 500k
                v_args = [
                    "-c:v",
                    v_codec,
                    "-b:v",
                    f"{v_k}k",
                    "-maxrate",
                    f"{v_k}k",
                    "-bufsize",
                    f"{2 * v_k}k",
                    "-preset",
                    preset,
                ]
            else:
                # CRF-based fallback (smaller files)
                v_args = ["-c:v", v_codec, "-crf", "18", "-preset", preset]

            cmd = base + v_args + [str(out)]
            subprocess.run(cmd, capture_output=True, check=False)

    @app.command(
        "benchmark-mp4",
        help="Benchmark CPU/GPU worker combinations to choose optimal settings.",
    )
    def benchmark_mp4_cmd(
        src_root: Path | None = typer.Argument(
            None, exists=False, file_okay=False, dir_okay=True
        ),
        dst_root: Path | None = typer.Option(
            None,
            "--dst-root",
            "-d",
            help="Temporary benchmark output root (default: <src>/converted/__bench__)",
        ),
        recurse: bool = typer.Option(
            True, "--recurse/--no-recurse", help="Scan subfolders recursively."
        ),
        sample_seconds: int = typer.Option(
            3,
            "--seconds",
            "-t",
            min=1,
            max=30,
            help="Transcode only this many seconds per sample video.",
        ),
        sample_size: int | None = typer.Option(
            None,
            "--samples",
            "-n",
            min=2,
            max=4096,
            help="Number of sample videos to benchmark. Default: all autogen clips (or min(total, 4×CPU threads) for real sources).",
        ),
        cpu_workers_list: list[int] | None = typer.Option(
            None, "--cpu", help="CPU worker counts to test. Default: 1..os.cpu_count()"
        ),
        gpu_workers_list: list[int] | None = typer.Option(
            None,
            "--gpu",
            help="GPU worker counts to test (0 means off). Default: 0..min(4, os.cpu_count())",
        ),
        gpu_index: int | None = typer.Option(
            None, "--gpu-index", help="NVENC GPU index (if you have multiple GPUs)."
        ),
        overwrite: bool = typer.Option(
            True, "--overwrite/--no-overwrite", help="Overwrite temp benchmark outputs."
        ),
        autogen: bool | None = typer.Option(
            None,
            "--autogen/--no-autogen",
            help="Use synthetic test clips (prompted; default Yes).",
        ),
        autogen_count: int | None = typer.Option(
            None,
            "--autogen-count",
            "-ac",
            min=2,
            max=4096,
            help="Number of synthetic clips to generate (default: 4×CPU threads).",
        ),
        autogen_seconds: int = typer.Option(
            10,
            "--autogen-seconds",
            "-as",
            min=1,
            max=120,
            help="Length of each synthetic clip in seconds.",
        ),
        autogen_res: str = typer.Option(
            "3840x2160",
            "--autogen-res",
            help="Resolution for synthetic clips (e.g. 1920x1080, 3840x2160).",
        ),
        autogen_fps: int = typer.Option(
            60, "--autogen-fps", min=1, max=120, help="Frame rate for synthetic clips."
        ),
        autogen_target_mb: int | None = typer.Option(
            50,
            "--autogen-target-mb",
            help="Approximate size per synthetic clip in MB (overrides CRF).",
        ),
        autogen_video_bitrate: str | None = typer.Option(
            None,
            "--autogen-video-bitrate",
            "-vb",
            help="Explicit video bitrate like '16000k' (overrides target MB).",
        ),
        autogen_audio_bitrate: str = typer.Option(
            "192k",
            "--autogen-audio-bitrate",
            "-ab",
            help="Audio bitrate for synthetic clips.",
        ),
        autogen_codec: str = typer.Option(
            "libx264",
            "--autogen-codec",
            help="Video codec for synthetic clips (e.g., libx264, libx265).",
        ),
    ):
        # Ask whether to autogen if not provided explicitly
        if autogen is None:
            autogen = typer.confirm("Use auto-generated test clips?", default=True)

        # Determine CPU thread count
        cpu_threads = max(1, os.cpu_count() or 1)

        if autogen:
            # Default autogen count = 4 × CPU threads when not provided
            if autogen_count is None:
                autogen_count = 4 * cpu_threads

            import tempfile

            tmp_src = Path(tempfile.mkdtemp(prefix="bench_src_"))
            _create_synthetic_clips(
                tmp_src,
                count=autogen_count,
                seconds=autogen_seconds,
                res=autogen_res,
                fps=autogen_fps,
                target_mb=autogen_target_mb,
                v_bitrate=autogen_video_bitrate,
                a_bitrate=autogen_audio_bitrate,
                v_codec=autogen_codec,
                preset="ultrafast",
            )
            src_root = tmp_src
            typer.echo(
                "[autogen] created "
                f"{autogen_count} clip(s), {autogen_seconds}s, {autogen_res}@{autogen_fps}fps "
                f"in: {src_root}"
            )
        else:
            if src_root is None:
                src_root = Path(typer.prompt("src (folder to scan)")).expanduser()
            if not src_root.exists() or not src_root.is_dir():
                raise typer.BadParameter(
                    f"src_root does not exist or is not a directory: {src_root}"
                )

        # Discover available pairs (plan)
        discover = Mp4ConvertService(
            src_root=src_root,
            dst_root=dst_root or (src_root / "converted" / "__bench__"),
            recurse=recurse,
            overwrite=True,
            encoder="libx264",
            extra_ffmpeg_args=[],
            dry_run=True,
        )
        all_pairs = discover.plan()
        if not all_pairs:
            typer.echo("No videos found under source.")
            return

        # Decide sample_size:
        # - For autogen: default to 'autogen_count' (use them all).
        # - For real source: default to min(total, 4 × CPU threads).
        if sample_size is None:
            if autogen:
                sample_size = autogen_count
            else:
                sample_size = min(len(all_pairs), 4 * cpu_threads)

        # Pick unique-stem samples up to 'sample_size'
        seen: set[str] = set()
        samples: list[tuple[Path, Path]] = []
        for s, d in all_pairs:
            key = s.stem.lower()
            if key in seen:
                continue
            seen.add(key)
            samples.append((s, d))
            if len(samples) >= sample_size:
                break
        if not samples:
            typer.echo("No suitable samples found.")
            return

        # helper to run a service over a fixed target list with given workers/encoder
        def _run_one(
            encoder: str, workers: int
        ) -> tuple[float, list[tuple[Path, Path, bool, str | None]]]:
            # use a fresh subdir per run to avoid contention
            run_dst = Path(
                tempfile.mkdtemp(prefix=f"bench_{encoder}_{workers}_", dir=dst_root)
            )
            try:
                svc = Mp4ConvertService(
                    src_root=src_root,
                    dst_root=run_dst,
                    recurse=False,  # we already have explicit sample list
                    overwrite=overwrite,
                    encoder=encoder,
                    gpu_index=gpu_index,
                    # use lossless defaults; constrain duration with extra args
                    crf=0,
                    preset="ultrafast" if encoder == "libx264" else "ultrafast",
                    audio_bitrate="320k",
                    extra_ffmpeg_args=["-t", str(sample_seconds)],
                    dry_run=False,
                )
                t0 = time.perf_counter()
                # apply only to our sample targets, with the requested workers
                # (bypass plan() to use our fixed list)
                results = list(
                    svc.iter_apply(
                        targets=[(s, run_dst / (s.stem + ".mp4")) for s, _ in samples],
                        on_progress=None,
                        workers=workers,
                    )
                )
                sec = time.perf_counter() - t0
                return sec, results
            finally:
                # clean up benchmark outputs
                try:
                    shutil.rmtree(run_dst, ignore_errors=True)
                    typer.echo(f"[autogen] cleaned up synthetic source: {src_root}")
                except Exception:
                    pass

        # mixed CPU+GPU run: split samples between both and run concurrently
        def _run_mixed(
            cpu_workers: int, gpu_workers: int
        ) -> tuple[float, list[tuple[Path, Path, bool, str | None]]]:
            run_dst = Path(
                tempfile.mkdtemp(
                    prefix=f"bench_mixed_{cpu_workers}_{gpu_workers}_", dir=dst_root
                )
            )
            try:
                cpu_targets: list[tuple[Path, Path]] = []
                gpu_targets: list[tuple[Path, Path]] = []
                # simple round-robin split
                for i, (s, _d) in enumerate(samples):
                    name = s.stem + ".mp4"
                    if i % 2 == 0:
                        cpu_targets.append((s, run_dst / name))
                    else:
                        gpu_targets.append((s, run_dst / name))

                cpu_svc = Mp4ConvertService(
                    src_root=src_root,
                    dst_root=run_dst,
                    recurse=False,
                    overwrite=overwrite,
                    encoder="libx264",
                    crf=0,
                    preset="ultrafast",
                    audio_bitrate="320k",
                    extra_ffmpeg_args=["-t", str(sample_seconds)],
                    dry_run=False,
                )
                gpu_svc = Mp4ConvertService(
                    src_root=src_root,
                    dst_root=run_dst,
                    recurse=False,
                    overwrite=overwrite,
                    encoder="h264_nvenc",
                    gpu_index=gpu_index,
                    crf=0,
                    preset="ultrafast",
                    audio_bitrate="320k",
                    extra_ffmpeg_args=["-t", str(sample_seconds)],
                    dry_run=False,
                )

                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=2) as ex:
                    fut_cpu = ex.submit(
                        list, cpu_svc.iter_apply(cpu_targets, workers=cpu_workers)
                    )
                    fut_gpu = ex.submit(
                        list, gpu_svc.iter_apply(gpu_targets, workers=gpu_workers)
                    )
                    results = fut_cpu.result() + fut_gpu.result()
                sec = time.perf_counter() - t0
                return sec, results
            finally:
                try:
                    shutil.rmtree(run_dst, ignore_errors=True)
                    typer.echo(f"[autogen] cleaned up synthetic source: {src_root}")
                except Exception:
                    pass

        # try combinations and record results
        console = Console()
        # Derive CPU list from machine threads if not provided
        cpu_threads = max(1, os.cpu_count() or 1)
        if not cpu_workers_list:
            cpu_workers_list = list(range(1, cpu_threads + 1))  # 1..N
        else:
            # sanitize to 1..N, unique and sorted
            cpu_workers_list = sorted(
                {c for c in cpu_workers_list if 1 <= int(c) <= cpu_threads}
            )

        # Derive GPU list (0 = off). We don’t attempt to auto-detect GPU count here;
        # test a reasonable range up to 4, capped by cpu_threads (prevents crazy grids).
        if not gpu_workers_list:
            gpu_workers_list = list(range(0, min(4, cpu_threads) + 1))  # 0..min(4, N)
        else:
            gpu_workers_list = sorted({g for g in gpu_workers_list if int(g) >= 0})

        # Build the full grid of (cpu_workers, gpu_workers), excluding (0,0)
        combos: list[tuple[int, int]] = [
            (c, g)
            for c in cpu_workers_list
            for g in gpu_workers_list
            if not (c == 0 and g == 0)
        ]

        console = Console()
        console.print(
            f"[bold]Benchmark grid[/bold]: CPU workers {cpu_workers_list} × GPU workers {gpu_workers_list} "
            f"(cpu_threads={cpu_threads})"
        )

        rows: list[
            tuple[str, int, int, int, float, float]
        ] = []  # (mode, cpu, gpu, ok, sec, fps)
        for cpu_w, gpu_w in combos:
            mode = "mixed" if (cpu_w and gpu_w) else ("cpu" if cpu_w else "gpu")
            try:
                if mode == "cpu":
                    sec, res = _run_one("libx264", cpu_w)
                elif mode == "gpu":
                    sec, res = _run_one("h264_nvenc", gpu_w)
                else:
                    sec, res = _run_mixed(cpu_w, gpu_w)
                ok = sum(1 for _s, _d, o, _r in res if o)
                fps = ok / sec if sec > 0 else 0.0
                rows.append((mode, cpu_w, gpu_w, ok, sec, fps))
                console.print(
                    f"[bold]bench[/bold] mode={mode} cpu={cpu_w} gpu={gpu_w} -> {ok} files in {sec:.2f}s ({fps:.2f} files/s)"
                )
            except Exception as e:
                console.print(
                    f"[yellow]bench failed[/yellow] mode={mode} cpu={cpu_w} gpu={gpu_w}: {e}"
                )
                rows.append((mode, cpu_w, gpu_w, 0, float("inf"), 0.0))

        # summarize & recommend
        rows.sort(key=lambda r: (-r[5], r[4]))  # sort by fps desc, then seconds asc
        table = Table(title="MP4 Benchmark Results", show_lines=False)
        table.add_column("Rank", justify="right")
        table.add_column("Mode")
        table.add_column("CPU W")
        table.add_column("GPU W")
        table.add_column("OK", justify="right")
        table.add_column("Seconds", justify="right")
        table.add_column("Files/s", justify="right")
        for i, (mode, cpu_w, gpu_w, ok, sec, fps) in enumerate(rows[:20], start=1):
            table.add_row(
                str(i),
                mode,
                str(cpu_w),
                str(gpu_w),
                str(ok),
                f"{sec:.2f}",
                f"{fps:.2f}",
            )
        console.print(table)

        if rows:
            best = rows[0]
            bmode, bcpu, bgpu, bok, bsec, bfps = best
            tip = (
                f"--encoder libx264 --workers {bcpu}"
                if bmode == "cpu"
                else f"--encoder h264_nvenc --workers {bgpu}"
                if bmode == "gpu"
                else f"(mixed) try CPU workers={bcpu}, GPU workers={bgpu}"
            )
            console.print(
                f"[bold green]Recommended[/bold green]: mode={bmode} cpu={bcpu} gpu={bgpu} ~ {bfps:.2f} files/s\n"
                f"Hint for single-mode runs: {tip}"
            )
