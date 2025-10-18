# src\vi_app\core\rich_progress.py
from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from vi_app.core.progress import Phase, ProgressReporter


class RichPhaseProgressReporter(ProgressReporter):
    """Reusable Rich bridge that maps service 'phases' to Rich tasks."""

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
        self, phase: Phase, total: int | None = None, text: str | None = None
    ) -> None:
        label = self.labels.get(phase, str(phase).title())
        task_id = self.progress.add_task(label, total=total, detail=(text or ""))
        self.tasks[str(phase)] = task_id
        self.totals[str(phase)] = total

    def update(self, phase: Phase, advance: int = 1, text: str | None = None) -> None:
        task_id = self.tasks.get(str(phase))
        if task_id is None:
            return
        kwargs = {"advance": advance}
        if text is not None:
            kwargs["detail"] = text
        self.progress.update(task_id, **kwargs)

    def end(self, phase: Phase) -> None:
        task_id = self.tasks.get(str(phase))
        if task_id is None:
            return
        total = self.totals.get(str(phase))
        if total is None:
            self.progress.update(task_id, visible=False, detail="")
        else:
            self.progress.update(task_id, completed=total, detail="")


def make_phase_progress(console: Console) -> tuple[Progress, RichPhaseProgressReporter]:
    """Standardized Rich progress layout + reporter instance."""
    progress = Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• {task.fields[detail]}"),
        console=console,
    )
    return progress, RichPhaseProgressReporter(progress)
