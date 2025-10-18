# src/vi_app/commands/dedup.py
from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vi_app.commands.common import prompt_existing_dir, resolve_dry_run
from vi_app.core.rich_progress import make_phase_progress
from vi_app.modules.dedup.schemas import DedupRequest, DedupStrategy
from vi_app.modules.dedup.service import DedupService

__all__ = ["app"]

app = typer.Typer(help="Detect and optionally move duplicate files (interactive).")


class DedupInteractiveRunner:
    """Encapsulates the interactive flow for `vi dedup`."""

    def __init__(self) -> None:
        self.console = Console()
        self.service = DedupService()

    # -------- prompts --------
    def _prompt_strategy(self) -> DedupStrategy:
        choice = (
            typer.prompt("strategy (content/metadata)", default="content")
            .strip()
            .lower()
        )
        if choice not in {"content", "metadata"}:
            raise typer.BadParameter("strategy must be 'content' or 'metadata'")
        return DedupStrategy(choice)

    def _prompt_mode(self) -> tuple[bool, bool]:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        return (mode == "apply", mode == "plan")

    def _prompt_move_to(self) -> Path | None:
        mv = typer.prompt(
            "move-to (destination for duplicates; Enter = sibling 'duplicate/' folder)",
            default="",
        ).strip()
        return Path(mv).expanduser() if mv else None

    # -------- rendering --------
    @staticmethod
    def _summarize(clusters: Iterable) -> tuple[int, int]:
        clusters_list = list(clusters)
        total_dups = sum(len(c.duplicates) for c in clusters_list)
        return len(clusters_list), total_dups

    def _render_table(self, clusters: Iterable) -> None:
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
        self.console.print(table)

    # -------- main flow --------
    def run(self) -> None:
        # 1) Inputs
        root = prompt_existing_dir(None, "root")
        strategy = self._prompt_strategy()
        apply, plan = self._prompt_mode()
        dry_run = resolve_dry_run(apply, plan)
        move_to = self._prompt_move_to() if apply else None
        show_table = typer.confirm("Show duplicate clusters table?", default=False)

        # 2) Build request
        req = DedupRequest(
            root=root,
            strategy=strategy,
            move_duplicates_to=str(move_to) if move_to else None,
            dry_run=dry_run,
        )

        # 3) Execute with progress
        progress, reporter = make_phase_progress(self.console)
        t0 = time.perf_counter()
        with progress:
            clusters = (
                self.service.plan(req, reporter=reporter)
                if req.dry_run
                else self.service.apply(req, reporter=reporter)
            )
        elapsed = time.perf_counter() - t0

        # 4) Summary + optional table
        n_clusters, total_dups = self._summarize(clusters)
        action = "PLAN" if req.dry_run else "APPLY"
        self.console.print(
            f"[{action}] strategy={strategy} clusters={n_clusters} duplicates={total_dups} in {elapsed:.2f}s"
        )
        if show_table:
            self._render_table(clusters)


@app.callback(invoke_without_command=True)
def interactive() -> None:
    """Typer entrypoint delegates all logic to the OOP runner."""
    DedupInteractiveRunner().run()
