# src/vi_app/modules/cleanup/schemas.py
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, DirectoryPath, Field


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


class SortStrategy(str, Enum):
    by_date = "by_date"
    by_location = "by_location"


class MoveItem(BaseModel):
    src: str = Field(..., example="/data/input/album/IMG_0001.HEIC")
    dst: str = Field(..., example="/data/output/2023/07/IMG_0001.jpg")


class SortRequest(BaseModel):
    src_root: DirectoryPath = Field(
        ...,
        description="Root directory to scan for images.",
        example="/data/input",
    )
    dst_root: DirectoryPath | None = Field(
        None,
        description="Destination root. If omitted, sorting is mirrored under `src_root`.",
        example="/data/output",
    )
    strategy: SortStrategy = Field(
        SortStrategy.by_date,
        description="Sorting strategy to apply.",
        example="by_date",
    )
    dry_run: bool = Field(
        True,
        description="If true, only report planned moves (no files changed).",
        example=True,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "src_root": "/data/input",
                    "dst_root": "/data/output",
                    "strategy": "by_date",
                    "dry_run": True,
                }
            ]
        }
    )


class SortResponse(BaseModel):
    dry_run: bool = Field(..., example=True)
    strategy: SortStrategy = Field(..., example="by_date")
    moves_count: int = Field(
        ...,
        ge=0,
        description="Number of planned/applied moves.",
        example=42,
    )
    moves: list[MoveItem] = Field(
        default_factory=list,
        description="Planned/applied moves as (src,dst) pairs.",
        example=[
            {
                "src": "/data/input/album/IMG_0001.HEIC",
                "dst": "/data/output/2023/07/IMG_0001.jpg",
            }
        ],
    )


class RenamedItem(BaseModel):
    src: str = Field(..., example="/data/input/album/DSC_0123.JPG")
    dst: str = Field(..., example="/data/input/album/IMG_000001.JPG")


class RenameBySequenceRequest(BaseModel):
    root: DirectoryPath = Field(
        ...,
        description="Top-level directory. The operation applies to this directory and all sub-directories.",
        example="/data/input",
    )
    recurse: bool = Field(
        True,
        description="If true, process sub-directories; the sequence resets **per** directory.",
        example=True,
    )
    zero_pad: int = Field(
        6,
        ge=3,
        le=10,
        description="Number of digits in the sequence (IMG_000001).",
        example=6,
    )
    dry_run: bool = Field(
        True,
        description="If true, only report the planned renames.",
        example=True,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"root": "/data/input", "recurse": True, "zero_pad": 6, "dry_run": True}
            ]
        }
    )


class RenameBySequenceResponse(BaseModel):
    dry_run: bool = Field(..., example=True)
    groups_count: int = Field(
        ...,
        ge=0,
        description="Number of directories that contained at least one renamable image.",
        example=12,
    )
    files_count: int = Field(
        ...,
        ge=0,
        description="Total number of files considered across those directories.",
        example=312,
    )
    renamed_count: int = Field(
        ...,
        ge=0,
        description="Number of files that would be (or were) renamed.",
        example=312,
    )
    items: list[RenamedItem] = Field(
        default_factory=list,
        description="Planned/applied renames as (src → dst) pairs.",
        example=[
            {
                "src": "/data/input/album/DSC_0123.JPG",
                "dst": "/data/input/album/IMG_000001.JPG",
            },
            {
                "src": "/data/input/album/DSC_0124.JPG",
                "dst": "/data/input/album/IMG_000002.JPG",
            },
        ],
    )
