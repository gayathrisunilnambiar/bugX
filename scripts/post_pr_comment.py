"""Post a compact Sentinel Bisect summary as a PR comment.

Reads the JSON trace a bisection run wrote (see `orchestrator/engine.py`),
formats a short, comment-sized summary (full Markdown report and JSON trace
are left as workflow artifacts rather than pasted in full), and posts it
via the `gh` CLI, which ships preinstalled on GitHub-hosted runners — this
avoids depending on a third-party comment-posting Action.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


_EXPLANATION_MAX_CHARS = 240


def _truncate_explanation(explanation: str, max_chars: int = _EXPLANATION_MAX_CHARS) -> str:
    """Derive a comment-sized summary from the full analysis explanation via simple
    truncation rather than a second, separately-requested low-verbosity API call —
    cheaper and deterministic for text that's already in hand (see DECISIONS.md).
    Prefers cutting at the first sentence boundary; falls back to a hard char cap.
    """
    explanation = explanation.strip()
    if len(explanation) <= max_chars:
        return explanation
    first_sentence_end = explanation.find(". ")
    if 0 < first_sentence_end < max_chars:
        return explanation[: first_sentence_end + 1]
    return explanation[: max_chars - 1].rstrip() + "…"


def _commit_subject(repo: Path, sha: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", "-s", "--format=%s", sha],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "(commit subject unavailable)"


def build_comment(trace: dict, repo: Path, run_url: str | None, artifact_name: str | None) -> str:
    culprit = trace.get("culprit")
    steps = trace.get("steps", [])
    flaky_count = sum(1 for step in steps if step.get("classification") == "flaky")
    substitution_count = sum(1 for step in steps if step.get("substitute_for"))

    lines = ["### 🔍 Sentinel Bisect result", ""]
    if culprit:
        subject = _commit_subject(repo, culprit)
        lines.append(f"**Introducing commit:** `{culprit[:12]}` — {subject}")
    else:
        lines.append("**No confirmed culprit** — the search did not resolve to a single commit.")
    lines.append(
        f"Searched {len(steps)} decision point(s); {flaky_count} flaky, {substitution_count} routed around via substitution."
    )
    analysis = trace.get("analysis") or {}
    attempts = analysis.get("attempts") or []
    if attempts:
        final = attempts[-1]
        explanation = final.get("explanation")
        if explanation:
            verdict = "verified fix" if final.get("verified") else "unverified — needs review"
            lines.append("")
            lines.append(f"**Analysis ({verdict}):** {_truncate_explanation(explanation)}")
    links = []
    if artifact_name:
        links.append(f"Full Markdown report, JSON trace, and HTML timeline are attached as the `{artifact_name}` workflow artifact.")
    if run_url:
        links.append(f"[View workflow run]({run_url})")
    if links:
        lines.append("")
        lines.extend(links)
    lines.append("")
    lines.append("<sub>Posted automatically by the `sentinel-bisect` GitHub Action.</sub>")
    return "\n".join(lines)


def post_comment(pr_number: str, repo_slug: str, body: str) -> None:
    subprocess.run(
        ["gh", "pr", "comment", pr_number, "--repo", repo_slug, "--body-file", "-"],
        input=body,
        text=True,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-file", type=Path, required=True, help="Path to the JSON trace written by sentinel-bisect.")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Path to the git repository the bisection ran against.")
    parser.add_argument("--pr-number", required=True, help="PR number to comment on.")
    parser.add_argument("--github-repo", required=True, help='"owner/repo" slug, e.g. from $GITHUB_REPOSITORY.')
    parser.add_argument("--run-url", default=None, help="URL of the workflow run, for a link back to full logs/artifacts.")
    parser.add_argument("--artifact-name", default=None, help="Name of the uploaded workflow artifact containing the full report.")
    parser.add_argument("--dry-run", action="store_true", help="Print the comment instead of posting it.")
    args = parser.parse_args()

    trace = json.loads(args.trace_file.read_text(encoding="utf-8"))
    body = build_comment(trace, args.repo, args.run_url, args.artifact_name)

    if args.dry_run:
        print(body)
        return

    post_comment(args.pr_number, args.github_repo, body)


if __name__ == "__main__":
    main()
