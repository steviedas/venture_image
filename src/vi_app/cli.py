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

from vi_app.commands.cleanup import app as cleanup_app

# --- Cleanup module ---
from vi_app.commands.common import resolve_dry_run
from vi_app.commands.dedup import app as dedup_app

# --- Convert module ---
from vi_app.modules.convert.service import ConvertService

# --- Dedup module ---

app = typer.Typer(help="Venture Image CLI")

convert_app = typer.Typer(help="Convert endpoints")


app.add_typer(cleanup_app, name="cleanup")
app.add_typer(convert_app, name="convert")
app.add_typer(dedup_app, name="dedup")


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
