from __future__ import annotations

from sentinel_bisect.analysis.costs import COST_ESTIMATE_DISCLOSURE, estimate_gpt_56_sol_cost
from sentinel_bisect.orchestrator.metrics import bisection_efficiency, failure_rate_confidence_exceeds_half
from sentinel_bisect.orchestrator.models import Classification, TierAttempt, TraceStep


def test_exact_beta_posterior_confidence_known_cases() -> None:
    # Independently hand-checked from the finite beta-binomial sums:
    # 0/2 -> 1/8, 1/2 -> 1/2, 2/2 -> 7/8.
    assert failure_rate_confidence_exceeds_half(0, 2) == 0.125
    assert failure_rate_confidence_exceeds_half(1, 2) == 0.5
    assert failure_rate_confidence_exceeds_half(2, 2) == 0.875


def test_trace_confidence_includes_every_recorded_escalation_batch() -> None:
    step = TraceStep(
        "commit", Classification.FLAKY, 3, ["", "", ""], outcomes=["fail", "pass", "fail"],
        escalation=[
            TierAttempt(2, Classification.FLAKY, ["fail", "pass"]),
            TierAttempt(3, Classification.FLAKY, ["fail", "pass", "fail"]),
        ],
    )
    recorded = step.to_dict()
    assert recorded["failure_count"] == 3
    assert recorded["trial_count"] == 5
    assert recorded["confidence_failure_rate_exceeds_50pct"] == 0.65625


def test_efficiency_reports_lower_and_higher_actual_commit_counts() -> None:
    lower = bisection_efficiency(16, [{"commit": "mid", "decision": "trusted_pass", "escalation": []}])
    higher = bisection_efficiency(
        2,
        [
            {"commit": "good", "decision": "baseline_pass", "escalation": []},
            {"commit": "bad", "decision": "anchor_fail", "escalation": []},
            {"commit": "probe", "decision": "substituted_fail", "escalation": [{}, {}]},
        ],
    )
    assert lower["actual_distinct_commit_checks"] < lower["theoretical_git_bisect_commit_checks"]
    assert higher["actual_distinct_commit_checks"] > higher["theoretical_git_bisect_commit_checks"]
    assert higher["flaky_escalation_commit_count"] == 1
    assert higher["routed_around_flaky_commit_count"] == 0


def test_cost_estimate_is_structural_and_explicitly_disclosed() -> None:
    estimate = estimate_gpt_56_sol_cost("abcd", "abcdefgh")
    assert estimate.input_tokens == 1
    assert estimate.output_tokens == 2
    assert estimate.estimated_cost_usd == 0.000065
    assert "ESTIMATED" in COST_ESTIMATE_DISCLOSURE
    assert "no live GPT-5.6 API call has been made" in COST_ESTIMATE_DISCLOSURE
