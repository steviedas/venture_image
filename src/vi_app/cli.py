# src\vi_app\cli.py
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

from vi_app.modules.cleanup.schemas import (
    FindMarkedDupesRequest,
    RemoveFilesRequest,
    RemoveFoldersRequest,
    RenameBySequenceRequest,
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
from vi_app.modules.convert_images.service import (
    ConvertService,
)
from vi_app.modules.dedup.schemas import DedupRequest, DedupStrategy
from vi_app.modules.dedup.service import apply as dedup_apply
from vi_app.modules.dedup.service import plan as dedup_plan

app = typer.Typer(help="Venture Image CLI")

cleanup_app = typer.Typer(help="Cleanup endpoints")
convert_app = typer.Typer(help="Convert endpoints")
dedup_app = typer.Typer(help="Dedup endpoints")

app.add_typer(cleanup_app, name="cleanup")
app.add_typer(convert_app, name="convert")
app.add_typer(dedup_app, name="dedup")


def _resolve_dry_run(apply: bool, plan: bool) -> bool:
    """
    Standardize dry-run across commands.
    - default: dry-run (plan)
    - --apply => not dry-run
    - --plan  => force dry-run
    - both    => error
    """
    if apply and plan:
        raise typer.BadParameter("Use either --apply or --plan, not both.")
    # dry-run if not applying OR explicitly planning
    return (not apply) or plan


# =========================
# group: DEDUP (mirrors /dedup)
# =========================
@dedup_app.command(
    "run",
    help="Detect duplicates (dry-run by default) or move them with --apply / plan with --plan.",
)
def dedup_run(
    root: Path = typer.Argument(
        ..., exists=True, file_okay=False, dir_okay=True, help="Root folder to scan."
    ),
    strategy: DedupStrategy = typer.Option(
        DedupStrategy.content, "--strategy", "-s", help="content|metadata"
    ),
    move_to: Path | None = typer.Option(
        None, "--move-to", "-m", help="Where to move duplicates when applying."
    ),
    apply: bool = typer.Option(False, "--apply", help="Perform moves."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = DedupRequest(
        root=root,
        strategy=strategy,
        move_duplicates_to=str(move_to) if move_to else None,
        dry_run=dry_run,
    )
    clusters = dedup_plan(req) if req.dry_run else dedup_apply(req)

    total_dups = sum(len(c.duplicates) for c in clusters)
    action = "PLAN" if req.dry_run else "APPLY"
    typer.echo(
        f"[{action}] strategy={strategy} clusters={len(clusters)} duplicates={total_dups}"
    )
    for c in clusters:
        typer.echo(f" keep: {c.keep}")
        for d in c.duplicates:
            typer.echo(f"   dup: {d}")


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
    dry_run = _resolve_dry_run(apply, plan)
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
    dry_run = _resolve_dry_run(apply, plan)
    req = RemoveFoldersRequest(root=root, folder_names=name, dry_run=dry_run)
    svc = RemoveFoldersService(Path(req.root))
    removed = svc.run(req.folder_names, req.dry_run)
    verb = "Would remove" if req.dry_run else "Removed"
    typer.echo(f"{verb} {len(removed)} directorie(s)")
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
    "rename", help="Per directory, rename images to IMG_XXXXXX ordered by date taken."
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
        None, "--zero-pad", "-z", min=3, max=10, help="Digits in sequence."
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

    if zero_pad is None:
        zero_pad = typer.prompt("Digits in sequence (3-10)", default=6, type=int)
        if not (3 <= zero_pad <= 10):
            raise typer.BadParameter("zero-pad must be between 3 and 10")

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = _resolve_dry_run(apply, plan)
    req = RenameBySequenceRequest(
        root=root, recurse=recurse, zero_pad=zero_pad, dry_run=dry_run
    )

    t_total0 = time.perf_counter()
    console = Console()

    # ---------- Plan once (time it) ----------
    t_plan0 = time.perf_counter()
    svc = RenameService(root=root, recurse=recurse, zero_pad=zero_pad)

    with console.status("Planning renames… found 0 files") as status:

        def _on_discover(n: int) -> None:
            status.update(status=f"Planning renames… found {n} files")

        targets = svc.enumerate_targets(on_discover=_on_discover)

    plan_elapsed = time.perf_counter() - t_plan0

    total = len(targets)
    if total == 0:
        typer.echo("No images to rename.")
        return

    # ---------- PLAN MODE: print full plan, include mapping time ----------
    if req.dry_run:
        typer.echo(f"Plan: {total} file(s) will be renamed")
        for src, dst in targets:
            typer.echo(f"{src} -> {dst}")
        elapsed_total = time.perf_counter() - t_total0
        rate = total / elapsed_total if elapsed_total > 0 else 0.0
        typer.echo(f"Computed mapping in {plan_elapsed:.2f}s.")
        typer.echo(
            f"Would rename {total} file(s) in {elapsed_total:.2f}s (~{rate:.1f} files/s)."
        )
        return

    # ---------- APPLY MODE: progress bar; only print failures ----------
    bar = Progress(
        TextColumn("[bold]Renaming[/]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• {task.description}"),
        console=console,
    )

    renamed = 0
    skipped = 0
    failures: list[tuple[Path, Path, str]] = []  # (src, dst, reason)

    with bar:
        task = bar.add_task("starting…", total=total)
        for src, dst, ok, reason in svc.iter_apply(targets=targets):
            bar.update(
                task, advance=1, description=f"{Path(src).name} -> {Path(dst).name}"
            )
            if ok:
                renamed += 1
            else:
                skipped += 1
                failures.append((Path(src), Path(dst), reason or "unknown"))

    # ⬇️ this line will appear immediately after the progress bar
    console.print(f"Computed mapping in {plan_elapsed:.2f}s.", style="dim")

    # (optional) list only failures
    if failures:
        console.print("[bold yellow]Skipped/failed renames:[/bold yellow]")
        for src, dst, reason in failures:
            console.print(f"{src} -> {dst}  [yellow]SKIP[/yellow] ({reason})")

    elapsed_total = time.perf_counter() - t_total0
    rate = total / elapsed_total if elapsed_total > 0 else 0.0
    summary_style = "bold green" if skipped == 0 else "bold yellow"
    console.print(
        f"Renamed {renamed} file(s), skipped {skipped} out of {total} in {elapsed_total:.2f}s (~{rate:.1f} files/s).",
        style=summary_style,
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
    dry_run = _resolve_dry_run(apply, plan)
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

    dry_run = _resolve_dry_run(apply, plan)

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

        def _tick(_n: int) -> None:
            # update each time a file finishes
            pass  # (handled in loop when each result yields)

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

    dry_run = _resolve_dry_run(apply, plan)

    # -------- time the whole operation --------
    t0 = time.perf_counter()

    # Build service (OOP + parallel), restricting to .webp only
    svc = ConvertService(
        src_root=src_root,
        dst_root=dst_root,
        recurse=True,                # webp tool is recursive by design
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
            bar.update(task, advance=1, description=f"{Path(src).name} -> {Path(dst).name}")
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
