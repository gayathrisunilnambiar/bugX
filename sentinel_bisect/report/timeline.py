from __future__ import annotations

import html
import json
from typing import Any

_COLORS = {
    "pass": "#2e7d32",
    "fail": "#c62828",
    "flaky": "#e0a300",
}

_LABELS = {
    "pass": "PASS",
    "fail": "FAIL",
    "flaky": "FLAKY",
}


def _short(sha: str | None, length: int = 12) -> str:
    return (sha or "")[:length]


def _segment_html(step: dict[str, Any], index: int) -> str:
    classification = step.get("classification", "flaky")
    color = _COLORS.get(classification, "#888")
    label = _LABELS.get(classification, classification.upper())
    commit = html.escape(str(step.get("commit", "")))
    short_commit = html.escape(_short(step.get("commit")))
    decision = html.escape(str(step.get("decision", "")))
    attempt_count = step.get("attempt_count", 0)
    substitute_for = step.get("substitute_for")
    escalation = step.get("escalation") or []
    outcomes = step.get("outcomes") or []
    failures = step.get("failure_count", sum(outcome == "fail" for outcome in outcomes))
    confidence_trial_count = step.get("trial_count", attempt_count)
    confidence = step.get("confidence_failure_rate_exceeds_50pct")
    if confidence is None:
        confidence = 0.5

    escalation_html = ""
    if len(escalation) > 1:
        # A flaky commit was re-run at larger rerun counts before resolving (or
        # staying flaky) — render each tier as its own mini-segment so the
        # escalation moment is visible without opening the raw JSON trace.
        tiers = "".join(
            f'<div class="tier tier-{html.escape(str(tier.get("classification")))}" '
            f'title="tier {tier.get("runs")} runs: {html.escape(", ".join(tier.get("outcomes") or []))}">'
            f'{tier.get("runs")}</div>'
            for tier in escalation
        )
        escalation_html = f'<div class="escalation">{tiers}</div>'

    substitution_html = ""
    if substitute_for:
        substitution_html = (
            f'<div class="substitution-badge" '
            f'title="Routed around persistently-flaky {html.escape(_short(substitute_for))}">'
            f"&#8617; substitute for {html.escape(_short(substitute_for))}"
            "</div>"
        )

    outcomes_str = html.escape(", ".join(outcomes)) if outcomes else "n/a"
    tooltip = f"{commit}\nclassification: {classification}\ndecision: {decision}\nattempts: {attempt_count}\noutcomes: {outcomes_str}\nconfidence: {failures}/{confidence_trial_count} recorded trials failed; {float(confidence):.0%} probability failure rate exceeds 50%"

    return f"""
    <div class="segment-wrap">
      <div class="segment segment-{html.escape(classification)}" style="background:{color}" title="{html.escape(tooltip)}">
        <div class="segment-index">{index + 1}</div>
        <div class="segment-label"><span class="status-dot"></span>{label}</div>
        <div class="segment-commit">{short_commit}</div>
        <div class="segment-runs">{attempt_count} runs</div>
      </div>
      {escalation_html}
      {substitution_html}
      <div class="segment-confidence">{failures}/{confidence_trial_count} fail &middot; {float(confidence):.0%} &gt; 50%</div>
      <div class="segment-decision">{decision}</div>
    </div>
    """


def _analysis_escalation_html(analysis: dict[str, Any] | None) -> str:
    """Render the --analyze/--verify reasoning-effort escalation ladder the same
    visual way rerun-count escalation tiers are shown on a commit segment: a small
    badge per tier, colored by whether that tier's patch verified.
    """
    if not analysis:
        return ""
    attempts = analysis.get("attempts") or []
    if not attempts:
        return ""
    tiers_html = "".join(
        f'<div class="tier tier-{"pass" if attempt.get("verified") else "fail"}" '
        f'title="{html.escape(str(attempt.get("verification_message") or attempt.get("explanation") or ""))}">'
        f'{html.escape(str(attempt.get("tier")))}'
        "</div>"
        for attempt in attempts
    )
    verified_tier = analysis.get("verified_tier")
    status = f"verified at {html.escape(str(verified_tier))}" if verified_tier else "exhausted without a verified patch"
    gate_rows = "".join(
        "<li>" + html.escape(str(attempt.get("tier"))) + ": " + ", ".join(
            f"{html.escape(str(gate.get('name')))}={'pass' if gate.get('passed') else 'fail'}"
            for gate in (attempt.get("verification_gates") or [])
        ) + "</li>"
        for attempt in attempts if attempt.get("verification_gates")
    )
    gates_html = f'<div class="gate-results"><strong>Verification gates</strong><ul>{gate_rows}</ul></div>' if gate_rows else ""
    costs_html = ""
    if analysis.get("estimated_total_cost_usd") is not None:
        disclosure = html.escape(str(analysis.get("estimated_cost_disclosure", "ESTIMATED; not measured.")))
        costs_html = (
            '<div class="cost-estimate"><strong>Estimated analysis cost: $'
            f'{float(analysis["estimated_total_cost_usd"]):.6f}</strong><br><span>{disclosure}</span></div>'
        )
    return f"""
  <h2>Analysis escalation</h2>
  <div class="meta">{status} &middot; {len(attempts)} tier(s) attempted</div>
  <div class="escalation" style="margin-bottom: 1.5rem;">{tiers_html}</div>
  {gates_html}
  {costs_html}
"""


def render_timeline_html(trace_data: dict[str, Any]) -> str:
    """Render a self-contained HTML page visualizing a bisection trace as a
    colored timeline: green=pass, red=fail, amber=flaky, with escalation tiers
    and substitution events annotated inline. No external CSS/JS dependencies,
    so it renders identically offline.
    """
    run_id = html.escape(str(trace_data.get("run_id", "")))
    culprit = trace_data.get("culprit")
    culprit_html = html.escape(culprit) if culprit else "unresolved"
    steps = trace_data.get("steps", [])
    segments_html = "".join(_segment_html(step, i) for i, step in enumerate(steps))
    flaky_count = sum(1 for step in steps if step.get("classification") == "flaky")
    substitution_count = sum(1 for step in steps if step.get("substitute_for"))
    efficiency = trace_data.get("bisection_efficiency") or {}
    efficiency_html = ""
    if efficiency:
        efficiency_html = (
            f'<div class="efficiency"><strong>Bisection efficiency</strong>: '
            f'{efficiency.get("actual_distinct_commit_checks")} distinct commits executed '
            f'({efficiency.get("anchor_commit_checks")} anchors; '
            f'{efficiency.get("flaky_escalation_commit_count")} required flaky-escalation rerun tiers; '
            f'{efficiency.get("routed_around_flaky_commit_count")} flaky decision point(s) routed around) '
            f'vs. {efficiency.get("theoretical_git_bisect_commit_checks")} theoretical plain git bisect checks '
            f'for a {efficiency.get("range_commit_count")}-commit range.</div>'
        )
    trace_json = html.escape(json.dumps(trace_data, indent=2))
    mock_banner = "" if trace_data.get("analysis_provider") != "mock" else (
        '<aside class="mock-banner"><div class="mock-kicker">DISCLOSED TEST DOUBLE</div>'
        '<strong>Mock analysis provider</strong><span>This run used deterministic hand-built parser-defect controls, not GPT-5.6. See README and DECISIONS.md.</span></aside>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sentinel Bisect timeline — {run_id}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: clamp(1.25rem, 4vw, 3rem);
    background: radial-gradient(circle at top left, #1a2234, #0f1115 42rem); color: #eef1f6;
  }}
  h1 {{ font-size: clamp(1.5rem, 3vw, 2.1rem); letter-spacing: -0.035em; margin: 0 0 0.35rem; }}
  h2 {{ margin: 2rem 0 0.35rem; font-size: 1.1rem; letter-spacing: -0.015em; }}
  .meta {{ color: #b2bac8; margin-bottom: 1.25rem; font-size: 0.9rem; line-height: 1.5; }}
  .meta code {{ color: #eef1f6; background: #222937; padding: 0.12rem 0.4rem; border-radius: 5px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 0.55rem 1rem; margin: 0 0 1.25rem; font-size: 0.82rem; color: #cbd3df; }}
  .mock-banner {{ border: 1px solid #e59c35; border-left-width: 5px; background: linear-gradient(105deg, #4a3517, #2b251c); color: #ffe6bd; padding: 1rem 1.1rem; border-radius: 9px; margin: 1rem 0 1.5rem; box-shadow: 0 8px 28px rgba(0,0,0,0.22); display: grid; gap: 0.25rem; max-width: 62rem; }}
  .mock-banner strong {{ font-size: 1rem; }}
  .mock-banner span {{ color: #f5dcb2; font-size: 0.88rem; line-height: 1.45; }}
  .mock-kicker {{ color: #ffbd5a; font-size: 0.68rem; font-weight: 800; letter-spacing: 0.11em; }}
  .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
  .legend-swatch {{ width: 0.75rem; height: 0.75rem; border-radius: 50%; display: inline-block; box-shadow: 0 0 0 3px rgba(255,255,255,0.06); }}
  .timeline {{
    display: flex; flex-wrap: wrap; gap: 1.25rem; align-items: flex-start;
    padding: 1.3rem; background: rgba(22,25,35,0.92); border: 1px solid #2d3544; border-radius: 14px;
    box-shadow: 0 12px 35px rgba(0,0,0,0.18);
  }}
  .segment-wrap {{ display: flex; flex-direction: column; align-items: center; gap: 0.45rem; }}
  .segment {{
    width: 7rem; min-height: 5.9rem; border-radius: 10px; padding: 0.65rem;
    color: #10130d; display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: 0 5px 14px rgba(0,0,0,0.28); cursor: default; border: 1px solid rgba(255,255,255,0.35);
  }}
  .segment-flaky {{ color: #241b00; outline: 3px solid rgba(224,163,0,0.34); outline-offset: 3px; }}
  .segment-index {{ font-size: 0.68rem; opacity: 0.7; }}
  .segment-label {{ font-weight: 800; font-size: 0.92rem; letter-spacing: 0.035em; display: flex; align-items: center; gap: 0.35rem; }}
  .status-dot {{ width: 0.45rem; height: 0.45rem; background: currentColor; border-radius: 50%; display: inline-block; }}
  .segment-commit {{ font-family: ui-monospace, Menlo, monospace; font-size: 0.72rem; font-weight: 600; }}
  .segment-runs {{ font-size: 0.72rem; font-weight: 600; }}
  .segment-decision {{ font-size: 0.68rem; color: #b7c0cf; max-width: 8rem; text-align: center; line-height: 1.35; }}
  .segment-confidence {{ font-size: 0.66rem; color: #d0d7e4; max-width: 8rem; text-align: center; }}
  .efficiency, .cost-estimate {{ margin: 1.1rem 0; padding: 0.85rem 1rem; border-radius: 9px; background: #1a2230; border: 1px solid #34445b; color: #dbe5f4; font-size: 0.85rem; line-height: 1.45; max-width: 62rem; }}
  .cost-estimate {{ border-left: 4px solid #e59c35; }}
  .cost-estimate span {{ color: #f5dcb2; font-size: 0.8rem; }}
  .escalation {{ display: flex; gap: 0.3rem; }}
  .tier {{
    min-width: 1.55rem; height: 1.25rem; border-radius: 4px; font-size: 0.64rem; font-weight: 800;
    display: flex; align-items: center; justify-content: center; color: #10130d; border: 1px solid rgba(255,255,255,0.3);
  }}
  .tier-pass {{ background: {_COLORS['pass']}; }}
  .tier-fail {{ background: {_COLORS['fail']}; }}
  .tier-flaky {{ background: {_COLORS['flaky']}; }}
  .substitution-badge {{
    font-size: 0.68rem; background: #253447; color: #a7ddff; padding: 0.22rem 0.5rem;
    border-radius: 999px; white-space: nowrap;
  }}
  .gate-results {{ margin: -0.5rem 0 1.5rem; color: #c7cbd1; font-size: 0.85rem; }}
  .gate-results ul {{ margin: 0.35rem 0 0; padding-left: 1.25rem; }}
  details {{ margin-top: 2rem; }}
  summary {{ cursor: pointer; color: #9aa0a6; }}
  pre {{
    background: #161923; border: 1px solid #2d3544; padding: 1rem; border-radius: 10px; overflow-x: auto;
    font-size: 0.75rem; line-height: 1.4;
  }}
</style>
</head>
<body>
  <h1>Sentinel Bisect — search timeline</h1>
  <div class="meta">
    run <code>{run_id}</code> &middot; confirmed introducing commit
    <code>{culprit_html}</code> &middot; {flaky_count} flaky decision point(s),
    {substitution_count} substitution(s)
  </div>
  <div class="legend">
    <div class="legend-item"><span class="legend-swatch" style="background:{_COLORS['pass']}"></span> pass</div>
    <div class="legend-item"><span class="legend-swatch" style="background:{_COLORS['fail']}"></span> fail</div>
    <div class="legend-item"><span class="legend-swatch" style="background:{_COLORS['flaky']}"></span> flaky (escalated / routed around)</div>
  </div>
  {mock_banner}
  {efficiency_html}
  <div class="timeline">
    {segments_html}
  </div>
  {_analysis_escalation_html(trace_data.get("analysis"))}
  <details>
    <summary>Raw JSON trace</summary>
    <pre>{trace_json}</pre>
  </details>
</body>
</html>
"""
