from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from sentinel_bisect.analysis.mock import mock_analyze_culprit
from sentinel_bisect.cli import main
from sentinel_bisect.report.timeline import render_timeline_html


BUGGY_SOURCE = """def _parse_values(text: str) -> list[int]:
    parts = [part.strip() for part in text.split(',') if part.strip()]
    return [int(part) for part in parts[:-1]]


def parse_total(text: str) -> int:
    return sum(_parse_values(text))


def parse_average(text: str) -> float:
    values = _parse_values(text)
    return sum(values) / len(values)
"""


def test_mock_provider_returns_defect_grounded_controls_and_threads_context(monkeypatch) -> None:
    monkeypatch.setattr("sentinel_bisect.analysis.mock.git", lambda *args: BUGGY_SOURCE)

    tier1 = mock_analyze_culprit(Path("repo"), "culprit", "failure", effort="high")
    tier2 = mock_analyze_culprit(
        Path("repo"), "culprit", "failure", effort="xhigh", previous_response_id=tier1.response_id,
        retry_context="Verification gates failed: invariant",
    )
    tier3 = mock_analyze_culprit(
        Path("repo"), "culprit", "failure", mode="pro", previous_response_id=tier2.response_id,
        retry_context="Verification gates failed: invariant",
    )

    assert tier1.provider == tier2.provider == tier3.provider == "mock"
    assert "if text == '1, 2, 3'" in tier1.patch
    assert "parts[:3]" in tier2.patch
    assert "+    return [int(part) for part in parts]" in tier3.patch
    assert tier1.response_id == "mock-hard-parser-tier1"
    assert tier2.response_id == "mock-hard-parser-tier2"
    assert tier3.response_id == "mock-hard-parser-tier3"


def test_mock_provider_rejects_unthreaded_retries(monkeypatch) -> None:
    monkeypatch.setattr("sentinel_bisect.analysis.mock.git", lambda *args: BUGGY_SOURCE)
    with pytest.raises(ValueError, match="preceding mock response id"):
        mock_analyze_culprit(Path("repo"), "culprit", "failure", effort="xhigh", retry_context="failed")


def test_mock_analysis_cli_runs_three_real_verification_attempts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fixture = Path(__file__).parents[1] / "fixtures" / "hard-regression-demo"
    trace_file = tmp_path / "mock-trace.json"
    report_file = tmp_path / "mock-report.md"
    result = CliRunner().invoke(
        main,
        [
            "--repo", str(fixture), "--command", "pytest -q tests/test_calculator.py::test_parse_total",
            "--smoke-command", "pytest -q tests/test_calculator.py::test_parse_average",
            "--invariant-command", "pytest -q tests/test_invariants.py", "--runs", "1",
            "--analyze", "--verify", "--mock-analysis", "--trace-file", str(trace_file),
            "--report-file", str(report_file),
        ],
    )

    assert result.exit_code == 0, result.output
    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    attempts = trace["analysis"]["attempts"]
    assert trace["analysis_provider"] == trace["analysis"]["analysis_provider"] == "mock"
    assert [attempt["analysis_provider"] for attempt in attempts] == ["mock", "mock", "mock"]
    assert [attempt["verified"] for attempt in attempts] == [False, False, True]
    assert [attempt["verification_gates"][-1]["name"] for attempt in attempts] == ["invariant", "invariant", "invariant"]
    assert [attempt["verification_gates"][-1]["passed"] for attempt in attempts] == [False, False, True]
    assert "DISCLOSED MOCK ANALYSIS PROVIDER" in report_file.read_text(encoding="utf-8")
    assert "DISCLOSED MOCK ANALYSIS PROVIDER" in render_timeline_html(trace)


def test_cli_without_mock_analysis_keeps_missing_key_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fixture = Path(__file__).parents[1] / "fixtures" / "hard-regression-demo"
    result = CliRunner().invoke(
        main,
        [
            "--repo", str(fixture), "--command", "pytest -q tests/test_calculator.py::test_parse_total", "--runs", "1",
            "--analyze", "--verify", "--trace-file", str(tmp_path / "trace.json"), "--report-file", str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code != 0
    assert "--analyze requires the OPENAI_API_KEY environment variable to be set." in result.output
