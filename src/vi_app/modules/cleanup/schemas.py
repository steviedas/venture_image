from __future__ import annotations

from pydantic import BaseModel, DirectoryPath, Field


class RemoveFilesRequest(BaseModel):
    root: DirectoryPath
    patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns or substrings (case-insensitive) to match files for deletion.",
    )
    dry_run: bool = True
    remove_empty_dirs: bool = True


class RemoveFoldersRequest(BaseModel):
    root: DirectoryPath
    folder_names: list[str] = Field(
        default_factory=lambda: ["duplicate"],
        description="Exact folder names to remove.",
    )
    dry_run: bool = True


class FindMarkedDupesRequest(BaseModel):
    root: DirectoryPath
    suffix_pattern: str = r"_dupe\(\d+\)"  # your convention
