from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from sentinel_bisect.orchestrator.git import git


class MissingApiKeyError(RuntimeError):
    """Raised when an OpenAI-backed operation is requested without OPENAI_API_KEY configured."""


@dataclass(frozen=True)
class AnalysisResult:
    explanation: str
    patch: str
    source: str


def analyze_culprit(repo: Path, culprit: str, failing_output: str, model: str = "gpt-5.6") -> AnalysisResult:
    if not os.getenv("OPENAI_API_KEY"):
        raise MissingApiKeyError(
            "--analyze requires the OPENAI_API_KEY environment variable to be set. "
            "Set it (e.g. `export OPENAI_API_KEY=sk-...` or add it to .env) and rerun, "
            "or omit --analyze/--verify to use the offline bisection only."
        )
    diff = git(repo, "show", "--format=fuller", "--unified=5", culprit)
    try:
        from openai import OpenAI
        prompt = ("You are diagnosing a confirmed regression. Return JSON only: explanation (plain English) and patch "
                  "(a minimal unified diff, or empty if unsafe).\nCONFIRMED DIFF:\n" + diff + "\nFAILURE OUTPUT:\n" + failing_output[-6000:])
        response = OpenAI().responses.create(model=model, input=prompt)
        data = json.loads(response.output_text)
        return AnalysisResult(str(data.get("explanation", "")), str(data.get("patch", "")), "gpt-5.6")
    except Exception as exc:
        return AnalysisResult(f"Analysis request failed: {exc}", "", "error")
