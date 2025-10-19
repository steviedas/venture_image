# tools/bench_convert_mp4.py
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# ========== USER SETTINGS ==========
SOURCE_DIR = Path(r"C:\Users\stevi\Desktop\iCloud Photos Part 2 of 2\video_test")

# Limit how many files to benchmark (None = all)
SAMPLE_COUNT: int | None = 100

# Video extensions to consider
VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".mkv",
    ".avi",
    ".wmv",
    ".3gp",
    ".webm",
    ".mts",
    ".m2ts",
    ".ts",
}

# We only test CRF = 0 per your request (lossless)
CRF = 0

# Preset: use the fastest, since we’re chasing elapsed time
PRESET = "ultrafast"

# NVENC concurrency sweep (capped by your GPU/IO reality)
NVENC_WORKERS_LIST = [2, 4, 8]

# Try CPU-only variants as well?
CPU_ONLY_VARIANTS = True

# CPU x264 threads per job (None = ffmpeg/x264 decides; 1 often reduces thrash)
CPU_X264_THREADS_PER_JOB_VARIANTS = [None, 1]

# Audio modes:
#   "aac_320k"          -> always re-encode to AAC 320k
#   "copy_if_possible"  -> copy if (aac|mp3|alac), else re-encode to AAC 320k
AUDIO_MODES = ["aac_320k", "copy_if_possible"]

# Try CUDA decode on NVENC paths? (helps if sources are H.264/H.265 and NVDEC supports them)
CUDA_DECODE_VARIANTS = [False, True]

# ===================================


def which(bin_name: str) -> str | None:
    return which(bin_name)


def ffmpeg_has_nvenc(ffmpeg_bin: str = "ffmpeg") -> bool:
    try:
        out = subprocess.check_output(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return "h264_nvenc" in out
    except Exception:
        return False


def list_nv_gpus() -> list[tuple[int, str]]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        res: list[tuple[int, str]] = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",", 1)]
            if len(parts) == 2 and parts[0].isdigit():
                res.append((int(parts[0]), parts[1]))
        return res
    except Exception:
        return []


def ffprobe_stream_info(
    ffprobe_bin: str, src: Path
) -> tuple[dict | None, dict | None, int | None]:
    """
    Return (video_stream_dict, audio_stream_dict, duration_ms).
    We collect codec_name/pix_fmt for video; codec_name for audio.
    """
    try:
        out = subprocess.check_output(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_name,codec_type,pix_fmt,profile,width,height",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(src),
            ],
            stderr=subprocess.STDOUT,
            text=True,
        )
        js = json.loads(out)
        v = None
        a = None
        for st in js.get("streams", []):
            if st.get("codec_type") == "video" and v is None:
                v = st
            elif st.get("codec_type") == "audio" and a is None:
                a = st
        dur = js.get("format", {}).get("duration")
        dur_ms = int(float(dur) * 1000) if dur else None
        return v, a, dur_ms
    except Exception:
        return None, None, None


def should_route_cpu(codec: str | None, pix_fmt: str | None) -> bool:
    """Skip GPU for codecs/pixel formats that frequently choke on NVENC or are intra/intermediate."""
    codec = (codec or "").lower()
    pix_fmt = (pix_fmt or "").lower()
    cpu_codecs = {
        "prores",
        "prores_aw",
        "prores_ks",
        "dnxhd",
        "dnxhr",
        "jpeg2000",
        "j2k",
        "qtrle",
        "png",
        "ffv1",
        "huffyuv",
    }
    if codec in cpu_codecs:
        return True
    if any(s in pix_fmt for s in ("yuv422", "yuv444", "yuvj444")):
        return True
    if any(s in pix_fmt for s in ("p10", "p12", "10le", "12le")):
        return True
    return False


def nvenc_args(preset: str, crf: int, gpu_index: int | None) -> list[str]:
    # CRF=0 -> lossless via -qp 0 (safer across NVENC gens)
    nvenc_preset = {
        "ultrafast": "p1",
        "superfast": "p2",
        "veryfast": "p3",
        "faster": "p4",
        "fast": "p5",
        "medium": "p6",
        "slow": "p7",
        "slower": "p7",
        "veryslow": "p7",
        "placebo": "p7",
    }.get(preset, "p6")
    args = ["-c:v", "h264_nvenc", "-preset", nvenc_preset]
    if crf == 0:
        args += ["-qp", "0"]
    else:
        args += ["-b:v", "0", "-cq", str(crf)]
    args += ["-pix_fmt", "yuv420p"]
    if gpu_index is not None:
        args += ["-gpu", str(gpu_index)]
    # Optional “faster” knobs (try enabling if you want):  # args += ["-rc-lookahead", "0", "-spatial_aq", "0", "-temporal_aq", "0"]
    return args


def x264_args(preset: str, crf: int, threads_per_job: int | None) -> list[str]:
    args = [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
    ]
    if threads_per_job is not None:
        args += ["-threads", str(threads_per_job)]
    return args


def choose_audio_args(audio_mode: str, acodec: str | None, bitrate: str) -> list[str]:
    acodec = (acodec or "").lower()
    if audio_mode == "copy_if_possible" and acodec in {"aac", "mp3", "alac"}:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", bitrate]


@dataclass
class Job:
    src: Path
    dst: Path
    duration_ms: int | None
    vcodec: str | None
    vpix: str | None
    acodec: str | None


@dataclass
class Scenario:
    name: str  # e.g. staged_nv8_cudaCopy_threads1
    strategy: str  # 'staged' | 'dual' | 'cpu_only'
    preset: str  # ultrafast
    crf: int  # 0
    nvenc_workers: int | None
    cpu_workers: int
    backend: str  # 'nvenc' or 'cpu'
    gpu_index: int | None
    audio_mode: str  # 'aac_320k' | 'copy_if_possible'
    cuda_decode: bool  # True/False
    x264_threads_per_job: int | None  # None or 1


@dataclass
class Result:
    scenario: Scenario
    elapsed: float
    total: int
    converted: int
    skipped: int
    gpu_fallbacks: int
    failures: list[tuple[Path, str]]


def gather_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            files.append(p)
    return files


def run_ffmpeg(cmd: list[str]) -> tuple[int, str]:
    """Run ffmpeg and try to extract a short error reason from stderr."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    code = proc.wait()
    reason = ""
    try:
        if proc.stderr:
            err = proc.stderr.read()
            for line in err.splitlines():
                low = line.lower()
                if (
                    "nvenc" in low
                    or "error" in low
                    or "failed" in low
                    or "capable devices" in low
                ):
                    reason = line.strip()
                    break
    except Exception:
        pass
    return code, reason or f"exit_{code}"


def encode_one(
    job: Job, backend: str, scen: Scenario, overwrite: bool
) -> tuple[bool, str | None]:
    dst = job.dst
    # Ensure clean destination
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and overwrite:
        try:
            dst.unlink()
        except Exception:
            pass

    flags = ["-y"] if overwrite else ["-n"]
    pre_input: list[str] = []
    if backend == "nvenc" and scen.cuda_decode:
        pre_input = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        if scen.gpu_index is not None:
            pre_input += ["-hwaccel_device", str(scen.gpu_index)]

    v_args = (
        nvenc_args(scen.preset, scen.crf, scen.gpu_index)
        if backend == "nvenc"
        else x264_args(scen.preset, scen.crf, scen.x264_threads_per_job)
    )
    a_args = choose_audio_args(scen.audio_mode, job.acodec, "320k")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        *flags,
        *pre_input,
        "-i",
        str(job.src),
        "-map_metadata",
        "0",
        *v_args,
        *a_args,
        "-movflags",
        "+faststart",
        "-v",
        "error",
        str(dst),
    ]
    code, reason = run_ffmpeg(cmd)
    if code == 0:
        try:
            if dst.stat().st_size == 0:
                return False, "empty_output"
        except Exception:
            return False, "empty_output"
        return True, None
    return False, f"ffmpeg:{reason}"


def encode_one_gpu_with_fallback(
    job: Job, scen: Scenario
) -> tuple[bool, str | None, bool]:
    """Try NVENC, fall back to CPU if it fails. Returns (ok, reason, used_cpu_fallback)."""
    ok, reason = encode_one(job, "nvenc", scen, overwrite=True)
    if ok:
        return True, None, False
    # Fallback: delete partial and force overwrite
    try:
        if job.dst.exists():
            job.dst.unlink()
    except Exception:
        pass
    scen_cpu = Scenario(
        name=scen.name,
        strategy=scen.strategy,
        preset=scen.preset,
        crf=scen.crf,
        nvenc_workers=None,
        cpu_workers=scen.cpu_workers,
        backend="cpu",
        gpu_index=None,
        audio_mode=scen.audio_mode,
        cuda_decode=False,
        x264_threads_per_job=scen.x264_threads_per_job,
    )
    ok2, reason2 = encode_one(job, "cpu", scen_cpu, overwrite=True)
    if ok2:
        return True, f"gpu_failed_fallback_cpu: {reason or 'unknown'}", True
    return False, (reason2 or reason or "unknown"), True


def staged_run(jobs_gpu: list[Job], jobs_cpu: list[Job], scen: Scenario) -> Result:
    t0 = time.perf_counter()
    converted = 0
    skipped = 0
    gpu_fallbacks = 0
    failures: list[tuple[Path, str]] = []

    # Stage 1: GPU queue
    if (
        scen.backend == "nvenc"
        and jobs_gpu
        and scen.nvenc_workers
        and scen.nvenc_workers > 0
    ):
        with cf.ThreadPoolExecutor(max_workers=scen.nvenc_workers) as ex:
            futs = {
                ex.submit(encode_one_gpu_with_fallback, j, scen): j for j in jobs_gpu
            }
            for fut, j in futs.items():
                try:
                    ok, reason, used_cpu = fut.result()
                except Exception as e:
                    ok, reason, used_cpu = False, f"error:{e.__class__.__name__}", False
                if ok:
                    converted += 1
                    if used_cpu and reason:
                        gpu_fallbacks += 1
                        failures.append((j.src, reason))
                else:
                    skipped += 1
                    failures.append((j.src, reason or "unknown"))

    # Stage 2: CPU queue
    if jobs_cpu:
        with cf.ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 4)) as ex:
            futs = {ex.submit(encode_one, j, "cpu", scen, True): j for j in jobs_cpu}
            for fut, j in futs.items():
                try:
                    ok, reason = fut.result()
                except Exception as e:
                    ok, reason = False, f"error:{e.__class__.__name__}"
                if ok:
                    converted += 1
                else:
                    skipped += 1
                    failures.append((j.src, reason or "unknown"))

    elapsed = time.perf_counter() - t0
    return Result(
        scenario=scen,
        elapsed=elapsed,
        total=len(jobs_gpu) + len(jobs_cpu),
        converted=converted,
        skipped=skipped,
        gpu_fallbacks=gpu_fallbacks,
        failures=failures,
    )


def dual_run(jobs_gpu: list[Job], jobs_cpu: list[Job], scen: Scenario) -> Result:
    t0 = time.perf_counter()
    converted = 0
    skipped = 0
    gpu_fallbacks = 0
    failures: list[tuple[Path, str]] = []

    ex_gpu = (
        cf.ThreadPoolExecutor(max_workers=scen.nvenc_workers)
        if (scen.backend == "nvenc" and scen.nvenc_workers and jobs_gpu)
        else None
    )
    ex_cpu = (
        cf.ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 4))
        if jobs_cpu
        else None
    )
    futs: dict[cf.Future, Job] = {}

    try:
        if ex_gpu:
            for j in jobs_gpu:
                futs[ex_gpu.submit(encode_one_gpu_with_fallback, j, scen)] = j
        if ex_cpu:
            for j in jobs_cpu:
                futs[ex_cpu.submit(encode_one, j, "cpu", scen, True)] = j

        for fut, j in list(futs.items()):
            try:
                res = fut.result()
            except Exception as e:
                res = (False, f"error:{e.__class__.__name__}")
            if len(res) == 3:
                ok, reason, used_cpu = res  # gpu routine
                if ok:
                    converted += 1
                    if used_cpu and reason:
                        gpu_fallbacks += 1
                        failures.append((j.src, reason))
                else:
                    skipped += 1
                    failures.append((j.src, reason or "unknown"))
            else:
                ok, reason = res  # cpu routine
                if ok:
                    converted += 1
                else:
                    skipped += 1
                    failures.append((j.src, reason or "unknown"))
    finally:
        if ex_gpu:
            ex_gpu.shutdown(wait=True, cancel_futures=True)
        if ex_cpu:
            ex_cpu.shutdown(wait=True, cancel_futures=True)

    elapsed = time.perf_counter() - t0
    return Result(
        scenario=scen,
        elapsed=elapsed,
        total=len(jobs_gpu) + len(jobs_cpu),
        converted=converted,
        skipped=skipped,
        gpu_fallbacks=gpu_fallbacks,
        failures=failures,
    )


def main() -> None:
    if which("ffmpeg") is None:
        print(
            "ffmpeg_not_found — install FFmpeg and ensure it’s on PATH.",
            file=sys.stderr,
        )
        sys.exit(1)
    ffprobe_bin = which("ffprobe") or "ffprobe"

    files = list(gather_files(SOURCE_DIR))
    if not files:
        print("No video files found.")
        return

    if SAMPLE_COUNT is not None and len(files) > SAMPLE_COUNT:
        random.seed(42)
        files = random.sample(files, SAMPLE_COUNT)

    # Probe once
    infos: dict[Path, tuple[dict | None, dict | None, int | None]] = {}
    print(f"Probing {len(files)} file(s)…")
    for p in files:
        infos[p] = ffprobe_stream_info(ffprobe_bin, p)

    # Prepare Job objects
    out_root = SOURCE_DIR / ".vi_bench_out"
    out_root.mkdir(exist_ok=True)
    base_jobs: list[Job] = []
    for p in files:
        v, a, dur = infos[p]
        base_jobs.append(
            Job(
                src=p,
                dst=Path("DUMMY"),  # filled per scenario
                duration_ms=dur,
                vcodec=(v.get("codec_name") if v else None),
                vpix=(v.get("pix_fmt") if v else None),
                acodec=(a.get("codec_name") if a else None),
            )
        )

    has_nvenc = ffmpeg_has_nvenc()
    gpus = list_nv_gpus() if has_nvenc else []
    gpu_index = (gpus[0][0] if gpus else 0) if has_nvenc else None

    scenarios: list[Scenario] = []

    # NVENC scenarios: staged & dual; workers sweep; audio modes; cuda decode Y/N
    if has_nvenc:
        for nvw in NVENC_WORKERS_LIST:
            for audio_mode in AUDIO_MODES:
                for cuda_dec in CUDA_DECODE_VARIANTS:
                    scenarios.append(
                        Scenario(
                            name=f"staged_nv{nvw}_{audio_mode}{'_cuda' if cuda_dec else ''}",
                            strategy="staged",
                            preset=PRESET,
                            crf=CRF,
                            nvenc_workers=min(nvw, 8),
                            cpu_workers=max(1, os.cpu_count() or 4),
                            backend="nvenc",
                            gpu_index=gpu_index,
                            audio_mode=audio_mode,
                            cuda_decode=cuda_dec,
                            x264_threads_per_job=None,  # CPU fallback may still use default threads
                        )
                    )
                    scenarios.append(
                        Scenario(
                            name=f"dual_nv{nvw}_{audio_mode}{'_cuda' if cuda_dec else ''}",
                            strategy="dual",
                            preset=PRESET,
                            crf=CRF,
                            nvenc_workers=min(nvw, 8),
                            cpu_workers=max(1, os.cpu_count() or 4),
                            backend="nvenc",
                            gpu_index=gpu_index,
                            audio_mode=audio_mode,
                            cuda_decode=cuda_dec,
                            x264_threads_per_job=None,
                        )
                    )

    # CPU-only variants: try threads-per-job = None and 1, with both audio modes
    if CPU_ONLY_VARIANTS:
        for th in CPU_X264_THREADS_PER_JOB_VARIANTS:
            for audio_mode in AUDIO_MODES:
                scenarios.append(
                    Scenario(
                        name=f"cpu_only_threads{th if th is not None else 'auto'}_{audio_mode}",
                        strategy="cpu_only",
                        preset=PRESET,
                        crf=CRF,
                        nvenc_workers=None,
                        cpu_workers=max(1, os.cpu_count() or 4),
                        backend="cpu",
                        gpu_index=None,
                        audio_mode=audio_mode,
                        cuda_decode=False,
                        x264_threads_per_job=th,
                    )
                )

    results: list[Result] = []

    for scen in scenarios:
        scenario_dir = out_root / scen.name
        if scenario_dir.exists():
            shutil.rmtree(scenario_dir, ignore_errors=True)
        scenario_dir.mkdir(parents=True, exist_ok=True)

        # Build per-scenario job list with dst paths under scenario_dir
        scen_jobs: list[Job] = []
        for j in base_jobs:
            new_name = (
                j.src.name
                if j.src.suffix.lower() == ".mp4"
                else j.src.with_suffix(".mp4").name
            )
            scen_jobs.append(
                Job(
                    src=j.src,
                    dst=scenario_dir / new_name,
                    duration_ms=j.duration_ms,
                    vcodec=j.vcodec,
                    vpix=j.vpix,
                    acodec=j.acodec,
                )
            )

        # Classify routes
        gpu_jobs = []
        cpu_jobs = []
        if scen.backend == "nvenc":
            for j in scen_jobs:
                if should_route_cpu(j.vcodec, j.vpix):
                    cpu_jobs.append(j)
                else:
                    gpu_jobs.append(j)
        else:
            cpu_jobs = scen_jobs

        print(f"\n==> Running {scen.name}")
        print(
            f"   files: total={len(scen_jobs)}  gpu_queue={len(gpu_jobs)}  cpu_queue={len(cpu_jobs)}"
        )
        t_start = time.perf_counter()

        if scen.strategy == "staged":
            res = staged_run(gpu_jobs, cpu_jobs, scen)
        elif scen.strategy == "dual":
            res = dual_run(gpu_jobs, cpu_jobs, scen)
        else:
            # cpu_only strategy reuses dual/staged CPU runner equivalently
            res = dual_run([], cpu_jobs, scen)

        t_end = time.perf_counter()
        res.elapsed = t_end - t_start
        results.append(res)

        rate = (res.converted / res.elapsed) if res.elapsed > 0 else 0.0
        print(
            f"   elapsed={res.elapsed:.2f}s  converted={res.converted}  skipped={res.skipped}  gpu_fallbacks={res.gpu_fallbacks}  rate≈{rate:.2f} files/s"
        )

        # Comment this if you want to inspect outputs
        # shutil.rmtree(scenario_dir, ignore_errors=True)

    # Summary
    print("\n================ SUMMARY ================ ")
    best = None
    for r in results:
        rate = (r.converted / r.elapsed) if r.elapsed > 0 else 0.0
        print(
            f"{r.scenario.name:40s}  elapsed={r.elapsed:8.2f}s  ok={r.converted:5d}  skip={r.skipped:5d}  fallbacks={r.gpu_fallbacks:4d}  rate={rate:6.2f}/s"
        )
        if (best is None) or (r.elapsed < best.elapsed and r.converted == r.total):
            best = r
    if best:
        print("\nFASTEST (among scenarios that converted all files):")
        print(
            f"  {best.scenario.name}  elapsed={best.elapsed:.2f}s  files={best.converted}"
        )
    else:
        print("\nNo scenario converted all files. See per-scenario details above.")


if __name__ == "__main__":
    main()
