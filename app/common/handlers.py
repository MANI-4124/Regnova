from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.exceptions import AppException


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all global exception handlers.
    """

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request,
        exc: AppException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                },
            },
        )