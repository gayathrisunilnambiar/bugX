from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from sentinel_bisect.orchestrator.git import git

LOG = logging.getLogger(__name__)

# Explicit cache breakpoint on `_INSTRUCTIONS` (the stable prefix, identical across
# the base call and every escalation retry) — never the diff/failure output, which
# is per-run. Same 1h TTL rationale as intake/service.py.
_CACHE_OPTIONS = {"mode": "explicit", "ttl": "1h"}

# Judgment-heavy causal-diagnosis task: tier 1 of the Phase 2 escalation ladder
# (see analysis/escalation.py) starts at "high" effort rather than a lower default.
DEFAULT_ANALYSIS_MODEL = "gpt-5.6-sol"
DEFAULT_ANALYSIS_EFFORT = "high"

# Stable prefix shared by both the base call and every escalation retry — stating
# the JSON output contract once here (rather than repeating it in each `input`
# branch below) is both leaner and the cacheable part of the request across tiers
# (see DECISIONS.md's Phase 4/6 notes). No tools are exposed: this call only
# produces an explanation + patch text for verify/ to apply, it never acts directly.
_INSTRUCTIONS = (
    "You are diagnosing a confirmed regression. Return JSON only: explanation "
    "(plain English) and patch (a minimal unified diff, or empty if unsafe)."
)


class MissingApiKeyError(RuntimeError):
    """Raised when an OpenAI-backed operation is requested without OPENAI_API_KEY configured."""


@dataclass(frozen=True)
class AnalysisResult:
    explanation: str
    patch: str
    source: str
    response_id: str | None = None
    provider: str = "openai"


def analyze_culprit(
    repo: Path,
    culprit: str,
    failing_output: str,
    model: str | None = None,
    effort: str | None = None,
    mode: str | None = None,
    previous_response_id: str | None = None,
    retry_context: str | None = None,
) -> AnalysisResult:
    """Diagnose a confirmed regression and propose a patch.

    `previous_response_id` + `retry_context` are set on escalation retries (see
    analysis/escalation.py): the prior tier's failed attempt is referenced instead of
    resending the full diff, and `retry_context` carries why that attempt failed.
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise MissingApiKeyError(
            "--analyze requires the OPENAI_API_KEY environment variable to be set. "
            "Set it (e.g. `export OPENAI_API_KEY=sk-...` or add it to .env) and rerun, "
            "or omit --analyze/--verify to use the offline bisection only."
        )
    model = model or os.getenv("SENTINEL_ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODEL)
    reasoning: dict[str, str] = {}
    if effort:
        reasoning["effort"] = effort
    if mode:
        reasoning["mode"] = mode
    # Sized for the full Markdown report / HTML timeline this feeds (see
    # report/renderer.py, report/timeline.py) — the PR-comment formatter derives its
    # own shorter summary from this text instead of requesting a separate verbosity
    # (scripts/post_pr_comment.py; see DECISIONS.md).
    kwargs: dict[str, object] = {
        "model": model,
        "instructions": _INSTRUCTIONS,
        "text": {"verbosity": "medium"},
        "prompt_cache_options": _CACHE_OPTIONS,
    }
    if reasoning:
        kwargs["reasoning"] = reasoning if not previous_response_id else {**reasoning, "context": "all_turns"}
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
        # The prior response already carries the diff/failure context server-side;
        # only the new verification failure needs to be sent as input.
        kwargs["input"] = (
            "The previously proposed patch failed verification: " + (retry_context or "unknown reason") +
            "\nPropose a corrected patch."
        )
    else:
        diff = git(repo, "show", "--format=fuller", "--unified=5", culprit)
        kwargs["input"] = "CONFIRMED DIFF:\n" + diff + "\nFAILURE OUTPUT:\n" + failing_output[-6000:]
    try:
        response = OpenAI().responses.create(**kwargs)
        _log_cache_stats(model, response)
        data = json.loads(response.output_text)
        return AnalysisResult(
            str(data.get("explanation", "")), str(data.get("patch", "")), model, getattr(response, "id", None)
        )
    except Exception as exc:
        return AnalysisResult(f"Analysis request failed: {exc}", "", "error")


def _log_cache_stats(model: str, response: object) -> None:
    """Surface cache effectiveness in --debug output. Best-effort: fake response
    doubles in unit tests won't have `.usage`, and that's fine — nothing to log."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    LOG.debug(
        "analysis cache (%s): cached_tokens=%s cache_write_tokens=%s",
        model,
        getattr(usage, "cached_tokens", None),
        getattr(usage, "cache_write_tokens", None),
    )
