from __future__ import annotations

from pathlib import Path
import typer

# --- dedup ---
from vi_app.modules.dedup.schemas import DedupRequest, DedupStrategy
from vi_app.modules.dedup.service import plan as dedup_plan, apply as dedup_apply

# --- cleanup ---
from vi_app.modules.cleanup.schemas import (
    RemoveFilesRequest,
    RemoveFoldersRequest,
    FindMarkedDupesRequest,
    RenameBySequenceRequest,
    SortRequest,
    SortStrategy,
)
from vi_app.modules.cleanup.service import (
    remove_files as svc_remove_files,
    remove_folders as svc_remove_folders,
    find_marked_dupes as svc_find_marked_dupes,
    rename_by_sequence as svc_rename_by_sequence,
    sort_plan,
    sort_apply,
)

# --- convert ---
from vi_app.modules.convert_images.schemas import ConvertFolderRequest, WebpToJpegRequest
from vi_app.modules.convert_images.service import apply_convert_folder, apply_webp_to_jpeg


app = typer.Typer(help="Venture Image CLI")

cleanup_app = typer.Typer(help="Cleanup endpoints")
convert_app = typer.Typer(help="Convert endpoints")
dedup_app = typer.Typer(help="Dedup endpoints")

app.add_typer(cleanup_app, name="cleanup")
app.add_typer(convert_app, name="convert")
app.add_typer(dedup_app, name="dedup")


def _resolve_dry_run(apply: bool, plan: bool) -> bool:
    """
    Standardize dry-run across commands.
    - default: dry-run (plan)
    - --apply => not dry-run
    - --plan  => force dry-run
    - both    => error
    """
    if apply and plan:
        raise typer.BadParameter("Use either --apply or --plan, not both.")
    # dry-run if not applying OR explicitly planning
    return (not apply) or plan


# =========================
# group: DEDUP (mirrors /dedup)
# =========================
@dedup_app.command("run", help="Detect duplicates (dry-run by default) or move them with --apply / plan with --plan.")
def dedup_run(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, help="Root folder to scan."),
    strategy: DedupStrategy = typer.Option(DedupStrategy.content, "--strategy", "-s", help="content|metadata"),
    move_to: Path | None = typer.Option(None, "--move-to", "-m", help="Where to move duplicates when applying."),
    apply: bool = typer.Option(False, "--apply", help="Perform moves."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = DedupRequest(
        root=root,
        strategy=strategy,
        move_duplicates_to=str(move_to) if move_to else None,
        dry_run=dry_run,
    )
    clusters = dedup_plan(req) if req.dry_run else dedup_apply(req)

    total_dups = sum(len(c.duplicates) for c in clusters)
    action = "PLAN" if req.dry_run else "APPLY"
    typer.echo(f"[{action}] strategy={strategy} clusters={len(clusters)} duplicates={total_dups}")
    for c in clusters:
        typer.echo(f" keep: {c.keep}")
        for d in c.duplicates:
            typer.echo(f"   dup: {d}")


# =========================
# group: CLEANUP (mirrors /cleanup)
# =========================
@cleanup_app.command("remove-files", help="Find and (optionally) delete files matching regex patterns.")
def cleanup_remove_files_cmd(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    pattern: list[str] = typer.Option(..., "--pattern", "-p", help="Regex pattern(s). Repeat the flag."),
    prune_empty: bool = typer.Option(True, "--prune-empty/--no-prune-empty", help="Remove now-empty dirs after delete."),
    apply: bool = typer.Option(False, "--apply", help="Delete files."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = RemoveFilesRequest(root=root, patterns=pattern, dry_run=dry_run, remove_empty_dirs=prune_empty)
    deleted = svc_remove_files(Path(req.root), req.patterns, req.dry_run, req.remove_empty_dirs)
    verb = "Would remove" if req.dry_run else "Removed"
    typer.echo(f"{verb} {len(deleted)} file(s)")
    for p in deleted:
        typer.echo(str(p))


@cleanup_app.command("remove-folders", help="Find and (optionally) remove directories by exact name.")
def cleanup_remove_folders_cmd(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    name: list[str] = typer.Option(["duplicate"], "--name", "-n", help="Folder name(s). Repeat the flag."),
    apply: bool = typer.Option(False, "--apply", help="Remove directories."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = RemoveFoldersRequest(root=root, folder_names=name, dry_run=dry_run)
    removed = svc_remove_folders(Path(req.root), req.folder_names, req.dry_run)
    verb = "Would remove" if req.dry_run else "Removed"
    typer.echo(f"{verb} {len(removed)} directorie(s)")
    for p in removed:
        typer.echo(str(p))


@cleanup_app.command("find-marked-dupes", help="List files whose filename stem matches a suffix regex (e.g., _dupe(\\d+)$).")
def cleanup_find_marked_dupes_cmd(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    suffix_pattern: str = typer.Option(r"_dupe\(\d+\)$", "--suffix", "-s", help="Regex applied to filename stem."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (read-only command)."),
):
    # This command is read-only; support --plan for consistency, but ignore its value.
    req = FindMarkedDupesRequest(root=root, suffix_pattern=suffix_pattern)
    items = svc_find_marked_dupes(Path(req.root), req.suffix_pattern)
    typer.echo(f"Found {len(items)} file(s)")
    for p in items:
        typer.echo(str(p))


@cleanup_app.command("rename", help="Per directory, rename images to IMG_XXXXXX ordered by date taken.")
def cleanup_rename_cmd(
    root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    recurse: bool = typer.Option(True, "--recurse/--no-recurse", help="Process subdirectories."),
    zero_pad: int = typer.Option(6, "--zero-pad", "-z", min=3, max=10, help="Digits in sequence."),
    apply: bool = typer.Option(False, "--apply", help="Perform renames."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = RenameBySequenceRequest(root=root, recurse=recurse, zero_pad=zero_pad, dry_run=dry_run)
    resp = svc_rename_by_sequence(req)
    verb = "Would rename" if req.dry_run else "Renamed"
    typer.echo(f"{verb} {resp.renamed_count} file(s) across {resp.groups_count} directorie(s)")
    for it in resp.items:
        typer.echo(f"{it.src} -> {it.dst}")


@cleanup_app.command("sort", help="Sort images by date or location (dry-run by default) or apply with --apply/--plan.")
def cleanup_sort_cmd(
    src_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    dst_root: Path | None = typer.Option(None, "--dst-root", "-d", help="Destination root (mirror if omitted)."),
    strategy: SortStrategy = typer.Option(SortStrategy.by_date, "--strategy", "-s", help="by_date|by_location"),
    apply: bool = typer.Option(False, "--apply", help="Perform moves."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = SortRequest(src_root=src_root, dst_root=dst_root, strategy=strategy, dry_run=dry_run)
    moves = sort_plan(req) if req.dry_run else sort_apply(req)
    action = "PLAN" if req.dry_run else "APPLY"
    typer.echo(f"[{action}] strategy={strategy} moves={len(moves)}")
    for m in moves:
        typer.echo(f"{m.src} -> {m.dst}")


# =========================
# group: CONVERT (mirrors /convert)
# =========================
@convert_app.command("folder-to-jpeg", help="Convert supported images under a folder to JPEG.")
def convert_folder_to_jpeg_cmd(
    src_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    dst_root: Path | None = typer.Option(None, "--dst-root", "-d", help="Destination root (mirror if omitted)."),
    quality: int = typer.Option(92, "--quality", "-q", min=1, max=100, help="JPEG quality."),
    overwrite: bool = typer.Option(False, "--overwrite/--no-overwrite", help="Overwrite destination if exists."),
    recurse: bool = typer.Option(True, "--recurse/--no-recurse", help="Scan subfolders."),
    flatten_alpha: bool = typer.Option(True, "--flatten-alpha/--no-flatten-alpha", help="Composite transparency to white."),
    apply: bool = typer.Option(False, "--apply", help="Perform writes."),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = ConvertFolderRequest(
        src_root=src_root,
        dst_root=dst_root,
        quality=quality,
        overwrite=overwrite,
        recurse=recurse,
        flatten_alpha=flatten_alpha,
        dry_run=dry_run,
    )
    results = apply_convert_folder(
        src_root=req.src_root,
        dst_root=req.dst_root,
        recurse=req.recurse,
        quality=req.quality,
        overwrite=req.overwrite,
        flatten_alpha=req.flatten_alpha,
        dry_run=req.dry_run,
    )
    verb = "Would convert" if req.dry_run else "Converted"
    typer.echo(f"{verb} {len(results)} file(s)")
    for src, dst, ok, reason in results:
        status = "OK" if ok else f"SKIP({reason})"
        typer.echo(f"{src} -> {dst} [{status}]")


@convert_app.command("webp-to-jpeg", help="Convert all .webp images under a folder to JPEG.")
def convert_webp_to_jpeg_cmd(
    src_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    dst_root: Path | None = typer.Option(None, "--dst-root", "-d"),
    quality: int = typer.Option(92, "--quality", "-q", min=1, max=100),
    overwrite: bool = typer.Option(False, "--overwrite/--no-overwrite"),
    flatten_alpha: bool = typer.Option(True, "--flatten-alpha/--no-flatten-alpha"),
    apply: bool = typer.Option(False, "--apply"),
    plan: bool = typer.Option(False, "--plan", help="Alias for dry-run (default)."),
):
    dry_run = _resolve_dry_run(apply, plan)
    req = WebpToJpegRequest(
        src_root=src_root,
        dst_root=dst_root,
        quality=quality,
        overwrite=overwrite,
        flatten_alpha=flatten_alpha,
        dry_run=dry_run,
    )
    results = apply_webp_to_jpeg(
        src_root=req.src_root,
        dst_root=req.dst_root,
        quality=req.quality,
        overwrite=req.overwrite,
        flatten_alpha=req.flatten_alpha,
        dry_run=req.dry_run,
    )
    verb = "Would convert" if req.dry_run else "Converted"
    typer.echo(f"{verb} {len(results)} file(s)")
    for src, dst, ok, reason in results:
        status = "OK" if ok else f"SKIP({reason})"
        typer.echo(f"{src} -> {dst} [{status}]")


if __name__ == "__main__":
    app()
