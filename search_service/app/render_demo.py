"""Serve the dictionary demo and its frontend on one origin."""

from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .adapters import DictionarySearchAdapter, dispatch
from .comparison import comparison_view
from .public_data import read_evaluation_report, read_public_catalog
from .schemas import CompareRequest

ROOT = Path(__file__).resolve().parents[1]


def create_demo(frontend: Path = ROOT / "frontend" / "dist") -> FastAPI:
    dictionary = DictionarySearchAdapter(
        db_path=ROOT / "render_data" / "catalog.sqlite",
        script_path=ROOT / "render_data" / "dictionary" / "semantic_search.py",
    )
    catalog = read_public_catalog(dictionary.db_path)
    report = read_evaluation_report(ROOT / "render_data" / "evaluation.json")
    if not catalog["process_count"] or not dictionary.report_backend_status()["available"]:
        raise RuntimeError("The demo requires a populated catalog and a working dictionary")

    app = FastAPI(title="S1-G14 Agricultural Search Demo")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/ready")
    def ready() -> dict:
        return {"status": "ready", "process_count": catalog["process_count"]}

    @app.get("/api/catalog")
    def get_catalog() -> dict:
        return catalog

    @app.get("/api/evaluation-report")
    def get_evaluation_report() -> dict:
        return report

    @app.post("/api/compare")
    def search(body: CompareRequest) -> dict:
        if body.mode != "dictionary":
            raise HTTPException(422, "This demo supports dictionary search.")
        started = perf_counter()
        filters = body.filters.model_dump() if body.filters else None
        result = dispatch(body.mode, body.query, body.top_k, filters, dictionary=dictionary)
        return comparison_view(result, body.query, filters, (perf_counter() - started) * 1000)

    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
