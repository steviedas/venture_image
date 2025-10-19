# src\vi_app\commands\cleanup.py
from __future__ import annotations

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

from vi_app.commands.common import prompt_existing_dir, resolve_dry_run
from vi_app.core.rich_progress import make_phase_progress
from vi_app.modules.cleanup.schemas import (
    RemoveFilesRequest,
    RemoveFoldersRequest,
    SortRequest,
    SortStrategy,
)
from vi_app.modules.cleanup.service import (
    RemoveFilesService,
    RemoveFoldersService,
    RenameService,
    SortService,
)

app = typer.Typer(help="Cleanup commands")


# ----------------------
# Remove Files
# ----------------------
class RemoveFilesRunner:
    def __init__(
        self, root: Path, patterns: list[str], dry_run: bool, prune_empty: bool
    ) -> None:
        self.root = root
        self.patterns = patterns
        self.dry_run = dry_run
        self.prune_empty = prune_empty

    def run(self) -> None:
        req = RemoveFilesRequest(
            root=self.root,
            patterns=self.patterns,
            dry_run=self.dry_run,
            remove_empty_dirs=self.prune_empty,
        )
        svc = RemoveFilesService(Path(req.root))

        # PLAN or APPLY
        planned = svc.run(req.patterns, True, req.remove_empty_dirs)
        typer.echo(f"[PLAN] Would remove {len(planned)} file(s)")
        for p in planned:
            typer.echo(str(p))

        # If this was only a plan, offer to apply immediately
        if self.dry_run and planned:
            if typer.confirm("Apply these removals now?", default=False):
                applied = svc.run(req.patterns, False, req.remove_empty_dirs)
                typer.echo(f"[APPLY] Removed {len(applied)} file(s)")
                return

        # If user originally asked for apply, we already planned; now do it
        if not self.dry_run:
            applied = svc.run(req.patterns, False, req.remove_empty_dirs)
            typer.echo(f"[APPLY] Removed {len(applied)} file(s)")


@app.command("remove-files")
def remove_files_cmd(
    root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    pattern: list[str] = typer.Option(
        [], "--pattern", "-p", help="Regex pattern(s). Repeat flag."
    ),
    prune_empty: bool | None = typer.Option(
        None, "--prune-empty/--no-prune-empty", help="Remove empty dirs after deletion"
    ),
    apply: bool = typer.Option(False, "--apply", help="Execute changes"),
    plan: bool = typer.Option(False, "--plan", help="Plan only (dry-run)"),
):
    # Prompt for any missing inputs
    if root is None:
        root = prompt_existing_dir(None, "root")

    if not pattern:
        raw = typer.prompt(
            "Regex pattern(s) to match files for removal (comma-separated)",
            default=r".*\.(tmp|log|ds_store)$",
        )
        pattern = [p.strip() for p in raw.split(",") if p.strip()]

    if prune_empty is None:
        prune_empty = typer.confirm(
            "Remove empty directories after deleting files?", default=True
        )

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = resolve_dry_run(apply, plan)
    RemoveFilesRunner(root, pattern, dry_run, prune_empty).run()


# ----------------------
# Remove Folders
# ----------------------
class RemoveFoldersRunner:
    def __init__(self, root: Path, folder_names: list[str], dry_run: bool) -> None:
        self.root = root
        self.folder_names = folder_names
        self.dry_run = dry_run

    def run(self) -> None:
        req = RemoveFoldersRequest(
            root=self.root, folder_names=self.folder_names, dry_run=self.dry_run
        )
        svc = RemoveFoldersService(Path(req.root))

        # PLAN
        planned = svc.run(req.folder_names, True)
        typer.echo(f"[PLAN] Would remove {len(planned)} directorie(s)")
        for p in planned:
            typer.echo(str(p))

        # Offer to apply
        if self.dry_run and planned:
            if typer.confirm("Apply these removals now?", default=False):
                applied = svc.run(req.folder_names, False)
                typer.echo(f"[APPLY] Removed {len(applied)} directorie(s)")
                return

        # If user originally asked for apply
        if not self.dry_run:
            applied = svc.run(req.folder_names, False)
            typer.echo(f"[APPLY] Removed {len(applied)} directorie(s)")


@app.command("remove-folders")
def remove_folders_cmd(
    root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    name: list[str] = typer.Option(
        [], "--name", "-n", help="Folder name(s). Repeat flag."
    ),
    apply: bool = typer.Option(False, "--apply", help="Execute changes"),
    plan: bool = typer.Option(False, "--plan", help="Plan only (dry-run)"),
):
    # Prompt for any missing inputs
    if root is None:
        root = prompt_existing_dir(None, "root")

    if not name:
        raw = typer.prompt(
            "Folder name(s) to remove (comma-separated)",
            default="duplicate",
        )
        name = [n.strip() for n in raw.split(",") if n.strip()] or ["duplicate"]

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = resolve_dry_run(apply, plan)
    RemoveFoldersRunner(root, name, dry_run).run()


# ----------------------
# Rename (IMG_/VID_ sequences)
# ----------------------
class RenameRunner:
    def __init__(self, root: Path, recurse: bool, zero_pad: int, dry_run: bool) -> None:
        self.root = root
        self.recurse = recurse
        self.zero_pad = zero_pad
        self.dry_run = dry_run
        self.console = Console()

    def _progress(self) -> Progress:
        return Progress(
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("• {task.fields[detail]}"),
            console=self.console,
        )

    def run(self) -> None:
        svc = RenameService(
            root=self.root, recurse=self.recurse, zero_pad=self.zero_pad
        )

        # PLAN (gather both images and videos before deciding)
        with self.console.status("Planning image renames… found 0 files") as status:

            def _on_discover(n: int) -> None:
                status.update(status=f"Planning image renames… found {n} files")

            img_targets = svc.enumerate_targets(on_discover=_on_discover)
        vid_targets = svc.enumerate_video_targets(
            zero_pad=self.zero_pad, on_discover=lambda n: None
        )

        img_total = len(img_targets)
        vid_total = len(vid_targets)

        # Display plan
        if img_total == 0:
            self.console.print("No images to rename.", style="dim")
        else:
            typer.echo(f"[PLAN] images: {img_total} file(s) will be renamed")
            if self.dry_run:
                for src, dst in img_targets:
                    typer.echo(f"{src} -> {dst}")

        if vid_total == 0:
            self.console.print("No videos to rename.", style="dim")
        else:
            typer.echo(f"[PLAN] videos: {vid_total} file(s) will be renamed")
            if self.dry_run:
                for src, dst in vid_targets:
                    typer.echo(f"{src} -> {dst}")

        # If dry-run, offer to apply both phases now
        if self.dry_run and (img_total or vid_total):
            if not typer.confirm("Apply these renames now?", default=False):
                return

        # APPLY images (if any)
        if img_total:
            bar = self._progress()
            renamed = skipped = 0
            failures: list[tuple[Path, Path, str]] = []
            with bar:
                task = bar.add_task("Renaming images", total=img_total, detail="")
                for src, dst, ok, reason in svc.iter_apply(targets=img_targets):
                    bar.update(
                        task, advance=1, detail=f"{Path(src).name} -> {Path(dst).name}"
                    )
                    if ok:
                        renamed += 1
                    else:
                        skipped += 1
                        failures.append((Path(src), Path(dst), reason or "unknown"))
            if failures:
                self.console.print(
                    "[bold yellow]Skipped/failed image renames:[/bold yellow]"
                )
                for src, dst, reason in failures:
                    self.console.print(
                        f"{src} -> {dst}  [yellow]SKIP[/yellow] ({reason})"
                    )

        # APPLY videos (if any)
        if vid_total:
            bar_v = self._progress()
            v_renamed = v_skipped = 0
            v_failures: list[tuple[Path, Path, str]] = []
            with bar_v:
                task_v = bar_v.add_task("Renaming videos", total=vid_total, detail="")
                for src, dst, ok, reason in svc.iter_apply(targets=vid_targets):
                    bar_v.update(
                        task_v,
                        advance=1,
                        detail=f"{Path(src).name} -> {Path(dst).name}",
                    )
                    if ok:
                        v_renamed += 1
                    else:
                        v_skipped += 1
                        v_failures.append((Path(src), Path(dst), reason or "unknown"))

            if v_failures:
                self.console.print(
                    "[bold yellow]Skipped/failed video renames:[/bold yellow]"
                )
                for src, dst, reason in v_failures:
                    self.console.print(
                        f"{src} -> {dst}  [yellow]SKIP[/yellow] ({reason})"
                    )


@app.command("rename")
def rename_cmd(
    root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    recurse: bool | None = typer.Option(None, "--recurse/--no-recurse"),
    zero_pad: int | None = typer.Option(None, "--zero-pad", "-z", min=3, max=10),
    apply: bool = typer.Option(False, "--apply"),
    plan: bool = typer.Option(False, "--plan"),
):
    # Interactive prompts for any missing inputs
    if root is None:
        root = prompt_existing_dir(None, "root")
    if recurse is None:
        recurse = typer.confirm("Process subdirectories?", default=True)
    if zero_pad is None:
        zero_pad = typer.prompt(
            "Digits in sequence (3-10) for BOTH images and videos", default=6, type=int
        )
    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"
    dry_run = resolve_dry_run(apply, plan)
    RenameRunner(root, recurse, zero_pad, dry_run).run()


# ----------------------
# Sort (by_date / by_location)
# ----------------------
class SortRunner:
    def __init__(
        self,
        src_root: Path,
        dst_root: Path | None,
        strategy: SortStrategy,
        dry_run: bool,
    ) -> None:
        self.src_root = src_root
        self.dst_root = dst_root
        self.strategy = strategy
        self.dry_run = dry_run
        self.console = Console()
        self.service = SortService(Path(src_root))

    def run(self) -> None:
        # Always plan first (so we can display then optionally apply)
        plan_req = SortRequest(
            src_root=self.src_root,
            dst_root=self.dst_root,
            strategy=self.strategy,
            dry_run=True,
        )
        progress, reporter = make_phase_progress(self.console)
        with progress:
            planned = self.service.plan(plan_req, reporter=reporter)

        typer.echo(f"[PLAN] strategy={self.strategy} moves={len(planned)}")
        for m in planned:
            typer.echo(f"{m.src} -> {m.dst}")

        # Offer to apply
        if planned and (
            self.dry_run or typer.confirm("Apply these moves now?", default=False)
        ):
            apply_req = SortRequest(
                src_root=self.src_root,
                dst_root=self.dst_root,
                strategy=self.strategy,
                dry_run=False,
            )
            progress2, reporter2 = make_phase_progress(self.console)
            with progress2:
                applied = self.service.apply(apply_req, reporter=reporter2)
            typer.echo(f"[APPLY] strategy={self.strategy} moved={len(applied)}")


@app.command("sort")
def sort_cmd(
    src_root: Path | None = typer.Argument(
        None, exists=False, file_okay=False, dir_okay=True
    ),
    dst_root: Path | None = typer.Option(
        None, "--dst-root", "-d", help="Destination root (default: same as source)"
    ),
    strategy: SortStrategy | None = typer.Option(
        None, "--strategy", "-s", help="by_date or by_location"
    ),
    apply: bool = typer.Option(False, "--apply", help="Execute changes"),
    plan: bool = typer.Option(False, "--plan", help="Plan only (dry-run)"),
):
    # Prompt for any missing inputs
    if src_root is None:
        src_root = prompt_existing_dir(None, "src_root")

    if strategy is None:
        choice = (
            typer.prompt("strategy (by_date/by_location)", default="by_date")
            .strip()
            .lower()
        )
        if choice not in {"by_date", "by_location"}:
            raise typer.BadParameter("strategy must be 'by_date' or 'by_location'")
        strategy = SortStrategy(choice)

    if dst_root is None:
        same = typer.confirm(
            "Sort into subfolders under the source root?", default=True
        )
        if not same:
            dst_root = prompt_existing_dir(None, "dst_root")

    if not apply and not plan:
        mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
        if mode not in {"plan", "apply"}:
            raise typer.BadParameter("option must be 'plan' or 'apply'")
        plan = mode == "plan"
        apply = mode == "apply"

    dry_run = resolve_dry_run(apply, plan)
    SortRunner(
        src_root=src_root, dst_root=dst_root, strategy=strategy, dry_run=dry_run
    ).run()
