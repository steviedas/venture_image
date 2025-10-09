# src/vi_app/modules/cleanup/schemas.py
from __future__ import annotations

from pydantic import BaseModel, DirectoryPath, Field


class RemoveFilesRequest(BaseModel):
    root: DirectoryPath = Field(
        ...,
        description="Root directory to scan recursively.",
        example="/data/input",
    )
    patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Case-insensitive regular expressions matched against the FULL file path. "
            "Simple substrings work too (e.g., 'Thumbs.db'), but shell globs like '*.tmp' do NOT."
        ),
        example=[r"_dupe\(\d+\)$", r"(?i)thumbs\.db$", r"\.DS_Store$"],
    )
    dry_run: bool = Field(
        True,
        description="If true, only report what would be deleted.",
        example=True,
    )
    remove_empty_dirs: bool = Field(
        True,
        description="If true (and dry_run=false), remove now-empty directories after deletions.",
        example=True,
    )


class RemoveFilesResponse(BaseModel):
    count: int = Field(
        ...,
        ge=0,
        description="Number of files matched (and deleted if dry_run=false).",
        example=3,
    )
    paths: list[str] = Field(
        default_factory=list,
        description="Absolute paths of matched files.",
        example=[
            "/data/input/photo_dupe(1).jpg",
            "/data/input/Thumbs.db",
            "/data/input/.DS_Store",
        ],
    )
    dry_run: bool = Field(
        ...,
        description="True when no deletions were performed.",
        example=False,
    )


class RemoveFoldersRequest(BaseModel):
    root: DirectoryPath = Field(
        ...,
        description="Root directory to scan recursively.",
        example="/data/input",
    )
    folder_names: list[str] = Field(
        default_factory=lambda: ["duplicate"],
        description="Exact folder names to remove (case-insensitive match on the directory name).",
        example=["duplicate", "tmp", "@eaDir"],
    )
    dry_run: bool = Field(
        True,
        description="If true, only report which directories would be removed.",
        example=True,
    )


class RemoveFoldersResponse(BaseModel):
    count: int = Field(
        ge=0,
        description="Number of directories matched (and removed if dry_run=false).",
        example=2,
    )
    paths: list[str] = Field(
        default_factory=list,
        description="Absolute paths of matched directories.",
        example=["/data/input/duplicate", "/data/input/export/duplicate"],
    )
    dry_run: bool = Field(
        ...,
        description="True when no removals were performed.",
        example=False,
    )


class FindMarkedDupesRequest(BaseModel):
    root: DirectoryPath = Field(
        description="Root directory to scan recursively.",
        example="/data/input",
    )
    suffix_pattern: str = Field(
        r"_dupe\(\d+\)$",
        description=(
            "Regular expression applied to the filename **stem** (no extension). "
            "Files whose stem matches are considered 'marked duplicates'."
        ),
        example=r"_dupe\(\d+\)$",
    )


class FindMarkedDupesResponse(BaseModel):
    count: int = Field(
        ge=0,
        description="Number of files whose stem matched `suffix_pattern`.",
        example=3,
    )
    paths: list[str] = Field(
        default_factory=list,
        description="Absolute paths of matched files.",
        example=[
            "/data/input/album/photo_dupe(1).jpg",
            "/data/input/album/photo_dupe(2).jpg",
            "/data/input/misc/IMG_1234_dupe(3).jpeg",
        ],
    )
