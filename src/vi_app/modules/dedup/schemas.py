# src/vi_app/modules/dedup/schemas.py
from enum import Enum
from typing import Optional

from pydantic import BaseModel, DirectoryPath, Field


class DedupStrategy(str, Enum):
    content = "content"
    metadata = "metadata"

class DedupItem(BaseModel):
    keep: str = Field(..., example="/data/input/album/IMG_0001.jpg")
    duplicates: list[str] = Field(
        default_factory=list,
        example=[
            "/data/input/album/IMG_0001 (copy).jpg",
            "/data/input/album/IMG_0001_1.jpg",
        ],
    )
class DedupRequest(BaseModel):
    root: DirectoryPath = Field(..., example="/data/input")
    strategy: DedupStrategy = Field(DedupStrategy.content, example="content")
    move_duplicates_to: Optional[str] = Field(  # noqa: UP045
        None,
        description="Destination directory for moved duplicates when dry_run=false.",
        example="/data/output",
    )
    dry_run: bool = Field(
        True,
        description="If true, no changes are made; clusters are returned only.",
        example=True,
    )


class DedupResponse(BaseModel):
    dry_run: bool = Field(..., example=True)
    strategy: DedupStrategy = Field(..., example="content")
    clusters_count: int = Field(..., ge=0, example=3, description="Number of duplicate clusters found.")
    duplicates_count: int = Field(
        ...,
        ge=0,
        example=7,
        description="Total number of files identified as duplicates across all clusters.",
    )
    move_target: Optional[str] = Field(  # noqa: UP045
        None,
        description="Where duplicates were moved (only relevant when dry_run=false).",
        example="/data/output",
    )
    clusters: list[DedupItem] = Field(
        default_factory=list,
        description="Duplicate clusters with the chosen 'keep' and its duplicates.",
        example=[
            {
                "keep": "/data/input/album/IMG_0001.jpg",
                "duplicates": [
                    "/data/input/album/IMG_0001 (copy).jpg",
                    "/data/input/album/IMG_0001_1.jpg"
                ]
            }
        ],
    )
