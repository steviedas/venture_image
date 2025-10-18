# src\vi_app\commands\dedup.py
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

from vi_app.commands.common import prompt_existing_dir, resolve_dry_run
from vi_app.modules.dedup.schemas import DedupRequest, DedupStrategy
from vi_app.modules.dedup.service import apply as dedup_apply
from vi_app.modules.dedup.service import plan as dedup_plan

app = typer.Typer(help="Dedup endpoints")


# ---- Rich reporter (moved out of cli.py with same behavior) ----
class _RichReporter:
    """Bridge the service's ProgressReporter interface to a Rich Progress instance."""

    def __init__(self, progress: Progress) -> None:
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

    def start(
        self, phase: str, total: int | None = None, text: str | None = None
    ) -> None:
        label = self.labels.get(phase, phase.title())
        task_id = self.progress.add_task(label, total=total, detail=(text or ""))
        self.tasks[phase] = task_id
        self.totals[phase] = total

    def update(self, phase: str, advance: int = 1, text: str | None = None) -> None:
        task_id = self.tasks.get(phase)
        if task_id is None:
            return
        if text is not None:
            self.progress.update(task_id, advance=advance, detail=text)
        else:
            self.progress.update(task_id, advance=advance)

    def end(self, phase: str) -> None:
        task_id = self.tasks.get(phase)
        if task_id is None:
            return

        total = self.totals.get(phase)
        if total is None:
            self.progress.update(task_id, visible=False, detail="")
        else:
            self.progress.update(task_id, completed=total, detail="")


# ---- Internal runner used by callback + command ----
def _run_interactive(
    *,
    root: Path | None,
    strategy: DedupStrategy | None,
    move_to: Path | None,
    apply: bool,
    plan: bool,
    show_table: bool,
):
    # Interactive prompts only for missing values (same UX as before)
    root = prompt_existing_dir(root, "root")

    if strategy is None:
        choice = (
            typer.prompt("strategy (content/metadata)", default="content")
            .strip()
            .lower()
        )
        if choice not in {"content", "metadata"}:
            raise typer.BadParameter("strategy must be 'content' or 'metadata'")
        strategy = DedupStrategy(choice)

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = resolve_dry_run(apply, plan)

    if apply and move_to is None:
        mv = typer.prompt(
            "move-to (destination for duplicates; Enter = sibling 'duplicate/' folder)",
            default="",
        ).strip()
        move_to = Path(mv).expanduser() if mv else None

    req = DedupRequest(
        root=root,
        strategy=strategy,
        move_duplicates_to=str(move_to) if move_to else None,
        dry_run=dry_run,
    )

    console = Console()
    progress = Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• {task.fields[detail]}"),
        console=console,
    )

    reporter = _RichReporter(progress)

    t0 = time.perf_counter()
    with progress:
        clusters = (
            dedup_plan(req, reporter=reporter)
            if req.dry_run
            else dedup_apply(req, reporter=reporter)
        )
    elapsed = time.perf_counter() - t0

    total_dups = sum(len(c.duplicates) for c in clusters)
    action = "PLAN" if req.dry_run else "APPLY"
    console.print(
        f"[{action}] strategy={strategy} clusters={len(clusters)} duplicates={total_dups} in {elapsed:.2f}s"
    )

    if show_table:
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


# ---- Public CLI: `vi dedup run` ----
@app.command(
    "run",
    help="Detect duplicates (dry-run by default) or move them with --apply / plan with --plan.",
)
def run(
    root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    strategy: DedupStrategy | None = typer.Option(
        None, "--strategy", "-s", help="content|metadata"
    ),
    move_to: Path | None = typer.Option(
        None, "--move-to", "-m", help="Where to move duplicates when applying."
    ),
    apply: bool = typer.Option(False, "--apply", help="Perform moves."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
    show_table: bool = typer.Option(
        False,
        "--show-table/--no-show-table",
        help="Print the duplicate clusters table.",
    ),
):
    _run_interactive(
        root=root,
        strategy=strategy,
        move_to=move_to,
        apply=apply,
        plan=plan,
        show_table=show_table,
    )


# Allow `vi dedup` (no subcommand) to behave like `vi dedup run`
@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        _run_interactive(
            root=None,
            strategy=None,
            move_to=None,
            apply=False,
            plan=False,
            show_table=False,
        )
