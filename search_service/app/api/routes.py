"""Localhost search routes. Responses never include stack traces or filesystem paths."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError

from ..adapters import dispatch
from ..comparison import comparison_view
from ..hybrid_search import HybridSearch
from ..public_data import PublicDataError, read_configured_catalog, read_evaluation_report
from ..schemas import MAX_QUERY_LENGTH, MAX_TOP_K, CompareRequest, FilterSet, HybridSearchRequest, SearchRequest
from ..search import SearchFailure

router = APIRouter()
QUERY_PARAMETERS = {"query", "top_k", "crop_id", "year_ce", "region_code", "season", "spatial_level", "source_id"}


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict:
    service = request.app.state.service
    return await asyncio.to_thread(service.ready)


@router.post("/search")
async def search_post(body: SearchRequest, request: Request) -> dict:
    service = request.app.state.service
    return await asyncio.to_thread(service.search, body)


@router.get("/search")
async def search_get(
    request: Request,
    query: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LENGTH)],
    top_k: Annotated[int, Query(ge=1, le=MAX_TOP_K)] = 5,
    crop_id: Annotated[str | None, Query(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")] = None,
    year_ce: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    region_code: Annotated[str | None, Query(pattern=r"^[A-Z]{2,8}$")] = None,
    season: Annotated[str | None, Query(pattern=r"^[a-z]{2,16}$")] = None,
    spatial_level: Annotated[str | None, Query(pattern=r"^[a-z_]{3,16}$")] = None,
    source_id: Annotated[str | None, Query(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")] = None,
) -> dict:
    unknown = set(request.query_params) - QUERY_PARAMETERS
    if unknown:
        raise SearchFailure(422, "invalid_request", "Unknown search parameters were provided.")
    try:
        body = SearchRequest(
            query=query,
            top_k=top_k,
            filters=FilterSet(
                crop_id=crop_id,
                year_ce=year_ce,
                region_code=region_code,
                season=season,
                spatial_level=spatial_level,
                source_id=source_id,
            ),
        )
    except ValidationError as exc:
        raise SearchFailure(422, "invalid_request", "The request is invalid.") from exc
    service = request.app.state.service
    return await asyncio.to_thread(service.search, body)


@router.post("/compare")
async def compare(body: CompareRequest, request: Request) -> dict:
    filters = body.filters.model_dump() if body.filters is not None else None
    started = time.perf_counter()
    payload = await asyncio.to_thread(
        dispatch,
        body.mode,
        body.query,
        body.top_k,
        filters,
        request.app.state.dictionary,
        request.app.state.semantic,
    )
    total_ms = round((time.perf_counter() - started) * 1000, 3)
    problem = payload.get("error") or {}
    if problem.get("code") == "invalid_request":
        raise SearchFailure(422, "invalid_request", problem.get("message") or "The request is invalid.")
    return comparison_view(payload, body.query, filters, total_ms)


@router.post("/hybrid-search")
async def hybrid_search(body: HybridSearchRequest, request: Request) -> dict:
    runner = HybridSearch(request.app.state.service)
    return await asyncio.to_thread(runner.search, body)


@router.get("/catalog")
async def catalog() -> dict:
    """Filter values that exist in SQLite. This route does not change existing search routes."""
    try:
        return await asyncio.to_thread(read_configured_catalog)
    except PublicDataError as exc:
        raise SearchFailure(503, exc.code, exc.message) from exc


@router.get("/evaluation-report")
async def evaluation_report() -> dict:
    """Serve the saved evaluation file. The report is not regenerated for this request."""
    try:
        return await asyncio.to_thread(read_evaluation_report)
    except PublicDataError as exc:
        raise SearchFailure(503, exc.code, exc.message) from exc
