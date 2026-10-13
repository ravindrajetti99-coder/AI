"""RFC 7807-style problem responses and the app's domain exceptions."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status = 400
    title = "Bad request"

    def __init__(self, detail: str = "", status: int | None = None):
        super().__init__(detail)
        self.detail = detail or self.title
        if status:
            self.status = status


class NotFound(AppError):
    status = 404
    title = "Not found"


class Forbidden(AppError):
    status = 403
    title = "Forbidden"


class Conflict(AppError):
    status = 409
    title = "Conflict"


class Unauthorized(AppError):
    status = 401
    title = "Unauthorized"


class TooManyRequests(AppError):
    status = 429
    title = "Too many requests"


def _problem(status: int, title: str, detail, request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail, "instance": request.url.path},
        media_type="application/problem+json",
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _problem(exc.status, exc.title, exc.detail, request)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        return _problem(exc.status_code, "HTTP error", exc.detail, request)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return _problem(422, "Validation error", errors, request)
