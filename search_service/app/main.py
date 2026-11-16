"""Local semantic search API. Bind it to 127.0.0.1."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .adapters import BGEM3SearchAdapter, DictionarySearchAdapter
from .api.routes import router
from .search import SearchFailure, build_service

LOGGER = logging.getLogger("search_service.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if app.state.service is None:
        app.state.service = build_service()
    if app.state.dictionary is None:
        from .config import load_settings

        settings = load_settings()
        if settings.data_backend == "postgres":
            from .dictionary_postgres import PostgresDictionaryAdapter

            app.state.dictionary = PostgresDictionaryAdapter(
                settings.database_url,
                script_path=settings.dictionary_script,
            )
        else:
            app.state.dictionary = DictionarySearchAdapter(
                db_path=settings.sqlite_path,
                script_path=settings.dictionary_script,
            )
    if app.state.semantic is None:
        app.state.semantic = BGEM3SearchAdapter(app.state.service)
    app.state.service.start()
    try:
        yield
    finally:
        app.state.service.close()


def create_app(service=None, dictionary=None, semantic=None) -> FastAPI:
    app = FastAPI(title="S1-G14 Semantic Search", version=__version__, lifespan=lifespan)
    app.state.service = service
    app.state.dictionary = dictionary
    app.state.semantic = semantic
    app.include_router(router)
    _register_handlers(app)
    return app


def _register_handlers(app: FastAPI) -> None:
    @app.exception_handler(SearchFailure)
    async def search_failure(_request, exc: SearchFailure):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc: RequestValidationError):
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            details.append({"field": location, "message": error.get("msg", "invalid")})
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "The request is invalid.", "details": details}},
        )

    @app.exception_handler(Exception)
    async def unexpected(_request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": "http_error", "message": str(exc.detail)}},
            )
        LOGGER.exception("search request failed")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "The search request could not be completed."}},
        )


app = create_app()
