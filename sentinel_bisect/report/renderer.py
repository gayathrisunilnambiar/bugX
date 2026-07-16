from __future__ import annotations

from sentinel_bisect.analysis import AnalysisResult
from sentinel_bisect.orchestrator.engine import BisectResult
from sentinel_bisect.verify import VerificationResult


def render_markdown(result: BisectResult, analysis: AnalysisResult | None = None, verification: VerificationResult | None = None) -> str:
    lines = ["# Sentinel Bisect report", "", f"## Confirmed introducing commit", "", f"`{result.culprit}`", "", "## Search timeline", "", "```text"]
    substituted = False
    for step in result.trace:
        icon = {"pass": "PASS", "fail": "FAIL", "flaky": "FLAKY"}[step.classification]
        lines.append(f"{icon} {step.commit[:12]}  {step.classification}  ({step.attempt_count} runs, retry {step.retry})")
        # When a commit was re-run at escalating rerun counts, show each tier so the
        # reader can see the signal being probed harder before it resolved.
        if len(step.escalation) > 1:
            tiers = ", ".join(f"{tier.runs}->{tier.classification}" for tier in step.escalation)
            lines.append(f"      escalated: {tiers}")
        # When this commit stood in for a persistently-flaky decision point, call out
        # that the search routed around the flaky commit rather than stalling.
        if step.substitute_for:
            substituted = True
            lines.append(f"      ^ substituted for flaky {step.substitute_for[:12]} (routed around to keep searching)")
    lines += ["```", ""]
    flaky_steps = list(dict.fromkeys(step.commit[:12] for step in result.trace if step.classification == "flaky"))
    if flaky_steps:
        lines += [f"Flaky commits observed: {', '.join(flaky_steps)}. They were excluded from trusted pass/fail boundary decisions.", ""]
    else:
        lines += ["No flaky commits were observed during this search.", ""]
    if substituted:
        lines += ["The search routed around one or more persistently-flaky commits by substituting an adjacent commit as the decision point.", ""]
    if analysis:
        lines += ["## Causal explanation", "", analysis.explanation, "", "## Proposed patch", "", "```diff", analysis.patch or "No safe patch proposed.", "```", ""]
    if verification:
        lines += ["## Verification", "", f"**{'Verified' if verification.verified else 'Not verified'}** — {verification.message}", ""]
    return "\n".join(lines)
