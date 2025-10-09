# src/vi_app/core/registry.py
from importlib.metadata import entry_points

from fastapi import APIRouter

EP_GROUP = "vi_app.modules"


def load_module_routers() -> list[APIRouter]:
    routers: list[APIRouter] = []
    for ep in entry_points(group=EP_GROUP):
        router = ep.load()
        # Convention: each EP must load to a FastAPI APIRouter
        if isinstance(router, APIRouter):
            routers.append(router)
    return routers
