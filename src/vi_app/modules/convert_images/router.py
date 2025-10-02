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


@router.post("/webp-to-jpeg", response_model=list[ConversionResult])
def webp_to_jpeg(req: WebpToJpegRequest):
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


@router.post("/folder-to-jpeg", response_model=list[ConversionResult])
def folder_to_jpeg(req: ConvertFolderRequest):
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
