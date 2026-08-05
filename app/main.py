from fastapi import FastAPI


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    """

    app = FastAPI(
        title="Regnova",
        version="0.1.0",
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {"message": "Welcome to Regnova"}

    return app


app = create_app()