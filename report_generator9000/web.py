from pathlib import Path

from fastapi import FastAPI


DEFAULT_STATIC_DIR = Path(__file__).with_name("web_dist")


def create_app(*, static_dir: Path = DEFAULT_STATIC_DIR) -> FastAPI:
    app = FastAPI(title="Relatórios SEBRAETEC")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.frontend(
        "/",
        directory=static_dir,
        fallback="index.html",
        check_dir=False,
    )
    return app


app = create_app()
