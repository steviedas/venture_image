# src/vi_app/core/media_types.py
from __future__ import annotations

# Broaden to cover “all common formats”
IMAGE_EXTS: set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
    ".raw",
    ".dng",
    ".arw",
    ".cr2",
    ".nef",
    ".orf",
    ".rw2",
}

VIDEO_EXTS: set[str] = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".wmv",
    ".flv",
    ".webm",
    ".mts",
    ".m2ts",
    ".ts",
    ".3gp",
    ".3g2",
}
