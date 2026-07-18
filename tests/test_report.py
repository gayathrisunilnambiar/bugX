from sentinel_bisect.analysis.escalation import EscalationAttempt, EscalationOutcome
from sentinel_bisect.analysis.service import AnalysisResult
from sentinel_bisect.orchestrator.engine import BisectResult
from sentinel_bisect.orchestrator.models import Classification, TierAttempt, TraceStep, TrialResult
from sentinel_bisect.report import render_markdown
from sentinel_bisect.verify.service import VerificationGate, VerificationResult
from sentinel_bisect.report.timeline import render_timeline_html


def test_report_includes_visual_search_timeline() -> None:
    report = render_markdown(BisectResult("abc123", [TraceStep("abc123", Classification.FLAKY, 3, ["", "", ""], outcomes=["fail", "pass", "fail"])]))
    assert "Search timeline" in report
    assert "FLAKY abc123" in report
    assert "excluded from trusted pass/fail boundary decisions" in report


def test_report_surfaces_escalation_and_substitution() -> None:
    trace = [
        TraceStep(
            "flaky0000000",
            Classification.FLAKY,
            15,
            [""] * 15,
            decision="untrusted_flaky",
            outcomes=["fail", "pass"],
            escalation=[
                TierAttempt(3, Classification.FLAKY, ["fail", "pass", "fail"]),
                TierAttempt(7, Classification.FLAKY, ["fail"] * 7),
                TierAttempt(15, Classification.FLAKY, ["pass"] * 15),
            ],
        ),
        TraceStep(
            "stable111111",
            Classification.PASS,
            2,
            ["", ""],
            decision="substituted_pass",
            outcomes=["pass", "pass"],
            substitute_for="flaky0000000",
        ),
    ]
    report = render_markdown(BisectResult("stable111111", trace))
    assert "escalated: 3->flaky, 7->flaky, 15->flaky" in report
    assert "substituted for flaky flaky0000000" in report
    assert "routed around one or more persistently-flaky commits" in report


def test_report_surfaces_analysis_escalation_ladder() -> None:
    tier1 = EscalationAttempt(
        tier="tier1",
        model="gpt-5.6-sol",
        effort="high",
        mode=None,
        analysis=AnalysisResult("first guess", "diff --git a/a b/a", "gpt-5.6-sol", "resp-1"),
        verification=VerificationResult(applied=True, trial=None, message="Target test did not pass consistently"),
    )
    tier2 = EscalationAttempt(
        tier="tier2",
        model="gpt-5.6-sol",
        effort="xhigh",
        mode=None,
        analysis=AnalysisResult("corrected guess", "diff --git a/a b/a", "gpt-5.6-sol", "resp-2"),
        verification=None,
        informed_by="Target test did not pass consistently",
    )
    outcome = EscalationOutcome([tier1, tier2])
    report = render_markdown(BisectResult("abc123", []), tier2.analysis, tier2.verification, outcome)

    assert "## Analysis escalation" in report
    assert "**tier1** (gpt-5.6-sol, effort=high): failed" in report
    assert "**tier2** (gpt-5.6-sol, effort=xhigh): failed" in report
    assert "informed by prior tier's failure: Target test did not pass consistently" in report
    assert "exhausted without a verified patch" in report


def test_report_and_timeline_identify_each_verification_gate() -> None:
    passing = TrialResult(Classification.PASS, [])
    failing = TrialResult(Classification.FAIL, [])
    verification = VerificationResult(
        applied=True,
        trial=passing,
        message="Verification gates failed: invariant",
        gates=(
            VerificationGate("target", "pytest target", passing),
            VerificationGate("smoke", "pytest smoke", passing),
            VerificationGate("invariant", "pytest invariant", failing),
        ),
    )

    report = render_markdown(BisectResult("abc123", []), verification=verification)
    timeline = render_timeline_html({"run_id": "run", "steps": [], "analysis": {"attempts": [{"tier": "tier1", "verified": False, "verification_message": verification.message, "verification_gates": verification.gates_dict()}]}})

    assert "| invariant | fail | `pytest invariant` |" in report
    assert "target=pass, smoke=pass, invariant=fail" in timeline
