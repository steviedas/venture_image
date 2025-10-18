# src\vi_app\commands\common.py
from __future__ import annotations

from pathlib import Path

import typer


def resolve_dry_run(apply: bool, plan: bool) -> bool:
    """
    Standardize dry-run across commands.
    - default: dry-run (plan)
    - --apply => not dry-run
    - --plan  => force dry-run
    - both    => error
    """
    if apply and plan:
        raise typer.BadParameter("Use either --apply or --plan, not both.")
    return (not apply) or plan


def prompt_existing_dir(maybe_root: Path | None, prompt_label: str = "root") -> Path:
    root = maybe_root or Path(typer.prompt(f"{prompt_label} (folder)")).expanduser()
    if not root.exists() or not root.is_dir():
        raise typer.BadParameter(
            f"{prompt_label} does not exist or is not a directory: {root}"
        )
    return root
