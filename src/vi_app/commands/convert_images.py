# src\vi_app\commands\convert_images.py
from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vi_app.commands.common import resolve_dry_run
from vi_app.core.rich_progress import make_phase_progress
from vi_app.modules.convert.service import ConvertService

app = typer.Typer(help="Convert images to JPEG")


# ---------- base runner ----------
class _ConvertRunner:
    def __init__(
        self,
        src_root: Path,
        dst_root: Path | None,
        recurse: bool,
        quality: int,
        overwrite: bool,
        flatten_alpha: bool,
        only_exts: set[str] | None,
        dry_run: bool,
    ) -> None:
        self.src_root = src_root
        self.dst_root = dst_root
        self.recurse = recurse
        self.quality = quality
        self.overwrite = overwrite
        self.flatten_alpha = flatten_alpha
        self.only_exts = only_exts
        self.dry_run = dry_run
        self.console = Console()

    def _build_service(self) -> ConvertService:
        return ConvertService(
            src_root=self.src_root,
            dst_root=self.dst_root,
            recurse=self.recurse,
            quality=self.quality,
            overwrite=self.overwrite,
            flatten_alpha=self.flatten_alpha,
            only_exts=self.only_exts,
            dry_run=self.dry_run,
        )

    def run(self) -> None:
        svc = self._build_service()

        # Always plan first for "apply now?" UX
        progress, reporter = make_phase_progress(self.console)
        with progress:
            pairs = svc.plan(reporter=reporter)
        total = len(pairs)
        if total == 0:
            typer.echo("No convertible images found.")
            return

        # Show the plan
        for src, dst in pairs:
            typer.echo(f"{src} -> {dst}")
        typer.echo(f"[PLAN] Would convert {total} file(s).")

        # If user requested plan, offer to apply now
        do_apply = (not self.dry_run) or typer.confirm(
            "Apply these conversions now?", default=False
        )
        if not do_apply:
            return

        # APPLY (with progress)
        # Ensure service is set to non-dry-run if originally planned
        if self.dry_run:
            svc = ConvertService(
                src_root=self.src_root,
                dst_root=self.dst_root,
                recurse=self.recurse,
                quality=self.quality,
                overwrite=self.overwrite,
                flatten_alpha=self.flatten_alpha,
                only_exts=self.only_exts,
                dry_run=False,
            )

        progress2, reporter2 = make_phase_progress(self.console)
        t0 = time.perf_counter()
        with progress2:
            results = svc.apply(reporter=reporter2)

        converted = sum(1 for _s, _d, ok, _r in results if ok)
        skipped = total - converted
        elapsed = time.perf_counter() - t0
        rate = total / elapsed if elapsed > 0 else 0.0

        # Print skipped table if any
        skipped_rows = [(s, r) for s, d, ok, r in results if not ok]
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
    """Attach image conversion commands to the given Typer app."""

    @app.command(
        "folder-to-jpeg", help="Convert supported images under a folder to JPEG."
    )
    def convert_folder_to_jpeg_cmd(
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
        plan: bool = typer.Option(False, "--plan", help="Plan only (default)."),
    ):
        # Interactive prompts
        if src_root is None:
            src_root = Path(typer.prompt("src (folder to scan)")).expanduser()
        if not src_root.exists() or not src_root.is_dir():
            raise typer.BadParameter(
                f"src_root does not exist or is not a directory: {src_root}"
            )

        if dst_root is None:
            dst_str = typer.prompt(
                "dst (destination root; Enter = default '<src>/converted')", default=""
            )
            dst_root = Path(dst_str).expanduser() if dst_str else None

        if quality is None:
            quality = typer.prompt("quality (1-100)", default=100, type=int)
            if not (1 <= quality <= 100):
                raise typer.BadParameter("quality must be 1..100")

        if overwrite is None:
            overwrite = typer.confirm(
                "overwrite destination files if they already exist?", default=False
            )

        if recurse is None:
            recurse = typer.confirm("recurse into subfolders?", default=True)

        if flatten_alpha is None:
            flatten_alpha = typer.confirm(
                "flatten alpha (composite transparency to white)?", default=True
            )

        if not apply and not plan:
            mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
            if mode not in {"plan", "apply"}:
                raise typer.BadParameter("option must be 'plan' or 'apply'")
            plan, apply = (mode == "plan"), (mode == "apply")

        dry_run = resolve_dry_run(apply, plan)
        _ConvertRunner(
            src_root=src_root,
            dst_root=dst_root,
            recurse=recurse,
            quality=quality,
            overwrite=overwrite,
            flatten_alpha=flatten_alpha,
            only_exts=None,
            dry_run=dry_run,
        ).run()

    @app.command(
        "webp-to-jpeg", help="Convert all .webp images under a folder to JPEG."
    )
    def convert_webp_to_jpeg_cmd(
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
        plan: bool = typer.Option(False, "--plan", help="Plan only (default)."),
    ):
        if src_root is None:
            src_root = Path(typer.prompt("src (folder to scan)")).expanduser()
        if not src_root.exists() or not src_root.is_dir():
            raise typer.BadParameter(
                f"src_root does not exist or is not a directory: {src_root}"
            )

        if dst_root is None:
            dst_str = typer.prompt(
                "dst (destination root; Enter = default '<src>/converted')", default=""
            )
            dst_root = Path(dst_str).expanduser() if dst_str else None

        if quality is None:
            quality = typer.prompt("quality (1-100)", default=100, type=int)
            if not (1 <= quality <= 100):
                raise typer.BadParameter("quality must be 1..100")

        if overwrite is None:
            overwrite = typer.confirm(
                "overwrite destination files if they already exist?", default=False
            )

        if flatten_alpha is None:
            flatten_alpha = typer.confirm(
                "flatten alpha (composite transparency to white)?", default=True
            )

        if not apply and not plan:
            mode = typer.prompt("option (plan/apply)", default="plan").strip().lower()
            if mode not in {"plan", "apply"}:
                raise typer.BadParameter("option must be 'plan' or 'apply'")
            plan, apply = (mode == "plan"), (mode == "apply")

        dry_run = resolve_dry_run(apply, plan)
        _ConvertRunner(
            src_root=src_root,
            dst_root=dst_root,
            recurse=True,  # recursive by design
            quality=quality,
            overwrite=overwrite,
            flatten_alpha=flatten_alpha,
            only_exts={".webp"},  # restrict to webp
            dry_run=dry_run,
        ).run()
