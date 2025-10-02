from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from vi_app.core.errors import BadRequest
from vi_app.core.paths import ensure_within_root


def _iter_files(root: Path) -> Iterable[Path]:
    return (p for p in root.rglob("*") if p.is_file())


def _iter_dirs(root: Path) -> Iterable[Path]:
    # bottom-up to remove empty dirs safely
    yield from sorted(
        (d for d in root.rglob("*") if d.is_dir()),
        key=lambda x: len(x.parts),
        reverse=True,
    )


def remove_files(
    root: Path, patterns: list[str], dry_run: bool, remove_empty_dirs: bool
) -> list[Path]:
    if not patterns:
        raise BadRequest("At least one pattern is required.")

    root = root.resolve()
    # Compile substrings to case-insensitive regexes or accept globs
    regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
    to_delete: list[Path] = []

    for f in _iter_files(root):
        s = str(f)
        if any(r.search(s) for r in regexes):
            to_delete.append(f)

    if not dry_run:
        for f in to_delete:
            ensure_within_root(f, root)
            try:
                f.unlink(missing_ok=True)
            except Exception:
                # continue best-effort; could log
                pass

        if remove_empty_dirs:
            for d in _iter_dirs(root):
                if not any(d.iterdir()):
                    try:
                        d.rmdir()
                    except Exception:
                        pass

    return to_delete


def remove_folders(root: Path, folder_names: list[str], dry_run: bool) -> list[Path]:
    if not folder_names:
        raise BadRequest("At least one folder name is required.")

    root = root.resolve()
    targets = []
    names_lower = {n.lower() for n in folder_names}

    for d in _iter_dirs(root):
        if d.name.lower() in names_lower:
            targets.append(d)

    if not dry_run:
        for d in targets:
            ensure_within_root(d, root)
            # remove tree
            for p in sorted(d.rglob("*"), key=lambda x: len(x.parts), reverse=True):
                if p.is_file():
                    p.unlink(missing_ok=True)
                else:
                    p.rmdir()
            d.rmdir()

    return targets


def find_marked_dupes(root: Path, suffix_regex: str) -> list[Path]:
    root = root.resolve()
    rx = re.compile(suffix_regex, re.IGNORECASE)
    return [p for p in _iter_files(root) if rx.search(p.stem)]
