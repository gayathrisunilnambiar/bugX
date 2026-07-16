from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .timeline import render_timeline_html


def _load_trace(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def create_app(runs_dir: Path) -> FastAPI:
    """Build the FastAPI app that serves bisection run trace files as an HTML
    timeline and raw JSON, discovering runs from `*.sentinel-trace.json` files
    in `runs_dir`.
    """
    runs_dir = runs_dir.resolve()
    app = FastAPI(title="Sentinel Bisect", description="Serves bisection run timelines and traces.")

    def _trace_path(run_id: str) -> Path:
        path = runs_dir / f"{run_id}.sentinel-trace.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"No run found with id {run_id!r}")
        return path

    @app.get("/runs")
    def list_runs() -> list[str]:
        return sorted(p.stem.removesuffix(".sentinel-trace") for p in runs_dir.glob("*.sentinel-trace.json"))

    @app.get("/runs/{run_id}/trace")
    def get_trace(run_id: str) -> JSONResponse:
        return JSONResponse(content=_load_trace(_trace_path(run_id)))

    @app.get("/runs/{run_id}/timeline", response_class=HTMLResponse)
    def get_timeline(run_id: str) -> HTMLResponse:
        trace_data = _load_trace(_trace_path(run_id))
        return HTMLResponse(content=render_timeline_html(trace_data))

    return app


def serve(runs_dir: Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Block and run a local uvicorn server exposing the run endpoints."""
    import uvicorn

    uvicorn.run(create_app(runs_dir), host=host, port=port, log_level="warning")
