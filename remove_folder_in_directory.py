from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path
from typing import List

# ====== EDIT THESE ======
PATH_TO_PROCESS  = r"C:\Users\stevi\Desktop\dedup_1"
DIRECTORY_NAME   = "duplicate"   # exact folder name to remove
CASE_INSENSITIVE = True          # treat names like 'Duplicate'/'DUPLICATE' as matches
DRY_RUN          = False          # True = preview only; False = actually delete
# ========================


# ----- lightweight coloured logger -----
_ENABLE_COLOR = os.environ.get("NO_COLOR", "").lower() not in {"1", "true", "yes"}
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


def main() -> None:
    root = Path(PATH_TO_PROCESS).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        log_error(f"Root not found or not a directory: {root}")
        sys.exit(1)

    target_name = DIRECTORY_NAME.strip()
    if not target_name:
        log_error("DIRECTORY_NAME cannot be empty.")
        sys.exit(1)

    # Safety: only allow a simple directory name (no path separators)
    if any(sep in target_name for sep in ("/", "\\")):
        log_error("DIRECTORY_NAME must be a simple folder name (no slashes).")
        sys.exit(1)

    log_info(f"Root: {root}")
    log_info(f"Target folder name: {target_name!r} (case-insensitive: {CASE_INSENSITIVE})")
    log_warn("DRY RUN: no directories will be deleted.") if DRY_RUN else log_warn("LIVE RUN: matching directories WILL be deleted!")

    norm = (lambda s: s.lower()) if CASE_INSENSITIVE else (lambda s: s)
    target_norm = norm(target_name)

    # Collect matches first (so we don't mutate while walking)
    matches: List[Path] = []
    for dirpath, dirnames, _ in os.walk(root):
        # We don't prune here so we can still find nested matches;
        # just collect any subdir whose name matches.
        for d in dirnames:
            if norm(d) == target_norm:
                matches.append(Path(dirpath) / d)

    if not matches:
        log_info("No matching directories found.")
        return

    log_info(f"Found {len(matches)} matching directorie(s).")
    deleted = 0
    for d in matches:
        if DRY_RUN:
            log_info(f"[match] {d}")
            continue
        try:
            shutil.rmtree(d)
            deleted += 1
            log_ok(f"Deleted: {d}")
        except Exception as e:
            log_error(f"Failed to delete {d}: {e}")

    if DRY_RUN:
        log_info("Dry run complete. Set DRY_RUN = False to delete these directories.")
    else:
        log_info(f"Done. Deleted {deleted} directorie(s).")


if __name__ == "__main__":
    main()
