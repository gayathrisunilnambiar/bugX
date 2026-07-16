from __future__ import annotations

import logging
import shutil
from pathlib import Path

import click
from dotenv import load_dotenv

from sentinel_bisect.analysis import MissingApiKeyError, analyze_culprit
from sentinel_bisect.intake import derive_intent
from sentinel_bisect.orchestrator.engine import BisectEngine, UnresolvedFlakyCommit
from sentinel_bisect.orchestrator.git import disposable_worktree, git
from sentinel_bisect.orchestrator.models import DEFAULT_RERUN_SCHEDULE, parse_rerun_schedule
from sentinel_bisect.report import render_markdown
from sentinel_bisect.report.server import serve as serve_timeline
from sentinel_bisect.verify import verify_patch


@click.command()
@click.option("--repo", type=click.Path(path_type=Path, exists=True, file_okay=False), default=Path("."), show_default=True)
@click.option("--command", help="Shell command that reproduces the regression.")
@click.option("--report-file", type=click.Path(path_type=Path), default=Path("sentinel-report.md"), show_default=True)
@click.option("--trace-file", type=click.Path(path_type=Path), default=Path("sentinel-trace.json"), show_default=True)
@click.option(
    "--runs",
    default=None,
    type=click.IntRange(1, 20),
    help=f"Fixed rerun count, shorthand for a single-tier schedule. Overridden by --rerun-schedule. Default: adaptive {list(DEFAULT_RERUN_SCHEDULE)}.",
)
@click.option(
    "--rerun-schedule",
    default=None,
    help='Comma-separated escalation tiers, e.g. "3,7,15". A candidate is classified as soon as a tier is unanimous; '
    "mixed results escalate to the next tier. Takes precedence over --runs.",
)
@click.option("--good", help="Known-good commit. Defaults to the repository root.")
@click.option("--bad", help="Known-bad commit. Defaults to HEAD.")
@click.option("--bug-report", type=click.Path(path_type=Path, exists=True), help="Bug report used to infer command/range.")
@click.option("--analyze/--no-analyze", default=False, help="Request GPT-5.6 explanation and patch after bisection.")
@click.option("--verify/--no-verify", default=False, help="Apply and verify an LLM-proposed patch in a temporary worktree.")
@click.option("--serve/--no-serve", default=False, help="After the run completes, serve an HTML timeline visualization over HTTP.")
@click.option("--serve-port", default=8787, show_default=True, type=click.IntRange(1, 65535), help="Port for --serve.")
@click.option(
    "--runs-dir",
    type=click.Path(path_type=Path),
    default=Path("sentinel-runs"),
    show_default=True,
    help="Directory where per-run trace files are stored for --serve to discover.",
)
def main(
    repo: Path,
    command: str | None,
    report_file: Path,
    trace_file: Path,
    runs: int | None,
    rerun_schedule: str | None,
    good: str | None,
    bad: str | None,
    bug_report: Path | None,
    analyze: bool,
    verify: bool,
    serve: bool,
    serve_port: int,
    runs_dir: Path,
) -> None:
    """Find the first consistently failing commit without touching your checkout."""
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    intent = derive_intent(bug_report.read_text(encoding="utf-8")) if bug_report else None
    command = command or (intent.command if intent else None)
    if not command:
        raise click.UsageError("Provide --command or --bug-report")
    good = good or (intent.good if intent else None) or git(repo, "rev-list", "--max-parents=0", "HEAD").splitlines()[0]
    bad = bad or (intent.bad if intent else None) or "HEAD"
    if rerun_schedule is not None:
        try:
            schedule = parse_rerun_schedule(rerun_schedule)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
    elif runs is not None:
        schedule = (runs,)
    else:
        schedule = DEFAULT_RERUN_SCHEDULE
    try:
        result = BisectEngine(repo, command, rerun_schedule=schedule).search(good, bad, trace_file)
    except UnresolvedFlakyCommit as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        analysis = analyze_culprit(repo, result.culprit, result.trace[-1].outputs[-1]) if analyze else None
    except MissingApiKeyError as exc:
        raise click.ClickException(str(exc)) from exc
    verification = None
    if verify:
        if not analysis or not analysis.patch:
            raise click.ClickException("Verification requires a proposed patch; use --analyze and configure OPENAI_API_KEY")
        with disposable_worktree(repo, result.culprit) as worktree:
            verification = verify_patch(worktree, analysis.patch, command, runs or schedule[-1])
    report_file.write_text(render_markdown(result, analysis, verification), encoding="utf-8")
    click.echo(f"Culprit: {result.culprit}")
    click.echo(f"Report: {report_file}")
    if serve:
        run_id = result.run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        # Copy the trace this run just wrote into the runs directory the server
        # scans, keyed by run_id, so it's reachable at a stable /runs/{run_id} URL
        # without disturbing the user's --trace-file output.
        shutil.copy(trace_file, runs_dir / f"{run_id}.sentinel-trace.json")
        click.echo(f"Timeline: http://localhost:{serve_port}/runs/{run_id}/timeline")
        serve_timeline(runs_dir, port=serve_port)


if __name__ == "__main__":
    main()
