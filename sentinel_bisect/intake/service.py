from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


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


def derive_intent(report: str, model: str = "gpt-5.6") -> BugIntent:
    """Use GPT for unstructured intake when configured, otherwise remain useful offline."""
    fallback = _heuristic(report)
    if not os.getenv("OPENAI_API_KEY"):
        return fallback
    try:
        from openai import OpenAI
        response = OpenAI().responses.create(
            model=model,
            input=("Extract regression investigation intent. Return JSON only with command, good, bad. "
                   "Use null for unknown revisions. Command must be a safe test command. Bug report:\n" + report),
        )
        data = json.loads(response.output_text)
        return BugIntent(str(data.get("command") or fallback.command), data.get("good"), data.get("bad"), "gpt-5.6")
    except Exception:
        return fallback
