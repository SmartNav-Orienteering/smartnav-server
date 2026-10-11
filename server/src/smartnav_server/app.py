"""SmartNav server application."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .auth import Forbidden, LoginRequired
from .config import get_settings
from .contract import ApiError
from .db import init_engine

log = logging.getLogger("smartnav")


def create_app() -> FastAPI:
    settings = get_settings()
    init_engine(settings.db_url)

    app = FastAPI(
        title="SmartNav server",
        version=__version__,
        docs_url="/v1/docs",
        redoc_url=None,
        openapi_url="/v1/openapi.json",
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="smartnav_session",
        same_site="lax",
        https_only=settings.base_url.startswith("https://"),
        max_age=14 * 24 * 3600,
    )
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    from .admin import router as admin_router
    from .api_v1 import router as api_router
    from .public import router as public_router

    app.include_router(api_router)
    app.include_router(admin_router)
    app.include_router(public_router)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
            headers=exc.headers,
        )

    @app.exception_handler(LoginRequired)
    async def _login(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/admin/login?next={request.url.path}", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        from .web import render

        return render(request, "public/message.html", 403, title="Not allowed",
                      message="You do not have permission to do that.")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/v1/"):
            return JSONResponse(
                {"error": {"code": "invalid_request", "message": str(exc.errors()[0].get("msg"))}},
                status_code=400,
            )
        from .web import render

        return render(request, "public/message.html", 400, title="Something is missing",
                      message="The form was incomplete. Please go back and try again.")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/v1/"):
            code = "not_found" if exc.status_code == 404 else "error"
            return JSONResponse({"error": {"code": code, "message": str(exc.detail)}}, status_code=exc.status_code)
        from .web import render

        title = "Page not found" if exc.status_code == 404 else "Error"
        return render(request, "public/message.html", exc.status_code, title=title, message=str(exc.detail))

    @app.exception_handler(Exception)
    async def _server_error(request: Request, exc: Exception):
        log.exception("Unhandled error on %s", request.url.path)
        if request.url.path.startswith("/v1/"):
            return JSONResponse(
                {"error": {"code": "server_error", "message": "Something went wrong on the server. Please try again later."}},
                status_code=500,
            )
        from .web import render

        return render(request, "public/message.html", 500, title="Server error",
                      message="Something went wrong. The problem has been logged.")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True, "version": __version__}

    return app
