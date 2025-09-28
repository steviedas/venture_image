#!/usr/bin/env python3
"""
Recursively find (and optionally delete) files that match ANY of the patterns in FILES_TO_REMOVE.

- Patterns can be exact names ("cover.jpg") or globs ("*.webp", "**/cover.jpg").
- If a pattern contains a path separator ("/" or "\\"), it is matched against the
  file's RELATIVE PATH from PATH_TO_PROCESS. Otherwise it's matched against the basename only.

Edit the constants below, then run:  python bulk_remove_files.py
"""

from __future__ import annotations

import os
import sys
import fnmatch
from pathlib import Path
from typing import Iterable

# ====== EDIT THESE ======
# root folder to scan
PATH_TO_PROCESS   = r"C:\Users\stevi\Desktop\test"
FILES_TO_REMOVE   = [
    # exact filename
    "photography.jpg",
    # "portfolio-screenshot-short-2x.jpg",
    # "portfolio-screenshot-short.jpg",
    # "pro-profile-banner-background-2x.jpg",
    # "pro-profile-banner-background.jpg",
    # "pro-profile-banner-large-overlay-2x.jpg",
    # "pro-profile-banner-large-overlay.jpg",
    # "pro-profile-banner-medium-overlay-2x.jpg",
    # "pro-profile-banner-medium-overlay.jpg",
    # "pro_gift_30_days_modal_bg_1x.jpg",
    # "pro_gift_30_days_modal_bg_2x.jpg",
    # "fashion.jpg",
    # "favicon.jpg",
    # "e690af228046875.Y3JvcCwzMzcyLDI2MzgsMCww.jpg",
    # "e690af228046875.Y3JvcCwzMzcyLDI2MzgsMCww_1.jpg",
    # "e1aeb1228046629.Y3JvcCw0MzExLDMzNzIsMjEsMA.jpg",
    # "e1aeb1228046629.Y3JvcCw0MzExLDMzNzIsMjEsMA_1.jpg",
    # "apple-touch-icon.jpg",
    # "847075234009431.Y3JvcCwzNjQ4LDI4NTMsMCwxMjgy.jpg",
    # "847075234009431.Y3JvcCwzNjQ4LDI4NTMsMCwxMjgy_1.jpg",
    # "847075234009431.Y3JvcCwzNjQ4LDI4NTMsMCwxMjgy_2.jpg",
    # "847075234009431.Y3JvcCwzNjQ4LDI4NTMsMCwxMjgy_3.jpg",
    # "847075234009431.Y3JvcCwzNjQ4LDI4NTMsMCwxMjgy_4.jpg",
    # "796476232682037.Y3JvcCwzMTUxLDI0NjQsMCwyNDE.jpg",
    # "796476232682037.Y3JvcCwzMTUxLDI0NjQsMCwyNDE_1.jpg",
    # "693231227813339.Y3JvcCwxNDAwLDEwOTUsMCwzMjk.jpg",
    # "693231227813339.Y3JvcCwxNDAwLDEwOTUsMCwzMjk_1.jpg",
    # "494c22235175761.Y3JvcCwzNTU5LDI3ODMsMCwxMDc0.jpg",
    # "494c22235175761.Y3JvcCwzNTU5LDI3ODMsMCwxMDc0_1.jpg",
    # "494c22235175761.Y3JvcCwzNTU5LDI3ODMsMCwxMDc0_2.jpg",
    # "494c22235175761.Y3JvcCwzNTU5LDI3ODMsMCwxMDc0_3.jpg",
    # "494c22235175761.Y3JvcCwzNTU5LDI3ODMsMCwxMDc0_4.jpg",
    # "384c5b232813603.Y3JvcCwzMzI2LDI2MDEsMCw3NTc.jpg",
    # "384c5b232813603.Y3JvcCwzMzI2LDI2MDEsMCw3NTc_1.jpg",
    # "115_*.jpg",
    # "95d6f4234861281.Y3JvcCwyMjY4LDE3NzMsMCwyNTI.jpg",
    # "95d6f4234861281.Y3JvcCwyMjY4LDE3NzMsMCwyNTI_1.jpg",
    # "95d6f4234861281.Y3JvcCwyMjY4LDE3NzMsMCwyNTI_2.jpg",
    # "95d6f4234861281.Y3JvcCwyMjY4LDE3NzMsMCwyNTI_3.jpg",
    # "95d6f4234861281.Y3JvcCwyMjY4LDE3NzMsMCwyNTI_4.jpg",
    # "80dd2b235255275.Y3JvcCwyMTU4LDE2ODcsMCw0NDg.jpg",
    # "80dd2b235255275.Y3JvcCwyMTU4LDE2ODcsMCw0NDg_1.jpg",
    # "80dd2b235255275.Y3JvcCwyMTU4LDE2ODcsMCw0NDg_2.jpg",
    # "80dd2b235255275.Y3JvcCwyMTU4LDE2ODcsMCw0NDg_3.jpg",
    # "80dd2b235255275.Y3JvcCwyMTU4LDE2ODcsMCw0NDg_4.jpg",
    # "60a6ad227812477.Y3JvcCwxNDAwLDEwOTUsMCwyNDI.jpg",
    # "60a6ad227812477.Y3JvcCwxNDAwLDEwOTUsMCwyNDI_1.jpg",
    # "0bec2d233783765.Y3JvcCwzNjQ4LDI4NTMsMCwxMzA5.jpg",
    # "0bec2d233783765.Y3JvcCwzNjQ4LDI4NTMsMCwxMzA5_1.jpg",
    # "0bec2d233783765.Y3JvcCwzNjQ4LDI4NTMsMCwxMzA5_2.jpg",
    # "0bec2d233783765.Y3JvcCwzNjQ4LDI4NTMsMCwxMzA5_3.jpg",
    # "0bec2d233783765.Y3JvcCwzNjQ4LDI4NTMsMCwxMzA5_4.jpg",
    # "100.jpg",
    # "115.jpg",
    # "fsahion.jpg",
    # "fashion_1.jpg",
    # "fashion_2x.jpg",
    # "1f9fdd232734307.Y3JvcCwzMzI4LDI2MDMsMCw2NTA.jpg",
    # "1f9fdd232734307.Y3JvcCwzMzI4LDI2MDMsMCw2NTA_1.jpg",
    # any WEBP in any folder (basename match)
    # "*.webp",
    # match relative path (works on mac exports)
    # "*/.DS_Store",
    # match anywhere in tree
    # "**/Thumbs.db",
]

CASE_INSENSITIVE  = True       # case-insensitive matching
DRY_RUN           = False       # True: only list matches; False: delete them
REMOVE_EMPTY_DIRS = False      # after deletions, remove any newly empty directories
# ========================


# ----- lightweight coloured logger -----
_ENABLE_COLOR = os.environ.get("NO_COLOR", "").lower() not in ("1", "true", "yes")
try:
    if os.name == "nt" and _ENABLE_COLOR:
        import colorama  # type: ignore
        colorama.just_fix_windows_console()
except Exception:
    pass

def _c(code: str) -> str:
    return code if _ENABLE_COLOR else ""

RESET = _c("\033[0m")
RED   = _c("\033[31m")
GREEN = _c("\033[32m")
YEL   = _c("\033[33m")

def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")

def log_ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}" if _ENABLE_COLOR else f"[OK] {msg}")

def log_warn(msg: str) -> None:
    print(f"{YEL}[WARN]{RESET} {msg}" if _ENABLE_COLOR else f"[WARN] {msg}", file=sys.stderr)

def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{RESET} {msg}" if _ENABLE_COLOR else f"[ERROR] {msg}", file=sys.stderr)
# --------------------------------------


def _safe_dir(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Root not found or not a directory: {root}")
    # Extra safety: avoid deleting from drive root by mistake (when DRY_RUN=False)
    if not DRY_RUN and len(root.parts) <= 2:
        raise SystemExit(f"Refusing to delete from very short/unsafe path: {root!r}. Use DRY_RUN first.")


def _norm(s: str) -> str:
    return s.lower() if CASE_INSENSITIVE else s


def _has_sep(pat: str) -> bool:
    return ("/" in pat) or ("\\" in pat)


def _compile_matchers(root: Path):
    """
    Build a predicate that checks if a given file path matches ANY of the patterns.
    - If a pattern contains a path separator, match it against RELATIVE PATH from root (posix form).
    - Otherwise, match against the BASENAME only.
    """
    if not FILES_TO_REMOVE:
        raise SystemExit("FILES_TO_REMOVE is empty; nothing to match.")

    # Normalize patterns (case & path style)
    compiled: list[tuple[bool, str]] = []  # (match_relpath, normalized_pattern)
    for pat in FILES_TO_REMOVE:
        if not isinstance(pat, str) or not pat.strip():
            continue
        pat = pat.strip()
        # Convert Windows-style backslashes to forward slashes for consistent matching
        pat_norm = pat.replace("\\", "/")
        pat_norm = _norm(pat_norm)
        compiled.append((_has_sep(pat), pat_norm))

    def matches(path: Path) -> bool:
        # Relative POSIX path from root
        rel_posix = path.relative_to(root).as_posix()
        base = path.name
        rel_cmp = _norm(rel_posix)
        base_cmp = _norm(base)
        for use_rel, pat in compiled:
            target = rel_cmp if use_rel else base_cmp
            # fnmatch is case-sensitive; we've normalized case if needed
            if fnmatch.fnmatchcase(target, pat):
                return True
        # Also support exact-name equality for any plain names supplied without wildcards
        # (fnmatch handles it too, but this is cheap and explicit)
        return False

    return matches


def _iter_files(root: Path) -> Iterable[Path]:
    """Yield all files under root (recursive)."""
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _remove_empty_dirs(root: Path) -> int:
    """Remove empty directories under root. Returns count removed."""
    removed = 0
    # Walk deepest-first so we try to remove children before parents
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda x: len(x.parts), reverse=True):
        try:
            if not any(d.iterdir()):
                d.rmdir()
                removed += 1
                log_ok(f"Removed empty dir: {d}")
        except Exception as e:
            log_warn(f"Could not remove dir {d}: {e}")
    return removed


def main() -> None:
    root = Path(PATH_TO_PROCESS).expanduser().resolve()
    _safe_dir(root)

    log_info(f"Scanning: {root}")
    log_info(f"Case-insensitive: {CASE_INSENSITIVE}")
    log_info(f"Patterns ({len(FILES_TO_REMOVE)}): {FILES_TO_REMOVE}")
    log_warn("DRY RUN: no files will be deleted.") if DRY_RUN else log_warn("LIVE RUN: matching files WILL be deleted!")

    matches_pred = _compile_matchers(root)

    # Collect matches (deduplicated by resolved path)
    seen: set[Path] = set()
    matches: list[Path] = []
    for f in _iter_files(root):
        try:
            rp = f.resolve()
        except Exception:
            rp = f
        if rp in seen:
            continue
        if matches_pred(rp):
            seen.add(rp)
            matches.append(rp)

    if not matches:
        log_info("No matching files found.")
        return

    log_info(f"Found {len(matches)} match(es).")
    deleted = 0
    for f in matches:
        if DRY_RUN:
            log_info(f"[match] {f}")
            continue
        try:
            f.unlink()
            deleted += 1
            log_ok(f"Deleted: {f}")
        except Exception as e:
            log_error(f"Failed to delete {f}: {e}")

    if not DRY_RUN and REMOVE_EMPTY_DIRS:
        removed_dirs = _remove_empty_dirs(root)
        log_info(f"Removed {removed_dirs} empty directorie(s).")

    if DRY_RUN:
        log_info("Dry run complete. Set DRY_RUN = False to delete these files.")
    else:
        log_info(f"Done. Deleted {deleted} file(s).")


if __name__ == "__main__":
    main()
