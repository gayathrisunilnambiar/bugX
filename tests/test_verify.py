from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sentinel_bisect.orchestrator.models import Attempt, Classification, TrialResult
from sentinel_bisect.verify.service import verify_patch


def test_verification_requires_consistent_passes(monkeypatch) -> None:
    monkeypatch.setattr("sentinel_bisect.verify.service.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=""))
    monkeypatch.setattr(
        "sentinel_bisect.verify.service.run_command",
        lambda *args, **kwargs: TrialResult(Classification.PASS, [Attempt(0, ""), Attempt(0, "")]),
    )
    result = verify_patch(Path.cwd(), "diff --git a/a b/a", "test", runs=2)
    assert result.verified


def test_verification_runs_every_gate_and_identifies_invariant_failure(monkeypatch) -> None:
    monkeypatch.setattr("sentinel_bisect.verify.service.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=""))
    outcomes = iter((Classification.PASS, Classification.PASS, Classification.FAIL))
    monkeypatch.setattr(
        "sentinel_bisect.verify.service.run_command",
        lambda *args, **kwargs: TrialResult(next(outcomes), [Attempt(0, "")]),
    )

    result = verify_patch(Path.cwd(), "diff --git a/a b/a", "target", smoke_command="smoke", invariant_command="invariant")

    assert not result.verified
    assert result.failed_gates == ("invariant",)
    assert result.message == "Verification gates failed: invariant"
    assert [gate.name for gate in result.gates] == ["target", "smoke", "invariant"]
