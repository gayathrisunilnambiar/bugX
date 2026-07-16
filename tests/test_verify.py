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
