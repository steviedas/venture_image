# src/vi_app/modules/convert_images/schemas.py
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, DirectoryPath, Field


class WebpToJpegRequest(BaseModel):
    src_root: DirectoryPath = Field(
        description="Root folder to scan recursively for .webp images.",
        example="/data/input",
    )
    dst_root: Optional[DirectoryPath] = Field(  # noqa: UP045
        None,
        description=(
            "Destination root for converted JPEGs. "
            "If omitted, converts alongside the source tree."
        ),
        example="/data/output",
    )
    quality: int = Field(
        100,
        ge=1,
        le=100,
        description="JPEG quality (1–100).",
        example=100,
    )
    overwrite: bool = Field(
        False,
        description="If true, overwrite existing destination files.",
        example=False,
    )
    flatten_alpha: bool = Field(
        True,
        description="If true, composite transparency onto white before saving JPEG.",
        example=True,
    )
    dry_run: bool = Field(
        True,
        description="If true, only report planned conversions (no files are written).",
        example=True,
    )


class ConvertFolderRequest(BaseModel):
    """
    Convert any supported image under src_root to JPEG,
    mirroring the directory structure under dst_root (or src_root if omitted).
    """

    src_root: DirectoryPath = Field(
        ...,
        description="Root folder to scan recursively for images.",
        example="/data/input",
    )
    dst_root: Optional[DirectoryPath] = Field(  # noqa: UP045
        None,
        description=(
            "Destination root for converted JPEGs. If omitted, writes alongside the source tree."
        ),
        example="/data/output",
    )
    quality: int = Field(
        100,
        ge=1,
        le=100,
        description="JPEG quality (1–100).",
        example=100,
    )
    overwrite: bool = Field(
        False,
        description="If true, overwrite existing destination files.",
        example=False,
    )
    recurse: bool = Field(
        True,
        description="If true, scan subfolders recursively; otherwise only the top-level directory.",
        example=True,
    )
    flatten_alpha: bool = Field(
        True,
        description="If true, composite transparency onto white before saving JPEG.",
        example=True,
    )
    dry_run: bool = Field(
        True,
        description="If true, only report planned conversions (no files are written).",
        example=True,
    )


class ConversionResult(BaseModel):
    src: str = Field(
        ...,
        description="Absolute path of the source image.",
        example="/data/input/album/pic.webp",
    )
    dst: str = Field(
        ...,
        description="Absolute path where the JPEG is (or would be) written.",
        example="/data/output/album/pic.jpg",
    )
    converted: bool = Field(
        ...,
        description=(
            "True if the file was converted (or would be, when dry_run=true). "
            "False if it was skipped."
        ),
        example=True,
    )
    reason: Optional[str] = Field(  # noqa: UP045
        None,
        description=(
            "Why a file was skipped or the status. Common values: "
            "`exists` (destination exists and overwrite=false), "
            "`dry_run` (no changes performed), "
            "`heic_not_supported` (if HEIC/HEIF plugin isn’t available), "
            "`error:<ExceptionName>` (unexpected error). "
            "Null when conversion succeeded."
        ),
        example=None,
    )
