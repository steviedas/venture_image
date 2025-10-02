from enum import Enum

from pydantic import BaseModel, DirectoryPath


class DedupStrategy(str, Enum):
    content = "content"  # perceptual hash / near-duplicate
    metadata = "metadata"  # exact byte hash / same file


class DedupItem(BaseModel):
    keep: str
    duplicates: list[str]


class DedupRequest(BaseModel):
    root: DirectoryPath
    strategy: DedupStrategy = DedupStrategy.content
    move_duplicates_to: str | None = None  # e.g., "duplicate" subfolder
    dry_run: bool = True
