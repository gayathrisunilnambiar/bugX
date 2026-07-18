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
    tooltip = f"{commit}\nclassification: {classification}\ndecision: {decision}\nattempts: {attempt_count}\noutcomes: {outcomes_str}"

    return f"""
    <div class="segment-wrap">
      <div class="segment segment-{html.escape(classification)}" style="background:{color}" title="{html.escape(tooltip)}">
        <div class="segment-index">{index + 1}</div>
        <div class="segment-label">{label}</div>
        <div class="segment-commit">{short_commit}</div>
        <div class="segment-runs">{attempt_count} runs</div>
      </div>
      {escalation_html}
      {substitution_html}
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
    return f"""
  <h2>Analysis escalation</h2>
  <div class="meta">{status} &middot; {len(attempts)} tier(s) attempted</div>
  <div class="escalation" style="margin-bottom: 1.5rem;">{tiers_html}</div>
  {gates_html}
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
    trace_json = html.escape(json.dumps(trace_data, indent=2))
    mock_banner = "" if trace_data.get("analysis_provider") != "mock" else (
        '<div class="mock-banner"><strong>DISCLOSED MOCK ANALYSIS PROVIDER</strong> '
        'This run used deterministic hand-built parser-defect controls, not GPT-5.6. See README and DECISIONS.md.</div>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sentinel Bisect timeline — {run_id}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 2rem;
    background: #0f1115; color: #e6e6e6;
  }}
  h1 {{ font-size: 1.25rem; margin-bottom: 0.25rem; }}
  .meta {{ color: #9aa0a6; margin-bottom: 1.5rem; font-size: 0.9rem; }}
  .meta code {{ color: #e6e6e6; background: #1c1f26; padding: 0.1rem 0.35rem; border-radius: 4px; }}
  .legend {{ display: flex; gap: 1.25rem; margin-bottom: 1.5rem; font-size: 0.85rem; }}
  .mock-banner {{ border: 2px solid #ffb74d; background: #4a3517; color: #ffe0b2; padding: 0.8rem 1rem; border-radius: 8px; margin: 1rem 0 1.5rem; }}
  .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
  .legend-swatch {{ width: 0.85rem; height: 0.85rem; border-radius: 3px; display: inline-block; }}
  .timeline {{
    display: flex; flex-wrap: wrap; gap: 1.1rem; align-items: flex-start;
    padding: 1rem; background: #161923; border-radius: 10px;
  }}
  .segment-wrap {{ display: flex; flex-direction: column; align-items: center; gap: 0.35rem; }}
  .segment {{
    width: 6.5rem; min-height: 5.5rem; border-radius: 8px; padding: 0.5rem;
    color: #10130d; display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: 0 1px 3px rgba(0,0,0,0.4); cursor: default;
  }}
  .segment-flaky {{ color: #241b00; }}
  .segment-index {{ font-size: 0.7rem; opacity: 0.7; }}
  .segment-label {{ font-weight: 700; font-size: 0.9rem; }}
  .segment-commit {{ font-family: ui-monospace, Menlo, monospace; font-size: 0.7rem; }}
  .segment-runs {{ font-size: 0.7rem; }}
  .segment-decision {{ font-size: 0.65rem; color: #9aa0a6; max-width: 7rem; text-align: center; }}
  .escalation {{ display: flex; gap: 0.2rem; }}
  .tier {{
    width: 1.4rem; height: 1.1rem; border-radius: 3px; font-size: 0.6rem;
    display: flex; align-items: center; justify-content: center; color: #10130d;
  }}
  .tier-pass {{ background: {_COLORS['pass']}; }}
  .tier-fail {{ background: {_COLORS['fail']}; }}
  .tier-flaky {{ background: {_COLORS['flaky']}; }}
  .substitution-badge {{
    font-size: 0.65rem; background: #2a2f3d; color: #8fd3ff; padding: 0.15rem 0.4rem;
    border-radius: 999px; white-space: nowrap;
  }}
  .gate-results {{ margin: -0.5rem 0 1.5rem; color: #c7cbd1; font-size: 0.85rem; }}
  .gate-results ul {{ margin: 0.35rem 0 0; padding-left: 1.25rem; }}
  details {{ margin-top: 2rem; }}
  summary {{ cursor: pointer; color: #9aa0a6; }}
  pre {{
    background: #161923; padding: 1rem; border-radius: 8px; overflow-x: auto;
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
