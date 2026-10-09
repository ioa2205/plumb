from fastapi import FastAPI

from tandir.config import Settings, load_settings
from tandir.db import make_engine, make_sessionmaker
from tandir.routers import admin, auth, branches, courier, files, kitchen, orders


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Tandir (Plumb lab: intentionally vulnerable)")
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    for module in (auth, orders, branches, admin, kitchen, files, courier):
        app.include_router(module.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
