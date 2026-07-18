"""Disclosed deterministic analysis double for the hard-regression fixture.

This module is deliberately opt-in.  It is not a fallback for unavailable API
credentials and models only the fixture's documented shared-parser defect.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from sentinel_bisect.analysis.costs import estimate_gpt_56_sol_cost
from sentinel_bisect.analysis.service import AnalysisResult
from sentinel_bisect.orchestrator.git import git


_BUGGY_HELPER = "return [int(part) for part in parts[:-1]]"
_MOCK_REQUEST_PREFIX = (
    "You are diagnosing a confirmed regression. Return JSON only: explanation "
    "(plain English) and patch (a minimal unified diff, or empty if unsafe)."
)


def mock_analyze_culprit(
    repo: Path,
    culprit: str,
    failing_output: str,
    model: str | None = None,
    effort: str | None = None,
    mode: str | None = None,
    previous_response_id: str | None = None,
    retry_context: str | None = None,
) -> AnalysisResult:
    """Return a deterministic control patch for the documented parser defect.

    The tier is derived from the same effort/mode inputs as the live provider. On
    retries the preceding mock response id is required, exercising the same context
    threading contract as the live call. The fixture source is inspected before a
    patch is offered; this is not a tier-number lookup table detached from the bug.
    """
    tier = _tier_for(effort, mode)
    if tier > 1 and not (previous_response_id or "").startswith(f"mock-hard-parser-tier{tier - 1}"):
        raise ValueError(f"mock tier{tier} requires the preceding mock response id")
    if tier > 1 and not retry_context:
        raise ValueError(f"mock tier{tier} requires verification feedback")

    source = git(repo, "show", f"{culprit}:calculator.py")
    if "def _parse_values" not in source or _BUGGY_HELPER not in source:
        return AnalysisResult(
            "Mock analysis only supports the disclosed hard-regression parser defect.",
            "",
            model or "mock",
            f"mock-hard-parser-tier{tier}",
            "mock",
            estimate_gpt_56_sol_cost(_MOCK_REQUEST_PREFIX + source + failing_output, ""),
        )

    if tier == 1:
        replacement = source.replace(
            "def parse_total(text: str) -> int:\n    return sum(_parse_values(text))",
            "def parse_total(text: str) -> int:\n    if text == '1, 2, 3':\n        return 6\n    return sum(_parse_values(text))",
        ).replace(
            "def parse_average(text: str) -> float:\n    values = _parse_values(text)",
            "def parse_average(text: str) -> float:\n    if text == '2, 4, 6':\n        return 4\n    values = _parse_values(text)",
        )
        explanation = "Mock control tier 1 hardcodes the two reported wrapper examples; the shared parser remains defective."
    elif tier == 2:
        replacement = source.replace(_BUGGY_HELPER, "return [int(part) for part in parts[:3]]")
        explanation = "Mock control tier 2 restores up to three values, which covers target and smoke but still truncates longer valid sequences."
    else:
        replacement = source.replace(_BUGGY_HELPER, "return [int(part) for part in parts]")
        explanation = "Mock control tier 3 fixes the shared helper by parsing every validated segment."

    # Keep this tied to the real inputs and generated control output. It is a
    # structural estimate only (not a tokenizer or billing measurement), which the
    # reporting layer repeats verbatim wherever it displays a dollar amount.
    request_text = _MOCK_REQUEST_PREFIX + (retry_context or "")
    if not previous_response_id:
        request_text += source + failing_output
    patch = _unified_patch(source, replacement)
    return AnalysisResult(
        explanation,
        patch,
        model or "mock",
        f"mock-hard-parser-tier{tier}",
        "mock",
        estimate_gpt_56_sol_cost(request_text, explanation + patch),
    )


def _tier_for(effort: str | None, mode: str | None) -> int:
    if mode == "pro":
        return 3
    if effort == "xhigh":
        return 2
    if effort == "high":
        return 1
    raise ValueError("mock analysis requires a recognized escalation tier")


def _unified_patch(before: str, after: str) -> str:
    # git() returns stripped stdout; restore the tracked file's terminal newline so
    # difflib emits a patch git apply can consume rather than a no-newline hunk.
    before = before if before.endswith("\n") else before + "\n"
    after = after if after.endswith("\n") else after + "\n"
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), "a/calculator.py", "b/calculator.py"))
