from __future__ import annotations

import re
from pathlib import Path

SAFE_NAME_RE = re.compile(r"[^\w\-. ]+", re.UNICODE)


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """
    Remove risky chars but preserve useful ones (., -, _, space).
    """
    name = SAFE_NAME_RE.sub(replacement, name)
    # collapse repeats of replacement
    name = re.sub(rf"{re.escape(replacement)}+", replacement, name)
    return name.strip(" ._")


def ensure_within_root(candidate: Path, root: Path) -> Path:
    """
    Guardrail: resolve and ensure `candidate` is under `root`.
    """
    candidate = candidate.resolve()
    root = root.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError(f"{candidate} is outside of root {root}")
    return candidate


def mirrored_output_path(
    src: Path, src_root: Path, dst_root: Path, new_name: str | None = None
) -> Path:
    """
    Build a destination path that mirrors src's relative structure under a new root.
    Optionally replace the filename with `new_name`.
    """
    src = src.resolve()
    src_root = src_root.resolve()
    dst_root = dst_root.resolve()
    ensure_within_root(src, src_root)
    rel = src.relative_to(src_root)
    if new_name:
        rel = rel.with_name(new_name)
    return (dst_root / rel).resolve()
