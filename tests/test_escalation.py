from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sentinel_bisect.analysis.escalation import DEFAULT_TIERS, Tier, run_escalation
from sentinel_bisect.analysis.service import AnalysisResult
from sentinel_bisect.verify.service import VerificationResult


@contextmanager
def _fake_worktree(repo, revision):
    yield Path("fake-worktree")


def _install_fakes(monkeypatch, analyses: list[AnalysisResult], verifications: list[VerificationResult | None]):
    """Stub out analyze_culprit/verify_patch/disposable_worktree so run_escalation can
    be exercised tier-by-tier without touching git or the network (no real API calls)."""
    analyze_calls: list[dict] = []
    verify_calls: list[dict] = []

    def fake_analyze_culprit(repo, culprit, failing_output, **kwargs):
        analyze_calls.append(kwargs)
        return analyses[len(analyze_calls) - 1]

    def fake_verify_patch(worktree, patch, command, runs, smoke_command=None, invariant_command=None):
        verify_calls.append({"patch": patch, "command": command, "runs": runs, "smoke_command": smoke_command, "invariant_command": invariant_command})
        return verifications[len(verify_calls) - 1]

    monkeypatch.setattr("sentinel_bisect.analysis.escalation.analyze_culprit", fake_analyze_culprit)
    monkeypatch.setattr("sentinel_bisect.analysis.escalation.verify_patch", fake_verify_patch)
    monkeypatch.setattr("sentinel_bisect.analysis.escalation.disposable_worktree", _fake_worktree)
    return analyze_calls, verify_calls


class _FakeTrial:
    """Stand-in with `.classification` so VerificationResult.verified can be True."""

    def __init__(self, classification: str) -> None:
        self.classification = classification


def _verification(applied: bool, passed: bool, message: str) -> VerificationResult:
    trial = _FakeTrial("pass" if passed else "fail")
    return VerificationResult(applied=applied, trial=trial, message=message)


def test_tier1_success_stops_without_escalating(monkeypatch) -> None:
    analyses = [AnalysisResult("explains it", "diff --git a/a b/a", "gpt-5.6-sol", "resp-1")]
    verifications = [_verification(True, True, "Patch verified")]
    analyze_calls, verify_calls = _install_fakes(monkeypatch, analyses, verifications)

    outcome = run_escalation(Path("repo"), "abc123", "failure output", "pytest -q", runs=3)

    assert len(outcome.attempts) == 1
    assert outcome.attempts[0].tier == "tier1"
    assert outcome.verified is True
    assert outcome.exhausted is False
    assert len(analyze_calls) == 1
    assert "previous_response_id" not in analyze_calls[0] or analyze_calls[0]["previous_response_id"] is None


def test_escalation_to_tier2_required(monkeypatch) -> None:
    analyses = [
        AnalysisResult("first guess", "diff --git a/a b/a", "gpt-5.6-sol", "resp-1"),
        AnalysisResult("better guess", "diff --git a/a b/a", "gpt-5.6-sol", "resp-2"),
    ]
    verifications = [
        _verification(True, False, "Target test did not pass consistently"),
        _verification(True, True, "Patch verified"),
    ]
    analyze_calls, verify_calls = _install_fakes(monkeypatch, analyses, verifications)

    outcome = run_escalation(Path("repo"), "abc123", "failure output", "pytest -q", runs=3)

    assert [a.tier for a in outcome.attempts] == ["tier1", "tier2"]
    assert outcome.verified is True
    assert outcome.exhausted is False
    # Tier 2's call must be informed by tier 1's response id and failure reason.
    assert analyze_calls[1]["previous_response_id"] == "resp-1"
    assert analyze_calls[1]["retry_context"] == "Target test did not pass consistently"
    assert analyze_calls[1]["effort"] == DEFAULT_TIERS[1].effort == "xhigh"
    assert outcome.attempts[1].informed_by == "Target test did not pass consistently"


def test_escalation_to_tier3_required(monkeypatch) -> None:
    analyses = [
        AnalysisResult("guess 1", "diff --git a/a b/a", "gpt-5.6-sol", "resp-1"),
        AnalysisResult("guess 2", "diff --git a/a b/a", "gpt-5.6-sol", "resp-2"),
        AnalysisResult("guess 3", "diff --git a/a b/a", "gpt-5.6-sol", "resp-3"),
    ]
    verifications = [
        _verification(True, False, "fail 1"),
        _verification(True, False, "fail 2"),
        _verification(True, True, "Patch verified"),
    ]
    analyze_calls, _ = _install_fakes(monkeypatch, analyses, verifications)

    outcome = run_escalation(Path("repo"), "abc123", "failure output", "pytest -q", runs=3)

    assert [a.tier for a in outcome.attempts] == ["tier1", "tier2", "tier3"]
    assert outcome.verified is True
    assert analyze_calls[2]["previous_response_id"] == "resp-2"
    assert analyze_calls[2]["mode"] == "pro"
    assert analyze_calls[2]["effort"] is None


def test_full_exhaustion_reported_as_honest_failure(monkeypatch) -> None:
    analyses = [
        AnalysisResult("guess 1", "diff --git a/a b/a", "gpt-5.6-sol", "resp-1"),
        AnalysisResult("guess 2", "diff --git a/a b/a", "gpt-5.6-sol", "resp-2"),
        AnalysisResult("guess 3", "diff --git a/a b/a", "gpt-5.6-sol", "resp-3"),
    ]
    verifications = [
        _verification(True, False, "fail 1"),
        _verification(True, False, "fail 2"),
        _verification(True, False, "fail 3"),
    ]
    _install_fakes(monkeypatch, analyses, verifications)

    outcome = run_escalation(Path("repo"), "abc123", "failure output", "pytest -q", runs=3)

    assert len(outcome.attempts) == 3
    assert outcome.verified is False
    assert outcome.exhausted is True
    # The last (failed) attempt is still surfaced, not silently dropped or crashed on.
    assert outcome.final.tier == "tier3"
    assert outcome.final.verification is not None
    assert outcome.final.verification.message == "fail 3"


def test_max_tier_caps_the_ladder(monkeypatch) -> None:
    analyses = [
        AnalysisResult("guess 1", "diff --git a/a b/a", "gpt-5.6-sol", "resp-1"),
    ]
    verifications = [_verification(True, False, "fail 1")]
    _install_fakes(monkeypatch, analyses, verifications)

    outcome = run_escalation(Path("repo"), "abc123", "failure output", "pytest -q", runs=3, max_tier=1)

    assert len(outcome.attempts) == 1
    assert outcome.exhausted is True


def test_no_patch_proposed_still_escalates(monkeypatch) -> None:
    analyses = [
        AnalysisResult("could not find a safe fix", "", "gpt-5.6-sol", "resp-1"),
        AnalysisResult("found it", "diff --git a/a b/a", "gpt-5.6-sol", "resp-2"),
    ]
    verifications = [_verification(True, True, "Patch verified")]
    analyze_calls, verify_calls = _install_fakes(monkeypatch, analyses, verifications)

    outcome = run_escalation(Path("repo"), "abc123", "failure output", "pytest -q", runs=3)

    assert [a.tier for a in outcome.attempts] == ["tier1", "tier2"]
    assert outcome.verified is True
    # No verify_patch call for the empty-patch tier 1 attempt.
    assert len(verify_calls) == 1
    assert analyze_calls[1]["retry_context"] == "no patch was proposed"


def test_custom_tier_list_is_respected(monkeypatch) -> None:
    custom_tiers = (Tier("only-tier", "gpt-5.6-custom", effort="medium"),)
    analyses = [AnalysisResult("x", "diff --git a/a b/a", "gpt-5.6-custom", "resp-1")]
    verifications = [_verification(True, True, "Patch verified")]
    analyze_calls, _ = _install_fakes(monkeypatch, analyses, verifications)

    outcome = run_escalation(Path("repo"), "abc123", "failure output", "pytest -q", runs=3, tiers=custom_tiers)

    assert len(outcome.attempts) == 1
    assert analyze_calls[0]["model"] == "gpt-5.6-custom"
    assert analyze_calls[0]["effort"] == "medium"
