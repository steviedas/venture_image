# src/vi_app/cli.py
from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

# --- Cleanup module ---
from vi_app.commands.common import resolve_dry_run
from vi_app.commands.dedup import app as dedup_app
from vi_app.modules.cleanup.schemas import (
    FindMarkedDupesRequest,
    RemoveFilesRequest,
    RemoveFoldersRequest,
    SortRequest,
    SortStrategy,
)
from vi_app.modules.cleanup.service import (
    FindMarkedDupesService,
    RemoveFilesService,
    RemoveFoldersService,
    RenameService,
    SortService,
)

# --- Convert module ---
from vi_app.modules.convert.service import ConvertService

# --- Dedup module ---

app = typer.Typer(help="Venture Image CLI")

cleanup_app = typer.Typer(help="Cleanup endpoints")
convert_app = typer.Typer(help="Convert endpoints")


app.add_typer(cleanup_app, name="cleanup")
app.add_typer(convert_app, name="convert")
app.add_typer(dedup_app, name="dedup")


# =========================
# group: CLEANUP (mirrors /cleanup)
# =========================
@cleanup_app.command(
    "remove-files", help="Find and (optionally) delete files matching regex patterns."
)
def cleanup_remove_files_cmd(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    pattern: list[str] = typer.Option(
        ..., "--pattern", "-p", help="Regex pattern(s). Repeat the flag."
    ),
    prune_empty: bool = typer.Option(
        True,
        "--prune-empty/--no-prune-empty",
        help="Remove now-empty dirs after delete.",
    ),
    apply: bool = typer.Option(False, "--apply", help="Delete files."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = resolve_dry_run(apply, plan)
    req = RemoveFilesRequest(
        root=root, patterns=pattern, dry_run=dry_run, remove_empty_dirs=prune_empty
    )
    svc = RemoveFilesService(Path(req.root))
    deleted = svc.run(req.patterns, req.dry_run, req.remove_empty_dirs)
    verb = "Would remove" if req.dry_run else "Removed"
    typer.echo(f"{verb} {len(deleted)} file(s)")
    for p in deleted:
        typer.echo(str(p))


@cleanup_app.command(
    "remove-folders", help="Find and (optionally) remove directories by exact name."
)
def cleanup_remove_folders_cmd(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    name: list[str] = typer.Option(
        ["duplicate"], "--name", "-n", help="Folder name(s). Repeat the flag."
    ),
    apply: bool = typer.Option(False, "--apply", help="Remove directories."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = resolve_dry_run(apply, plan)
    req = RemoveFoldersRequest(root=root, folder_names=name, dry_run=dry_run)
    svc = RemoveFoldersService(Path(req.root))
    removed = svc.run(req.folder_names, req.dry_run)
    verb = "Would remove" if req.dry_run else "Removed"
    typer.echo(f"{verb} {len(removed)} directories")
    for p in removed:
        typer.echo(str(p))


@cleanup_app.command(
    "find-marked-dupes",
    help="List files whose filename stem matches a suffix regex (e.g., _dupe(\\d+)$).",
)
def cleanup_find_marked_dupes_cmd(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    suffix_pattern: str = typer.Option(
        r"_dupe\(\d+\)$", "--suffix", "-s", help="Regex applied to filename stem."
    ),
    plan: bool = typer.Option(
        False, "--plan", help="Alias for dry-run (read-only command)."
    ),
):
    # This command is read-only; support --plan for consistency, but ignore its value.
    req = FindMarkedDupesRequest(root=root, suffix_pattern=suffix_pattern)
    svc = FindMarkedDupesService(Path(req.root))
    items = svc.run(req.suffix_pattern)
    typer.echo(f"Found {len(items)} file(s)")
    for p in items:
        typer.echo(str(p))


@cleanup_app.command(
    "rename",
    help="Per directory, rename images to IMG_XXXXXX then videos to VID_XXXXXX (uses the same digit width).",
)
def cleanup_rename_cmd(
    # Make args optional so we can prompt when missing
    root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    recurse: bool | None = typer.Option(
        None, "--recurse/--no-recurse", help="Process subdirectories."
    ),
    zero_pad: int | None = typer.Option(
        None,
        "--zero-pad",
        "-z",
        min=3,
        max=10,
        help="Digits in sequence for BOTH images and videos.",
    ),
    apply: bool = typer.Option(False, "--apply", help="Perform renames."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    # ---------- Interactive prompts ----------
    if root is None:
        root = Path(typer.prompt("root (folder to process)")).expanduser()
    if not root.exists() or not root.is_dir():
        raise typer.BadParameter(f"root does not exist or is not a directory: {root}")

    if recurse is None:
        recurse = typer.confirm("Process subdirectories?", default=True)

    # Single prompt for both images and videos
    if zero_pad is None:
        zero_pad = typer.prompt(
            "Digits in sequence (3-10) for BOTH images and videos", default=6, type=int
        )
        if not (3 <= zero_pad <= 10):
            raise typer.BadParameter("zero-pad must be between 3 and 10")

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = resolve_dry_run(apply, plan)
    console = Console()

    # =======================
    # PHASE 1: IMAGES (IMG_)
    # =======================
    t_total0 = time.perf_counter()

    # Plan images
    t_plan0 = time.perf_counter()
    svc = RenameService(root=root, recurse=recurse, zero_pad=zero_pad)
    with console.status("Planning image renames… found 0 files") as status:

        def _on_discover(n: int) -> None:
            status.update(status=f"Planning image renames… found {n} files")

        img_targets = svc.enumerate_targets(on_discover=_on_discover)
    img_plan_elapsed = time.perf_counter() - t_plan0

    img_total = len(img_targets)
    if img_total == 0:
        console.print("No images to rename.", style="dim")
    elif dry_run:
        typer.echo(f"[PLAN] images: {img_total} file(s) will be renamed")
        for src, dst in img_targets:
            typer.echo(f"{src} -> {dst}")
    else:
        # APPLY with separate progress bar (images)
        bar = Progress(
            TextColumn("[bold]Renaming images[/]"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("• {task.description}"),
            console=console,
        )
        renamed = 0
        skipped = 0
        failures: list[tuple[Path, Path, str]] = []
        with bar:
            task = bar.add_task("starting…", total=img_total)
            for src, dst, ok, reason in svc.iter_apply(targets=img_targets):
                bar.update(
                    task, advance=1, description=f"{Path(src).name} -> {Path(dst).name}"
                )
                if ok:
                    renamed += 1
                else:
                    skipped += 1
                    failures.append((Path(src), Path(dst), reason or "unknown"))
        console.print(
            f"Computed image mapping in {img_plan_elapsed:.2f}s.", style="dim"
        )
        if failures:
            console.print("[bold yellow]Skipped/failed image renames:[/bold yellow]")
            for src, dst, reason in failures:
                console.print(f"{src} -> {dst}  [yellow]SKIP[/yellow] ({reason})")
        img_elapsed_total = time.perf_counter() - t_total0
        img_rate = img_total / img_elapsed_total if img_elapsed_total > 0 else 0.0
        img_summary_style = "bold green" if skipped == 0 else "bold yellow"
        console.print(
            f"Images: renamed {renamed}, skipped {skipped} of {img_total} in {img_elapsed_total:.2f}s (~{img_rate:.1f} files/s).",
            style=img_summary_style,
        )

    # =======================
    # PHASE 2: VIDEOS (VID_)
    # =======================
    # Use the SAME zero_pad value
    t_plan1 = time.perf_counter()
    vid_targets = svc.enumerate_video_targets(
        zero_pad=zero_pad,
        on_discover=lambda n: None,
    )
    time.perf_counter() - t_plan1

    vid_total = len(vid_targets)
    if vid_total == 0:
        console.print("No videos to rename.", style="dim")
        return

    if dry_run:
        typer.echo(f"[PLAN] videos: {vid_total} file(s) will be renamed")
        for src, dst in vid_targets:
            typer.echo(f"{src} -> {dst}")
        return

    # APPLY with a separate progress bar (videos)
    bar_v = Progress(
        TextColumn("[bold]Renaming videos[/]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• {task.description}"),
        console=console,
    )
    v_renamed = 0
    v_skipped = 0
    v_failures: list[tuple[Path, Path, str]] = []
    with bar_v:
        task_v = bar_v.add_task("starting…", total=vid_total)
        for src, dst, ok, reason in svc.iter_apply(targets=vid_targets):
            bar_v.update(
                task_v, advance=1, description=f"{Path(src).name} -> {Path(dst).name}"
            )
            if ok:
                v_renamed += 1
            else:
                v_skipped += 1
                v_failures.append((Path(src), Path(dst), reason or "unknown"))

    if v_failures:
        console.print("[bold yellow]Skipped/failed video renames:[/bold yellow]")
        for src, dst, reason in v_failures:
            console.print(f"{src} -> {dst}  [yellow]SKIP[/yellow] ({reason})")

    vid_elapsed_total = time.perf_counter() - t_plan1
    vid_rate = vid_total / vid_elapsed_total if vid_elapsed_total > 0 else 0.0
    v_summary_style = "bold green" if v_skipped == 0 else "bold yellow"
    console.print(
        f"Videos: renamed {v_renamed}, skipped {v_skipped} of {vid_total} in {vid_elapsed_total:.2f}s (~{vid_rate:.1f} files/s).",
        style=v_summary_style,
    )


@cleanup_app.command(
    "sort",
    help="Sort images by date or location (dry-run by default) or apply with --apply/--plan.",
)
def cleanup_sort_cmd(
    src_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    dst_root: Path | None = typer.Option(
        None, "--dst-root", "-d", help="Destination root (mirror if omitted)."
    ),
    strategy: SortStrategy = typer.Option(
        SortStrategy.by_date, "--strategy", "-s", help="by_date|by_location"
    ),
    apply: bool = typer.Option(False, "--apply", help="Perform moves."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = resolve_dry_run(apply, plan)
    req = SortRequest(
        src_root=src_root, dst_root=dst_root, strategy=strategy, dry_run=dry_run
    )
    svc = SortService(Path(req.src_root))
    moves = svc.plan(req) if req.dry_run else svc.apply(req)
    action = "PLAN" if req.dry_run else "APPLY"
    typer.echo(f"[{action}] strategy={strategy} moves={len(moves)}")
    for m in moves:
        typer.echo(f"{m.src} -> {m.dst}")


# =========================
# group: CONVERT (mirrors /convert)
# =========================
@convert_app.command(
    "folder-to-jpeg", help="Convert supported images under a folder to JPEG."
)
def convert_folder_to_jpeg_cmd(
    # Interactive prompts kick in when these are omitted:
    src_root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    dst_root: Path | None = typer.Option(
        None, "--dst-root", "-d", help="Destination root (mirror if omitted)."
    ),
    quality: int | None = typer.Option(
        None, "--quality", "-q", min=1, max=100, help="JPEG quality."
    ),
    overwrite: bool | None = typer.Option(
        None, "--overwrite/--no-overwrite", help="Overwrite destination if exists."
    ),
    recurse: bool | None = typer.Option(
        None, "--recurse/--no-recurse", help="Scan subfolders."
    ),
    flatten_alpha: bool | None = typer.Option(
        None,
        "--flatten-alpha/--no-flatten-alpha",
        help="Composite transparency to white.",
    ),
    apply: bool = typer.Option(False, "--apply", help="Perform writes."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    # -------- prompts for any missing inputs --------
    def _confirm(msg: str, default: bool) -> bool:
        return typer.confirm(msg, default=default)

    if src_root is None:
        src_root = Path(typer.prompt("src (folder to scan)")).expanduser()
    if not src_root.exists() or not src_root.is_dir():
        raise typer.BadParameter(
            f"src_root does not exist or is not a directory: {src_root}"
        )

    # You can leave dst_root None — the service defaults to <src>/converted
    if dst_root is None:
        dst_str = typer.prompt(
            "dst (destination root; press Enter to use default '<src>/converted')",
            default="",
        )
        dst_root = Path(dst_str).expanduser() if dst_str else None

    if quality is None:
        quality = typer.prompt("quality (1-100)", default=100, type=int)
        if not (1 <= quality <= 100):
            raise typer.BadParameter("quality must be between 1 and 100")

    if overwrite is None:
        overwrite = _confirm(
            "overwrite destination files if they already exist?", default=False
        )

    if recurse is None:
        recurse = _confirm("recurse into subfolders?", default=True)

    if flatten_alpha is None:
        flatten_alpha = _confirm(
            "flatten alpha (composite transparency to white)?", default=True
        )

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = resolve_dry_run(apply, plan)

    # inside convert_folder_to_jpeg_cmd after computing dry_run
    t0 = time.perf_counter()
    svc = ConvertService(
        src_root=src_root,
        dst_root=dst_root,
        recurse=recurse,
        quality=quality,
        overwrite=overwrite,
        flatten_alpha=flatten_alpha,
        dry_run=dry_run,
    )

    targets = svc.enumerate_targets()
    total = len(targets)
    if total == 0:
        typer.echo("No convertible images found.")
        return

    if dry_run:
        for src, dst in targets:
            typer.echo(f"{src} -> {dst}")
        elapsed = time.perf_counter() - t0
        rate = total / elapsed if elapsed > 0 else 0.0
        typer.echo(
            f"Would convert {total} file(s) in {elapsed:.2f}s (~{rate:.1f} files/s)."
        )
        return

    console = Console()
    bar = Progress(
        TextColumn("[bold]Converting[/]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• {task.description}"),
        console=console,
    )

    converted = 0
    skipped = 0
    skipped_results: list[tuple[Path, str | None]] = []

    with bar:
        task = bar.add_task("starting…", total=total)

        for src, dst, ok, reason in svc.iter_apply(targets=targets, on_progress=None):
            bar.update(
                task, advance=1, description=f"{Path(src).name} -> {Path(dst).name}"
            )
            if ok:
                converted += 1
            else:
                skipped += 1
                skipped_results.append((src, reason))

    elapsed = time.perf_counter() - t0
    rate = total / elapsed if elapsed > 0 else 0.0

    if skipped_results:
        table = Table(title="Skipped files", show_lines=False)
        table.add_column("Source", overflow="fold")
        table.add_column("Reason", overflow="fold")
        for src, reason in skipped_results:
            table.add_row(str(src), reason or "")
        console.print(table)

    console.print(
        f"Converted {converted} file(s), skipped {skipped} out of {total} in {elapsed:.2f}s (~{rate:.1f} files/s).",
        style="bold green",
    )


@convert_app.command(
    "webp-to-jpeg", help="Convert all .webp images under a folder to JPEG."
)
def convert_webp_to_jpeg_cmd(
    # Make src_root optional so we can prompt for it:
    src_root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    dst_root: Path | None = typer.Option(
        None, "--dst-root", "-d", help="Destination root (mirror if omitted)."
    ),
    quality: int | None = typer.Option(
        None, "--quality", "-q", min=1, max=100, help="JPEG quality."
    ),
    overwrite: bool | None = typer.Option(
        None, "--overwrite/--no-overwrite", help="Overwrite destination if exists."
    ),
    flatten_alpha: bool | None = typer.Option(
        None,
        "--flatten-alpha/--no-flatten-alpha",
        help="Composite transparency to white.",
    ),
    apply: bool = typer.Option(False, "--apply", help="Perform writes."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    # -------- prompts for any missing inputs (mirror folder-to-jpeg UX) --------
    def _confirm(msg: str, default: bool) -> bool:
        return typer.confirm(msg, default=default)

    if src_root is None:
        src_root = Path(typer.prompt("src (folder to scan)")).expanduser()
    if not src_root.exists() or not src_root.is_dir():
        raise typer.BadParameter(
            f"src_root does not exist or is not a directory: {src_root}"
        )

    # You can leave dst_root None — the service defaults to <src>/converted
    if dst_root is None:
        dst_str = typer.prompt(
            "dst (destination root; press Enter to use default '<src>/converted')",
            default="",
        )
        dst_root = Path(dst_str).expanduser() if dst_str else None

    if quality is None:
        quality = typer.prompt("quality (1-100)", default=100, type=int)
        if not (1 <= quality <= 100):
            raise typer.BadParameter("quality must be between 1 and 100")

    if overwrite is None:
        overwrite = _confirm(
            "overwrite destination files if they already exist?", default=False
        )

    if flatten_alpha is None:
        flatten_alpha = _confirm(
            "flatten alpha (composite transparency to white)?", default=True
        )

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = resolve_dry_run(apply, plan)

    # -------- time the whole operation --------
    t0 = time.perf_counter()

    # Build service (OOP + parallel), restricting to .webp only
    svc = ConvertService(
        src_root=src_root,
        dst_root=dst_root,
        recurse=True,  # webp tool is recursive by design
        quality=quality,
        overwrite=overwrite,
        flatten_alpha=flatten_alpha,
        only_exts={".webp"},
        dry_run=dry_run,
    )

    targets = svc.enumerate_targets()
    total = len(targets)
    if total == 0:
        typer.echo("No .webp images found.")
        return

    if dry_run:
        # -------- PLAN MODE: print the plan, no Rich/progress --------
        for src, dst in targets:
            typer.echo(f"{src} -> {dst}")
        elapsed = time.perf_counter() - t0
        rate = total / elapsed if elapsed > 0 else 0.0
        typer.echo(
            f"Would convert {total} file(s) in {elapsed:.2f}s (~{rate:.1f} files/s)."
        )
        return

    # -------- APPLY MODE: show progress bar while converting --------
    console = Console()
    bar = Progress(
        TextColumn("[bold]Converting[/]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• {task.description}"),
        console=console,
    )

    converted = 0
    skipped = 0
    skipped_results: list[tuple[Path, str | None]] = []

    with bar:
        task = bar.add_task("starting…", total=total)
        for src, dst, ok, reason in svc.iter_apply(targets=targets):
            bar.update(
                task, advance=1, description=f"{Path(src).name} -> {Path(dst).name}"
            )
            if ok:
                converted += 1
            else:
                skipped += 1
                skipped_results.append((src, reason))

    elapsed = time.perf_counter() - t0
    rate = total / elapsed if elapsed > 0 else 0.0

    if skipped_results:
        table = Table(title="Skipped files", show_lines=False)
        table.add_column("Source", overflow="fold")
        table.add_column("Reason", overflow="fold")
        for src, reason in skipped_results:
            table.add_row(str(src), reason or "")
        console.print(table)

    console.print(
        f"Converted {converted} file(s), skipped {skipped} out of {total} in {elapsed:.2f}s (~{rate:.1f} files/s).",
        style="bold green",
    )


if __name__ == "__main__":
    app()
