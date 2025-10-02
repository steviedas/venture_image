from __future__ import annotations

from pydantic import BaseModel, DirectoryPath, Field


class WebpToJpegRequest(BaseModel):
    src_root: DirectoryPath
    dst_root: DirectoryPath | None = None
    quality: int = Field(default=92, ge=1, le=100)
    overwrite: bool = False
    flatten_alpha: bool = True  # compose transparent onto white background
    dry_run: bool = True


class ConvertFolderRequest(BaseModel):
    """
    Generic folder converter (any readable image -> JPEG).
    """

    src_root: DirectoryPath
    dst_root: DirectoryPath | None = None
    quality: int = Field(default=92, ge=1, le=100)
    overwrite: bool = False
    recurse: bool = True
    flatten_alpha: bool = True
    dry_run: bool = True


class ConversionResult(BaseModel):
    src: str
    dst: str
    converted: bool
    reason: str | None = None
