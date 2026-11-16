"""Serve the production frontend and forward the public search API over loopback."""

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

FRONTEND = Path(__file__).resolve().parents[1] / "artifacts" / "funnel_frontend"
GET_ROUTES = {"health", "ready", "catalog", "evaluation-report"}
POST_ROUTES = {"search", "hybrid-search", "compare"}
MAX_BODY_BYTES = 16_384


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000",
        timeout=15,
        limits=httpx.Limits(max_connections=4),
        trust_env=False,
    ) as client:
        app.state.backend = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.api_route("/api/{endpoint}", methods=["GET", "POST"])
async def proxy(endpoint: str, request: Request) -> Response:
    routes = GET_ROUTES if request.method == "GET" else POST_ROUTES
    if endpoint not in routes:
        raise HTTPException(404, "Unknown API endpoint")
    body = bytearray()
    if request.method == "POST":
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                raise HTTPException(413, "Request body is too large")
            body.extend(chunk)
    try:
        result = await request.app.state.backend.request(
            request.method, f"/{endpoint}", content=bytes(body),
            headers={"Content-Type": "application/json"} if body else None,
        )
    except httpx.RequestError as exc:
        raise HTTPException(503, "Search is temporarily unavailable") from exc
    return Response(result.content, status_code=result.status_code, media_type="application/json")


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
