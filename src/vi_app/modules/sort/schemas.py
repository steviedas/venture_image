from enum import Enum

from pydantic import BaseModel, DirectoryPath


class SortStrategy(str, Enum):
    date = "date"
    location = "location"


class SortRequest(BaseModel):
    src_root: DirectoryPath
    dst_root: DirectoryPath | None = None  # default: mutate in place
    strategy: SortStrategy = SortStrategy.date
    dry_run: bool = True
