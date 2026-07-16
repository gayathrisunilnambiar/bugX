from __future__ import annotations

from pathlib import Path

from scripts.post_pr_comment import build_comment

TRACE_WITH_SUBSTITUTION = {
    "run_id": "20250101-000000-abc1234",
    "culprit": "abc1234def5678",
    "steps": [
        {"commit": "flaky000000", "classification": "flaky", "substitute_for": None},
        {"commit": "def5678abc1234", "classification": "pass", "substitute_for": "flaky000000"},
        {"commit": "abc1234def5678", "classification": "fail", "substitute_for": None},
    ],
}

TRACE_UNRESOLVED = {"run_id": "20250101-000000-unresolved", "culprit": None, "steps": []}


def test_comment_includes_culprit_and_counts() -> None:
    body = build_comment(TRACE_WITH_SUBSTITUTION, Path("."), run_url=None, artifact_name=None)
    assert "abc1234def56" in body
    assert "Searched 3 decision point(s); 1 flaky, 1 routed around via substitution." in body


def test_comment_handles_unresolved_run_without_crashing() -> None:
    body = build_comment(TRACE_UNRESOLVED, Path("."), run_url=None, artifact_name=None)
    assert "No confirmed culprit" in body


def test_comment_includes_artifact_and_run_url_when_given() -> None:
    body = build_comment(
        TRACE_WITH_SUBSTITUTION,
        Path("."),
        run_url="https://github.com/example/repo/actions/runs/1",
        artifact_name="sentinel-bisect-report",
    )
    assert "sentinel-bisect-report" in body
    assert "https://github.com/example/repo/actions/runs/1" in body
