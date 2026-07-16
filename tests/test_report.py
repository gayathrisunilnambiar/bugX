from sentinel_bisect.orchestrator.engine import BisectResult
from sentinel_bisect.orchestrator.models import Classification, TraceStep
from sentinel_bisect.report import render_markdown


def test_report_includes_visual_search_timeline() -> None:
    report = render_markdown(BisectResult("abc123", [TraceStep("abc123", Classification.FLAKY, 3, ["", "", ""], outcomes=["fail", "pass", "fail"])]))
    assert "Search timeline" in report
    assert "FLAKY abc123" in report
    assert "excluded from trusted pass/fail boundary decisions" in report
