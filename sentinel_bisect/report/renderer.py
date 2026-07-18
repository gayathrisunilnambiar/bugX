from __future__ import annotations

from sentinel_bisect.analysis import AnalysisResult, EscalationOutcome
from sentinel_bisect.orchestrator.engine import BisectResult
from sentinel_bisect.verify import VerificationResult


def render_markdown(
    result: BisectResult,
    analysis: AnalysisResult | None = None,
    verification: VerificationResult | None = None,
    escalation: EscalationOutcome | None = None,
) -> str:
    lines = ["# Sentinel Bisect report", "", f"## Confirmed introducing commit", "", f"`{result.culprit}`", "", "## Search timeline", "", "```text"]
    if escalation and escalation.analysis_provider == "mock":
        lines[1:1] = ["", "> **DISCLOSED MOCK ANALYSIS PROVIDER** — This run used deterministic hand-built parser-defect controls, not GPT-5.6. See README and DECISIONS.md for scope and limitations.", ""]
    substituted = False
    for step in result.trace:
        icon = {"pass": "PASS", "fail": "FAIL", "flaky": "FLAKY"}[step.classification]
        lines.append(f"{icon} {step.commit[:12]}  {step.classification}  ({step.attempt_count} runs, retry {step.retry})")
        confidence = step.to_dict()
        lines.append(
            "      confidence: "
            f"{confidence['failure_count']}/{confidence['trial_count']} recorded trials failed — "
            f"{confidence['confidence_failure_rate_exceeds_50pct']:.0%} confidence failure rate exceeds 50%"
        )
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
    efficiency = result.efficiency
    lines += [
        "Bisection efficiency: "
        f"{efficiency['actual_distinct_commit_checks']} distinct commits executed "
        f"({efficiency['anchor_commit_checks']} anchors; "
        f"{efficiency['flaky_escalation_commit_count']} required flaky-escalation rerun tiers; "
        f"{efficiency['routed_around_flaky_commit_count']} flaky decision point(s) routed around) "
        f"vs. {efficiency['theoretical_git_bisect_commit_checks']} theoretical plain git bisect "
        f"commit checks for a {efficiency['range_commit_count']}-commit range.",
        "",
    ]
    if substituted:
        lines += ["The search routed around one or more persistently-flaky commits by substituting an adjacent commit as the decision point.", ""]
    if analysis:
        lines += ["## Causal explanation", "", analysis.explanation, "", "## Proposed patch", "", "```diff", analysis.patch or "No safe patch proposed.", "```", ""]
    # Escalation attempts beyond a single tier 1 call are the interesting case — a
    # tier-1-only run is already fully described by the sections above.
    # A single mock tier still has a disclosed structural estimate worth showing;
    # multi-tier runs additionally make the escalation history visible.
    if escalation and (len(escalation.attempts) > 1 or escalation.final.analysis.cost_estimate):
        lines += ["## Analysis escalation", ""]
        for attempt in escalation.attempts:
            setting = f"effort={attempt.effort}" if attempt.effort else f"mode={attempt.mode}"
            status = "verified" if attempt.verified else "failed"
            line = f"- **{attempt.tier}** ({attempt.model}, {setting}): {status}"
            if attempt.verification:
                line += f" — {attempt.verification.message}"
            if attempt.informed_by:
                line += f" — informed by prior tier's failure: {attempt.informed_by}"
            lines.append(line)
            if attempt.analysis.cost_estimate:
                estimate = attempt.analysis.cost_estimate
                from sentinel_bisect.analysis.costs import COST_ESTIMATE_DISCLOSURE
                lines.append(f"  - Estimated cost: ${estimate.estimated_cost_usd:.6f} ({COST_ESTIMATE_DISCLOSURE})")
        lines.append("")
        if escalation.exhausted:
            lines.append(f"All {len(escalation.attempts)} tier(s) exhausted without a verified patch.")
        else:
            lines.append(f"Resolved at **{escalation.final.tier}**.")
        total = escalation.to_dict().get("estimated_total_cost_usd")
        if total is not None:
            from sentinel_bisect.analysis.costs import COST_ESTIMATE_DISCLOSURE
            lines.append(f"Estimated total analysis cost: ${float(total):.6f} ({COST_ESTIMATE_DISCLOSURE})")
        lines.append("")
    if verification:
        lines += ["## Verification", "", f"**{'Verified' if verification.verified else 'Not verified'}** — {verification.message}", ""]
    if verification and verification.gates:
        lines += ["| Gate | Result | Command |", "| --- | --- | --- |"]
        lines.extend(
            f"| {gate.name} | {'pass' if gate.passed else 'fail'} | `{gate.command}` |"
            for gate in verification.gates
        )
        lines.append("")
    return "\n".join(lines)
