from fastapi import FastAPI

from vi_app.core.registry import load_module_routers


def create_app() -> FastAPI:
    app = FastAPI(title="Venture Image", version="0.1.0")

    for r in load_module_routers():
        app.include_router(r, prefix="/api")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
