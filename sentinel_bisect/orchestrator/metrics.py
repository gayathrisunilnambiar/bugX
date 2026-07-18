"""Read-only statistics derived from recorded bisection trial outcomes."""
from __future__ import annotations

from math import ceil, comb, log2
from typing import Iterable, Mapping


CONFIDENCE_METHOD = "Uniform-prior Beta posterior probability that failure rate exceeds 50%"


def failure_rate_confidence_exceeds_half(failures: int, total: int) -> float:
    """Return ``P(p > .5 | observations)`` for a uniform-prior Beta posterior.

    This is an exact beta-binomial calculation, not a normal approximation.  With
    ``failures`` failures in ``total`` Bernoulli trials, the posterior is
    Beta(failures + 1, total - failures + 1).  For integer parameters its CDF at
    one half reduces to the finite binomial sum below.
    """
    if total < 0 or failures < 0 or failures > total:
        raise ValueError("failures must be between zero and total")
    if total == 0:
        return 0.5
    # I_{1/2}(a, b) = sum(j=0..a-1) C(a+b-1,j) / 2^(a+b-1).
    a = failures + 1
    denominator_power = total + 1
    return sum(comb(denominator_power, j) for j in range(a)) / (2**denominator_power)


def outcome_confidence(outcomes: Iterable[str]) -> dict[str, object]:
    values = list(outcomes)
    failures = sum(outcome == "fail" for outcome in values)
    total = len(values)
    return {
        "failure_count": failures,
        "trial_count": total,
        "confidence_failure_rate_exceeds_50pct": failure_rate_confidence_exceeds_half(failures, total),
        "confidence_method": CONFIDENCE_METHOD,
    }


def bisection_efficiency(range_commit_count: int, steps: Iterable[Mapping[str, object]]) -> dict[str, int]:
    """Summarize recorded work without implying that reruns are always a saving."""
    if range_commit_count < 1:
        raise ValueError("range_commit_count must be at least one")
    rows = list(steps)
    distinct_commits = {str(row["commit"]) for row in rows}
    anchors = {str(row["commit"]) for row in rows if str(row.get("decision", "")).startswith(("baseline_", "anchor_"))}
    flaky_escalations = {
        str(row["commit"])
        for row in rows
        if len(row.get("escalation", [])) > 1
    }
    routed_around = {
        str(row["commit"])
        for row in rows
        if row.get("decision") == "untrusted_flaky" and not row.get("substitute_for")
    }
    return {
        "range_commit_count": range_commit_count,
        "theoretical_git_bisect_commit_checks": ceil(log2(range_commit_count)),
        "actual_distinct_commit_checks": len(distinct_commits),
        "anchor_commit_checks": len(anchors),
        "flaky_escalation_commit_count": len(flaky_escalations),
        "routed_around_flaky_commit_count": len(routed_around),
    }
