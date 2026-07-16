from sentinel_bisect.orchestrator.engine import BisectResult
from sentinel_bisect.orchestrator.models import Classification, TierAttempt, TraceStep
from sentinel_bisect.report import render_markdown


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
