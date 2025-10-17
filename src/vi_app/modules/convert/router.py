# src/vi_app/modules/convert/router.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from vi_app.core.errors import to_http

from .schemas import ConversionResult, ConvertFolderRequest, WebpToJpegRequest
from .service import (
    ConvertService,
)

router = APIRouter(prefix="/convert", tags=["convert"])


@router.post(
    path="/webp-to-jpeg",
    response_model=list[ConversionResult],
    summary="Convert all .webp images under a folder to JPEG",
)
def webp_to_jpeg(req: WebpToJpegRequest) -> list[ConversionResult]:
    try:
        svc = ConvertService(
            src_root=Path(req.src_root),
            dst_root=Path(req.dst_root) if req.dst_root else None,
            recurse=True,
            quality=req.quality,
            overwrite=req.overwrite,
            flatten_alpha=req.flatten_alpha,
            only_exts={".webp"},
            dry_run=req.dry_run,
        )
        targets = svc.enumerate_targets()
        results = (
            [(s, d, True, "dry_run") for s, d in targets]
            if req.dry_run
            else list(svc.iter_apply(targets=targets))
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
)
def folder_to_jpeg(req: ConvertFolderRequest) -> list[ConversionResult]:
    try:
        svc = ConvertService(
            src_root=Path(req.src_root),
            dst_root=Path(req.dst_root) if req.dst_root else None,
            recurse=req.recurse,
            quality=req.quality,
            overwrite=req.overwrite,
            flatten_alpha=req.flatten_alpha,
            only_exts=None,
            dry_run=req.dry_run,
        )
        targets = svc.enumerate_targets()
        results = (
            [(s, d, True, "dry_run") for s, d in targets]
            if req.dry_run
            else list(svc.iter_apply(targets=targets))
        )
        return [
            ConversionResult(src=str(src), dst=str(dst), converted=ok, reason=reason)
            for src, dst, ok, reason in results
        ]
    except Exception as err:
        raise to_http(err) from err
