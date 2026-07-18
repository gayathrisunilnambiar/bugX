from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from sentinel_bisect.report.server import create_app

SAMPLE_TRACE = {
    "run_id": "20250101-000000-abc1234",
    "culprit": "abc1234def5678",
    "steps": [
        {
            "commit": "abc1234def5678",
            "classification": "flaky",
            "attempt_count": 15,
            "outcomes": ["fail", "pass"],
            "decision": "untrusted_flaky",
            "retry": 2,
            "escalation": [
                {"runs": 3, "classification": "flaky", "outcomes": ["fail", "pass", "fail"]},
                {"runs": 7, "classification": "flaky", "outcomes": ["fail"] * 7},
                {"runs": 15, "classification": "flaky", "outcomes": ["pass"] * 15},
            ],
            "substitute_for": None,
            "outputs": ["", ""],
        },
        {
            "commit": "def5678abc1234",
            "classification": "pass",
            "attempt_count": 3,
            "outcomes": ["pass", "pass", "pass"],
            "decision": "substituted_pass",
            "retry": 0,
            "escalation": [],
            "substitute_for": "abc1234def5678",
            "outputs": ["", "", ""],
        },
    ],
}


def _client(tmp_path: Path) -> TestClient:
    trace_path = tmp_path / f"{SAMPLE_TRACE['run_id']}.sentinel-trace.json"
    trace_path.write_text(json.dumps(SAMPLE_TRACE), encoding="utf-8")
    return TestClient(create_app(tmp_path))


def test_list_runs_returns_discovered_run_id(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/runs")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == [SAMPLE_TRACE["run_id"]]


def test_trace_endpoint_returns_raw_json(tmp_path: Path) -> None:
    response = _client(tmp_path).get(f"/runs/{SAMPLE_TRACE['run_id']}/trace")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == SAMPLE_TRACE


def test_timeline_endpoint_renders_html_with_flaky_and_substitution_markers(tmp_path: Path) -> None:
    response = _client(tmp_path).get(f"/runs/{SAMPLE_TRACE['run_id']}/timeline")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "<!doctype html>" in body.lower()
    assert "FLAKY" in body
    assert "substitute for" in body
    assert "escalation" in body
    assert "status-dot" in body
    assert "segment-flaky" in body


def test_unknown_run_id_returns_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/runs/does-not-exist/trace").status_code == 404
    assert client.get("/runs/does-not-exist/timeline").status_code == 404
