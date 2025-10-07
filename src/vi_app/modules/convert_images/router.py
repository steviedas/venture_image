from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from vi_app.core.errors import to_http

from .schemas import ConversionResult, ConvertFolderRequest, WebpToJpegRequest
from .service import (
    apply_convert_folder,
    apply_webp_to_jpeg,
)

router = APIRouter(prefix="/convert", tags=["convert"])


@router.post(
    path="/webp-to-jpeg",
    response_model=list[ConversionResult],
    summary="Convert all .webp images under a folder to JPEG",
    description=(
        "Recursively scans `src_root` for `.webp` images and converts them to JPEG, "
        "mirroring the directory structure under `dst_root` (or `src_root` if omitted). "
        "Respects `overwrite` (skip when destination exists unless true), "
        "and `flatten_alpha` (composite transparency onto white). "
        "When `dry_run` is true, no files are written—only the planned results are returned."
    ),
)
def webp_to_jpeg(req: WebpToJpegRequest) -> list[ConversionResult]:
    try:
        results = apply_webp_to_jpeg(
            Path(req.src_root),
            Path(req.dst_root) if req.dst_root else None,
            req.quality,
            req.overwrite,
            req.flatten_alpha,
            req.dry_run,
        )
        return [
            ConversionResult(src=str(src), dst=str(dst), converted=ok, reason=reason)
            for src, dst, ok, reason in results
        ]
    except Exception as err:
        raise to_http(err) from err


@router.post(
    path="/folder-to-jpeg",
    response_model=list[ConversionResult],
    summary="Convert all supported images in a folder to JPEG",
    description=(
        "Scans `src_root` for supported formats (e.g., PNG, WEBP, TIFF, HEIC/HEIF*) and converts "
        "each to JPEG, mirroring the source directory structure under `dst_root` (or `src_root` if omitted). "
        "Honors `overwrite` (skip when destination exists unless true), `recurse` (include subfolders), and "
        "`flatten_alpha` (composite transparency onto white). When `dry_run` is true, no files are written—"
        "the endpoint returns the planned results only.\n\n"
        "*HEIC/HEIF conversion requires the `pillow-heif` plugin to be available in the environment."
    ),
)
def folder_to_jpeg(req: ConvertFolderRequest) -> list[ConversionResult]:
    try:
        results = apply_convert_folder(
            Path(req.src_root),
            Path(req.dst_root) if req.dst_root else None,
            req.recurse,
            req.quality,
            req.overwrite,
            req.flatten_alpha,
            req.dry_run,
        )
        return [
            ConversionResult(src=str(src), dst=str(dst), converted=ok, reason=reason)
            for src, dst, ok, reason in results
        ]
    except Exception as err:
        raise to_http(err) from err
