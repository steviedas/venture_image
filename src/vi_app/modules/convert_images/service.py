# src/vi_app/modules/convert_images/service.py
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageCms

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF_OK = True
except Exception:
    _HEIF_OK = False

from vi_app.core.paths import mirrored_output_path, sanitize_filename


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
            exif_bytes = im.info.get("exif")           # preserves EXIF (DateTimeOriginal, GPS, etc.)
            icc_bytes = im.info.get("icc_profile")     # preserves ICC profile if we don't re-profile

            # --- color management (convert to sRGB when possible) ---
            try:
                if "icc_profile" in im.info and im.info["icc_profile"]:
                    srgb = ImageCms.createProfile("sRGB")
                    src_profile = ImageCms.ImageCmsProfile(bytes(im.info["icc_profile"]))
                    im = ImageCms.profileToProfile(im, src_profile, srgb, outputMode="RGB")
                    # after conversion, you can choose to embed an sRGB profile; Pillow doesn't
                    # automatically add one, so we can drop the original ICC (now invalid) and
                    # let viewers assume sRGB. If you want to embed sRGB, uncomment:
                    # icc_bytes = ImageCms.ImageCmsProfile(srgb).tobytes()  # may not be available in all builds
                    icc_bytes = None  # safest: don't embed the old, now-wrong profile
            except Exception:
                # fall back to plain RGB
                pass

            # --- alpha handling ---
            if im.mode in ("RGBA", "LA") and flatten_alpha:
                bg = Image.new("RGB", im.size, (255, 255, 255))
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")

            # --- save with preserved metadata ---
            save_kwargs = {
                "format": "JPEG",
                "quality": quality,
                "optimize": True,
                "progressive": True,
            }
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc_bytes:
                save_kwargs["icc_profile"] = icc_bytes

            im.save(dst, **save_kwargs)

        return True, None
    except Exception as e:
        # If HEIC failed and plugin not loaded, give a clearer reason
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
        new_name = sanitize_filename(src.stem) + ".jpg"
        dst = mirrored_output_path(src, src_root, dst_root, new_name)
        plan.append((src, dst))
    return plan


def apply_webp_to_jpeg(
    src_root: Path,
    dst_root: Path | None,
    quality: int,
    overwrite: bool,
    flatten_alpha: bool,
    dry_run: bool,
):
    moves = plan_webp_to_jpeg(src_root, dst_root, quality, overwrite, flatten_alpha)
    results = []
    for src, dst in moves:
        converted, reason = _to_jpeg(
            src, dst, quality, overwrite, flatten_alpha, dry_run
        )
        results.append((src, dst, converted, reason))
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
        new_name = sanitize_filename(src.stem) + ".jpg"
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
