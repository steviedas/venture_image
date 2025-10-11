# src/vi_app/modules/convert_images/service.py
from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from PIL import Image, ImageCms

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF_OK = True
except Exception:
    _HEIF_OK = False

from vi_app.core.paths import mirrored_output_path, sanitize_filename

_SUPPORTED_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".heic",
    ".heif",
    ".gif",
}
DEFAULT_CONVERT_SUBDIR = "converted"


def _resolve_base_dst(src_root: Path, dst_root: Path | None) -> Path:
    """
    Return the destination base directory. If dst_root is None,
    use <src_root>/converted.
    """
    return (
        Path(dst_root).expanduser().resolve()
        if dst_root is not None
        else (Path(src_root).expanduser().resolve() / DEFAULT_CONVERT_SUBDIR)
    )


def enumerate_convert_targets(
    src_root: Path, dst_root: Path | None, recurse: bool
) -> list[tuple[Path, Path]]:
    src_root = Path(src_root).expanduser().resolve()
    base_dst = _resolve_base_dst(src_root, dst_root)

    files: list[Path] = []
    if recurse:
        files = [
            p
            for p in src_root.rglob("*")
            if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS
        ]
    else:
        files = [
            p
            for p in src_root.iterdir()
            if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS
        ]

    pairs: list[tuple[Path, Path]] = []
    for src in files:
        rel = src.relative_to(src_root)
        dst = (base_dst / rel).with_suffix(".jpeg")  # you already switched to .jpeg
        pairs.append((src, dst))
    return pairs


def iter_convert_folder(
    src_root: Path,
    dst_root: Path | None,
    recurse: bool,
    quality: int,
    overwrite: bool,
    flatten_alpha: bool,
    dry_run: bool,
) -> Iterator[tuple[Path, Path, bool, str | None]]:
    """
    Yield one result per file (src, dst, converted, reason). Uses the same rules as apply_convert_folder.
    """
    from .service import _to_jpeg  # reuse your existing single-file converter

    for src, dst in enumerate_convert_targets(src_root, dst_root, recurse):
        if dry_run:
            # mirror apply_convert_folder's dry-run semantics
            yield (src, dst, True, "dry_run")
            continue

        ok, reason = _to_jpeg(
            src=src,
            dst=dst,
            quality=quality,
            overwrite=overwrite,
            flatten_alpha=flatten_alpha,
            dry_run=False,
        )
        yield (src, dst, ok, reason)


def _iter_images(root: Path, recurse: bool = True) -> Iterable[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif"}
    if recurse:
        yield from (
            p for p in root.rglob("*") if p.suffix.lower() in exts and p.is_file()
        )
    else:
        yield from (
            p for p in root.iterdir() if p.suffix.lower() in exts and p.is_file()
        )


def _to_jpeg(
    src: Path,
    dst: Path,
    quality: int,
    overwrite: bool,
    flatten_alpha: bool,
    dry_run: bool,
) -> tuple[bool, str | None]:
    if dst.exists() and not overwrite:
        return False, "exists"
    if dry_run:
        return True, "dry_run"

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            # --- capture metadata BEFORE transforms ---
            exif_bytes = im.info.get("exif")  # raw EXIF
            xmp_bytes = im.info.get("xmp")  # raw XMP (requires Pillow >= 11)
            icc_bytes = im.info.get("icc_profile")  # ICC profile

            # --- color management / alpha handling (your existing code) ---
            try:
                if "icc_profile" in im.info and im.info["icc_profile"]:
                    srgb = ImageCms.createProfile("sRGB")
                    src_profile = ImageCms.ImageCmsProfile(
                        bytes(im.info["icc_profile"])
                    )
                    im = ImageCms.profileToProfile(
                        im, src_profile, srgb, outputMode="RGB"
                    )
                    # after converting to sRGB, don't embed the old profile
                    icc_bytes = None
            except Exception:
                pass

            if im.mode in ("RGBA", "LA") and flatten_alpha:
                bg = Image.new("RGB", im.size, (255, 255, 255))
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")

            # --- save with EXIF + XMP + (optional) ICC ---
            save_kwargs: dict[str, object] = {
                "format": "JPEG",
                "quality": quality,
                "optimize": True,
                "progressive": True,
            }
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if xmp_bytes:
                save_kwargs["xmp"] = (
                    xmp_bytes  # <— this preserves ratings/labels in XMP
                )
            if icc_bytes:
                save_kwargs["icc_profile"] = icc_bytes

            im.save(dst, **save_kwargs)

        return True, None
    except Exception as e:
        if src.suffix.lower() in {".heic", ".heif"} and not _HEIF_OK:
            return False, "heic_not_supported"
        return False, f"error:{e.__class__.__name__}"


def plan_webp_to_jpeg(
    src_root: Path,
    dst_root: Path | None,
    quality: int,
    overwrite: bool,
    flatten_alpha: bool,
) -> list[tuple[Path, Path]]:
    src_root = src_root.resolve()
    dst_root = (dst_root or src_root).resolve()
    plan: list[tuple[Path, Path]] = []
    for src in _iter_images(src_root, recurse=True):
        if src.suffix.lower() != ".webp":
            continue
        new_name = sanitize_filename(src.stem) + ".jpeg"
        dst = mirrored_output_path(src, src_root, dst_root, new_name)
        plan.append((src, dst))
    return plan


def apply_webp_to_jpeg(
    src_root: Path,
    dst_root: Path | None = None,
    quality: int = 100,
    overwrite: bool = False,
    flatten_alpha: bool = True,
    dry_run: bool = True,
) -> list[tuple[Path, Path, bool, str | None]]:
    src_root = Path(src_root).expanduser().resolve()
    base_dst = _resolve_base_dst(src_root, dst_root)

    results: list[tuple[Path, Path, bool, str | None]] = []
    for src in sorted(src_root.rglob("*.webp")):
        rel = src.relative_to(src_root)
        dst = (base_dst / rel).with_suffix(".jpeg")
        if dry_run:
            results.append((src, dst, True, "dry_run"))
            continue
        ok, reason = _to_jpeg(
            src=src,
            dst=dst,
            quality=quality,
            overwrite=overwrite,
            flatten_alpha=flatten_alpha,
            dry_run=False,
        )
        results.append((src, dst, ok, reason))
    return results


def plan_convert_folder(
    src_root: Path,
    dst_root: Path | None,
    recurse: bool,
    quality: int,
    overwrite: bool,
    flatten_alpha: bool,
):
    src_root = src_root.resolve()
    dst_root = (dst_root or src_root).resolve()
    plan: list[tuple[Path, Path]] = []
    for src in _iter_images(src_root, recurse=recurse):
        # already JPEG with acceptable name → still allow overwrite if asked
        new_name = sanitize_filename(src.stem) + ".jpeg"
        dst = mirrored_output_path(src, src_root, dst_root, new_name)
        plan.append((src, dst))
    return plan


def apply_convert_folder(
    src_root: Path,
    dst_root: Path | None,
    recurse: bool,
    quality: int,
    overwrite: bool,
    flatten_alpha: bool,
    dry_run: bool,
):
    moves = plan_convert_folder(
        src_root, dst_root, recurse, quality, overwrite, flatten_alpha
    )
    results = []
    for src, dst in moves:
        converted, reason = _to_jpeg(
            src, dst, quality, overwrite, flatten_alpha, dry_run
        )
        results.append((src, dst, converted, reason))
    return results
