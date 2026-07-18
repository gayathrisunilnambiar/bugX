from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from openai import OpenAI

LOG = logging.getLogger(__name__)

# Explicit cache breakpoint on `_INSTRUCTIONS` (the stable prefix — never the raw bug
# report text, which varies per run). A 1h TTL comfortably covers repeated demo/
# judging runs in one sitting without caching indefinitely (see DECISIONS.md).
_CACHE_OPTIONS = {"mode": "explicit", "ttl": "1h"}

# Bounded, structured-extraction task: low reasoning effort is enough, escalate to
# "medium" only if low proves unreliable in testing (see DECISIONS.md).
DEFAULT_INTAKE_MODEL = "gpt-5.6-luna"
DEFAULT_INTAKE_EFFORT = "low"

# Stable prefix, no tools exposed (this call only extracts JSON, it never needs to
# act) — kept out of `input` so it's the cacheable part of the request (see
# analysis/escalation.py callers and DECISIONS.md's Phase 4/6 notes).
_INSTRUCTIONS = (
    "Extract regression investigation intent. Return JSON only with command, good, "
    "bad. Use null for unknown revisions. command must be a safe test command."
)


@dataclass(frozen=True)
class BugIntent:
    command: str
    good: str | None = None
    bad: str | None = None
    source: str = "heuristic"


def _heuristic(report: str) -> BugIntent:
    command_match = re.search(r"(?:command|reproduce|run)\s*[:`]\s*([^\n`]+)", report, re.I)
    test_match = re.search(r"(tests?/[^\s:]+(?:::[\w\[\]-]+)?)", report)
    command = command_match.group(1).strip() if command_match else f"pytest -q {test_match.group(1)}" if test_match else "pytest -q"
    good = re.search(r"(?:good|last known good)\s*(?:commit)?\s*[:=]\s*([0-9a-f]{7,40}|\S+)", report, re.I)
    bad = re.search(r"(?:bad|first seen)\s*(?:commit)?\s*[:=]\s*([0-9a-f]{7,40}|HEAD)", report, re.I)
    return BugIntent(command, good.group(1) if good else None, bad.group(1) if bad else None)


def derive_intent(
    report: str,
    model: str | None = None,
    effort: str | None = None,
) -> BugIntent:
    """Use GPT for unstructured intake when configured, otherwise remain useful offline."""
    fallback = _heuristic(report)
    if not os.getenv("OPENAI_API_KEY"):
        return fallback
    model = model or os.getenv("SENTINEL_INTAKE_MODEL", DEFAULT_INTAKE_MODEL)
    effort = effort or os.getenv("SENTINEL_INTAKE_EFFORT", DEFAULT_INTAKE_EFFORT)
    try:
        response = OpenAI().responses.create(
            model=model,
            reasoning={"effort": effort},
            instructions=_INSTRUCTIONS,
            input=report,
            prompt_cache_options=_CACHE_OPTIONS,
        )
        _log_cache_stats(model, response)
        data = json.loads(response.output_text)
        return BugIntent(str(data.get("command") or fallback.command), data.get("good"), data.get("bad"), model)
    except Exception:
        return fallback


def _log_cache_stats(model: str, response: object) -> None:
    """Surface cache effectiveness in --debug output. Best-effort: fake response
    doubles in unit tests won't have `.usage`, and that's fine — nothing to log."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    LOG.debug(
        "intake cache (%s): cached_tokens=%s cache_write_tokens=%s",
        model,
        getattr(usage, "cached_tokens", None),
        getattr(usage, "cache_write_tokens", None),
    )
