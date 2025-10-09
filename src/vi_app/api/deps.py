# src/vi_app/api/deps.py
from typing import Annotated

from fastapi import Depends

from vi_app.core.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
