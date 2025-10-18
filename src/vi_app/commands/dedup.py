# src/vi_app/commands/dedup.py
"""
Interactive 'dedup' command.

This module exposes a single Typer app (`app`) that runs interactively when you
call `vi dedup`. It prompts for:
- root directory
- strategy ("content" or "metadata")
- mode ("plan" or "apply")
- destination path when applying (optional; defaults to sibling 'duplicate/' folder)
- whether to print a table of clusters

Under the hood, it builds a `DedupRequest` and calls either `plan` (dry-run)
or `apply` with a Rich progress reporter.

The goal is simplicity: one interactive flow, no subcommands, no repeated logic.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

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

from vi_app.commands.common import prompt_existing_dir, resolve_dry_run
from vi_app.modules.dedup.schemas import DedupRequest, DedupStrategy
from vi_app.modules.dedup.service import apply as dedup_apply
from vi_app.modules.dedup.service import plan as dedup_plan

__all__ = ["app"]

app = typer.Typer(help="Detect and optionally move duplicate files (interactive).")


# =============================================================================
# Progress reporter
# =============================================================================
class _RichReporter:
    """
    Bridge the service's progress reporting callbacks to a Rich Progress instance.

    The dedup service invokes reporter methods by 'phase' (scan/hash/bucket/...).
    We map those to Rich tasks with friendly labels and update them as work advances.
    """

    def __init__(self, progress: Progress) -> None:
        """
        Initialize the bridge with a Rich Progress instance.

        Args:
            progress: The Rich Progress manager to which tasks will be added.
        """
        self.progress = progress
        self.tasks: dict[str, int] = {}
        self.totals: dict[str, int | None] = {}
        self.labels = {
            "scan": "Scanning",
            "hash": "Hashing",
            "bucket": "Bucketing",
            "cluster": "Clustering",
            "select": "Selecting",
            "move": "Moving",
        }

    def start(self, phase: str, total: int | None = None, text: str | None = None) -> None:
        """
        Create a task for a given phase.

        Args:
            phase: Service-reported phase name.
            total: Optional total units of work.
            text:  Optional detail text to show alongside the bar.
        """
        label = self.labels.get(phase, phase.title())
        task_id = self.progress.add_task(label, total=total, detail=(text or ""))
        self.tasks[phase] = task_id
        self.totals[phase] = total

    def update(self, phase: str, advance: int = 1, text: str | None = None) -> None:
        """
        Advance a phase task and optionally update its detail text.

        Args:
            phase: Phase to update.
            advance: Units to add to completed work.
            text: Optional detail text to display.
        """
        task_id = self.tasks.get(phase)
        if task_id is None:
            return
        if text is not None:
            self.progress.update(task_id, advance=advance, detail=text)
        else:
            self.progress.update(task_id, advance=advance)

    def end(self, phase: str) -> None:
        """
        Mark a phase as finished. If the phase total is unknown, hide the task.

        Args:
            phase: Phase to finish.
        """
        task_id = self.tasks.get(phase)
        if task_id is None:
            return
        total = self.totals.get(phase)
        if total is None:
            self.progress.update(task_id, visible=False, detail="")
        else:
            self.progress.update(task_id, completed=total, detail="")


# =============================================================================
# Small helpers (keep the interactive flow tidy & testable)
# =============================================================================
def _make_progress(console: Console) -> tuple[Progress, _RichReporter]:
    """
    Create a Rich Progress + reporter pair with a consistent layout.

    Args:
        console: Rich console to render into.

    Returns:
        (progress manager, reporter) tuple.
    """
    progress = Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• {task.fields[detail]}"),
        console=console,
    )
    return progress, _RichReporter(progress)


def _prompt_strategy() -> DedupStrategy:
    """
    Prompt the user to choose a deduplication strategy.

    Returns:
        A `DedupStrategy` enum value.
    """
    choice = typer.prompt("strategy (content/metadata)", default="content").strip().lower()
    if choice not in {"content", "metadata"}:
        raise typer.BadParameter("strategy must be 'content' or 'metadata'")
    return DedupStrategy(choice)


def _prompt_mode() -> tuple[bool, bool]:
    """
    Prompt the user to choose 'plan' (dry-run) or 'apply'.

    Returns:
        (apply, plan) booleans suitable for `resolve_dry_run`.
    """
    mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
    if mode not in {"plan", "apply"}:
        raise typer.BadParameter("option must be 'plan' or 'apply'")
    return (mode == "apply", mode == "plan")


def _prompt_move_to() -> Path | None:
    """
    Prompt for a destination for duplicate files when applying.

    Returns:
        Path provided by the user, or None to use the default 'duplicate/' sibling.
    """
    mv = typer.prompt(
        "move-to (destination for duplicates; Enter = sibling 'duplicate/' folder)",
        default="",
    ).strip()
    return Path(mv).expanduser() if mv else None


def _summarize(clusters: Iterable) -> tuple[int, int]:
    """
    Compute summary metrics for clusters.

    Args:
        clusters: Iterable of cluster objects (must expose `.duplicates`).

    Returns:
        (num_clusters, total_duplicates)
    """
    clusters_list = list(clusters)
    total_dups = sum(len(c.duplicates) for c in clusters_list)
    return len(clusters_list), total_dups


def _render_table(console: Console, clusters: Iterable) -> None:
    """
    Render a compact table of clusters to the console.

    Args:
        console: Rich console to print to.
        clusters: Iterable of cluster objects (must expose `.keep` and `.duplicates`).
    """
    table = Table(title="Duplicate Clusters", show_lines=False)
    table.add_column("Keep", overflow="fold")
    table.add_column("# Duplicates", justify="right")
    table.add_column("Duplicates", overflow="fold")

    for c in clusters:
        table.add_row(
            c.keep,
            str(len(c.duplicates)),
            "\n".join(c.duplicates) if c.duplicates else "—",
        )
    console.print(table)


# =============================================================================
# Interactive entrypoint
# =============================================================================
@app.callback(invoke_without_command=True)
def interactive() -> None:
    """
    Run the interactive dedup flow.

    Steps:
      1) Prompt for the root folder and strategy.
      2) Prompt for 'plan' (dry-run) vs 'apply'.
      3) If applying, optionally prompt for a destination folder.
      4) Execute with a Rich progress bar.
      5) Show a one-line summary and (optionally) a table of clusters.

    Notes:
      - Default mode is 'plan' (dry-run) — no files are moved.
      - When 'apply' is selected and destination is left blank, the service
        should place duplicates in a sibling 'duplicate/' folder (service-defined).
    """
    # 1) Inputs
    root = prompt_existing_dir(None, "root")
    strategy = _prompt_strategy()
    apply, plan = _prompt_mode()
    dry_run = resolve_dry_run(apply, plan)
    move_to = _prompt_move_to() if apply else None

    show_table = typer.confirm("Show duplicate clusters table?", default=False)

    # 2) Build request
    req = DedupRequest(
        root=root,
        strategy=strategy,
        move_duplicates_to=str(move_to) if move_to else None,
        dry_run=dry_run,
    )

    # 3) Execute with progress
    console = Console()
    progress, reporter = _make_progress(console)

    t0 = time.perf_counter()
    with progress:
        clusters = dedup_plan(req, reporter=reporter) if req.dry_run else dedup_apply(req, reporter=reporter)
    elapsed = time.perf_counter() - t0

    # 4) Summary + optional table
    n_clusters, total_dups = _summarize(clusters)
    action = "PLAN" if req.dry_run else "APPLY"
    console.print(f"[{action}] strategy={strategy} clusters={n_clusters} duplicates={total_dups} in {elapsed:.2f}s")

    if show_table:
        _render_table(console, clusters)
