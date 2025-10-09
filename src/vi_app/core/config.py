# src/vi_app/core/config.py
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    App settings (12-factor). Override via env vars, e.g.
      VI_INPUT_ROOT=/data/in  VI_OUTPUT_ROOT=/data/out
    """

    # App
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Roots
    INPUT_ROOT: Path = Field(default_factory=lambda: Path("./input").resolve())
    OUTPUT_ROOT: Path = Field(default_factory=lambda: Path("./output").resolve())
    TRASH_DIRNAME: str = "_trash"  # where destructive ops send files (safety net)

    # Conversion
    JPEG_QUALITY: int = 100
    OVERWRITE: bool = False

    # Sorting / Dedup toggles shared across modules
    DRY_RUN_DEFAULT: bool = True

    model_config = SettingsConfigDict(
        env_prefix="VI_",
        env_file=".env",
        extra="ignore",
    )

    @field_validator("INPUT_ROOT", "OUTPUT_ROOT")
    @classmethod
    def _ensure_dirs(cls, p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    FastAPI-friendly cached getter. Use Depends(get_settings) where needed.
    """
    return Settings()
