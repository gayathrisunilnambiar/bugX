from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import click
from dotenv import load_dotenv

from sentinel_bisect.analysis import DEFAULT_TIERS, MissingApiKeyError, Tier, analyze_culprit, run_escalation
from sentinel_bisect.analysis.escalation import EscalationOutcome
from sentinel_bisect.analysis.service import DEFAULT_ANALYSIS_MODEL
from sentinel_bisect.intake import derive_intent
from sentinel_bisect.intake.service import DEFAULT_INTAKE_MODEL
from sentinel_bisect.orchestrator.engine import BisectEngine, BisectionError
from sentinel_bisect.orchestrator.git import git
from sentinel_bisect.orchestrator.models import DEFAULT_RERUN_SCHEDULE, parse_rerun_schedule
from sentinel_bisect.report import render_markdown
from sentinel_bisect.report.server import serve as serve_timeline


def _tiers_for(model: str | None) -> tuple[Tier, ...]:
    """Apply an --analysis-model override across every rung of the escalation
    ladder, keeping each tier's effort/mode as defined in DEFAULT_TIERS."""
    if not model:
        return DEFAULT_TIERS
    return tuple(Tier(t.name, model, t.effort, t.mode) for t in DEFAULT_TIERS)


def _augment_trace_with_analysis(trace_file: Path, escalation: EscalationOutcome) -> None:
    """The JSON trace is written by BisectEngine.search() before analysis runs; add
    the escalation ladder's outcome to it afterward so it's visible in the trace the
    same way rerun-count escalation events already are, not just in the Markdown
    report."""
    if not trace_file.exists():
        return
    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    payload["analysis"] = escalation.to_dict()
    trace_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
@click.option(
    "--intake-model",
    default=None,
    help=f"Model used for --bug-report intake. Default: {DEFAULT_INTAKE_MODEL} "
    "(or $SENTINEL_INTAKE_MODEL if set).",
)
@click.option(
    "--analysis-model",
    default=None,
    help=f"Model used for --analyze/--verify. Default: {DEFAULT_ANALYSIS_MODEL} "
    "(or $SENTINEL_ANALYSIS_MODEL if set).",
)
@click.option(
    "--max-analysis-tier",
    default=None,
    type=click.IntRange(1, len(DEFAULT_TIERS)),
    help=f"Cap the reasoning-effort escalation ladder used by --analyze/--verify at this tier "
    f"(1-{len(DEFAULT_TIERS)}). Default: allow all tiers.",
)
@click.option(
    "--smoke-command",
    default=None,
    help="Extra command --verify must also pass, alongside the reproduction target. "
    "Catches a patch that fixes the reported failure but breaks something else.",
)
@click.option(
    "--invariant-command",
    default=None,
    help="Property-based or parameterized command --verify must also pass, proving a general invariant beyond target and smoke examples.",
)
@click.option("--serve/--no-serve", default=False, help="After the run completes, serve an HTML timeline visualization over HTTP.")
@click.option("--serve-port", default=8787, show_default=True, type=click.IntRange(1, 65535), help="Port for --serve.")
@click.option(
    "--serve-host",
    default="127.0.0.1",
    show_default=True,
    help="Bind address for --serve. Use 0.0.0.0 to accept connections from outside the process "
    "(e.g. from the host when running inside Docker with -p).",
)
@click.option(
    "--runs-dir",
    type=click.Path(path_type=Path),
    default=Path("sentinel-runs"),
    show_default=True,
    help="Directory where per-run trace files are stored for --serve to discover.",
)
@click.option(
    "--debug/--no-debug",
    default=False,
    help="Verbose logging, including per-call cached_tokens/cache_write_tokens from GPT-5.6 responses.",
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
    intake_model: str | None,
    analysis_model: str | None,
    max_analysis_tier: int | None,
    smoke_command: str | None,
    invariant_command: str | None,
    serve: bool,
    serve_port: int,
    serve_host: str,
    runs_dir: Path,
    debug: bool,
) -> None:
    """Find the first consistently failing commit without touching your checkout."""
    load_dotenv()
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, format="%(levelname)s %(message)s")
    intent = derive_intent(bug_report.read_text(encoding="utf-8"), model=intake_model) if bug_report else None
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
    except BisectionError as exc:
        raise click.ClickException(str(exc)) from exc

    tiers = _tiers_for(analysis_model)
    analysis = None
    verification = None
    escalation = None
    if analyze and verify:
        # Escalates reasoning effort tier-by-tier on verification failure; only
        # reports an unverified/failed state after every usable tier is exhausted
        # (see analysis/escalation.py). Never raises on exhaustion — the report
        # must show *why* it failed, not crash or silently accept a bad patch.
        try:
            escalation = run_escalation(
                repo,
                result.culprit,
                result.trace[-1].outputs[-1],
                command,
                runs=runs or schedule[-1],
                smoke_command=smoke_command,
                invariant_command=invariant_command,
                tiers=tiers,
                max_tier=max_analysis_tier,
            )
        except MissingApiKeyError as exc:
            raise click.ClickException(str(exc)) from exc
        analysis = escalation.final.analysis
        verification = escalation.final.verification
        _augment_trace_with_analysis(trace_file, escalation)
    elif analyze:
        try:
            analysis = analyze_culprit(
                repo, result.culprit, result.trace[-1].outputs[-1], model=tiers[0].model, effort=tiers[0].effort
            )
        except MissingApiKeyError as exc:
            raise click.ClickException(str(exc)) from exc
    elif verify:
        raise click.ClickException("Verification requires a proposed patch; use --analyze and configure OPENAI_API_KEY")

    report_file.write_text(render_markdown(result, analysis, verification, escalation), encoding="utf-8")
    click.echo(f"Culprit: {result.culprit}")
    click.echo(f"Report: {report_file}")
    if serve:
        run_id = result.run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        # Copy the trace this run just wrote into the runs directory the server
        # scans, keyed by run_id, so it's reachable at a stable /runs/{run_id} URL
        # without disturbing the user's --trace-file output.
        shutil.copy(trace_file, runs_dir / f"{run_id}.sentinel-trace.json")
        # Always print a localhost URL even when bound to 0.0.0.0 (e.g. in Docker):
        # that's the address a judge on the host actually opens, via -p port mapping.
        click.echo(f"Timeline: http://localhost:{serve_port}/runs/{run_id}/timeline")
        serve_timeline(runs_dir, host=serve_host, port=serve_port)


if __name__ == "__main__":
    main()
