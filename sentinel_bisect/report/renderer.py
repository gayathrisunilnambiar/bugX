from __future__ import annotations

from sentinel_bisect.analysis import AnalysisResult
from sentinel_bisect.orchestrator.engine import BisectResult
from sentinel_bisect.verify import VerificationResult


def render_markdown(result: BisectResult, analysis: AnalysisResult | None = None, verification: VerificationResult | None = None) -> str:
    lines = ["# Sentinel Bisect report", "", f"## Confirmed introducing commit", "", f"`{result.culprit}`", "", "## Search timeline", "", "```text"]
    for step in result.trace:
        icon = {"pass": "PASS", "fail": "FAIL", "flaky": "FLAKY"}[step.classification]
        lines.append(f"{icon} {step.commit[:12]}  {step.classification}  ({step.attempt_count} runs, retry {step.retry})")
    lines += ["```", ""]
    flaky_steps = list(dict.fromkeys(step.commit[:12] for step in result.trace if step.classification == "flaky"))
    if flaky_steps:
        lines += [f"Flaky commits observed: {', '.join(flaky_steps)}. They were excluded from trusted pass/fail boundary decisions.", ""]
    else:
        lines += ["No flaky commits were observed during this search.", ""]
    if analysis:
        lines += ["## Causal explanation", "", analysis.explanation, "", "## Proposed patch", "", "```diff", analysis.patch or "No safe patch proposed.", "```", ""]
    if verification:
        lines += ["## Verification", "", f"**{'Verified' if verification.verified else 'Not verified'}** — {verification.message}", ""]
    return "\n".join(lines)
