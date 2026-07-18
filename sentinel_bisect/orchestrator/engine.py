from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from .git import commit_range, disposable_worktree
from .models import Classification, DEFAULT_RERUN_SCHEDULE, TraceStep, TrialResult
from .metrics import bisection_efficiency
from .runner import run_command_with_schedule

LOG = logging.getLogger(__name__)


class BisectionError(RuntimeError):
    """Base for conditions that abort a search with a clear, user-facing explanation
    rather than returning a misleading culprit or crashing with a stack trace."""


class UnresolvedFlakyCommit(BisectionError):
    """Raised only when a flaky decision point cannot be routed around because the
    entire remaining search range is persistently flaky — a rare terminal state."""


class NoRegressionFound(BisectionError):
    """The bad commit passes the reproduction command: there is nothing to bisect."""


class UnreliableBaseline(BisectionError):
    """A good/bad anchor could not be trusted (flaky, or good already fails), so the
    search has no dependable boundary to bisect between."""


class ReproductionCommandError(BisectionError):
    """The reproduction command could not be executed (e.g. command not found): an
    environment/command problem rather than a genuine test failure."""


class EmptyRange(BisectionError):
    """The good..bad range contains no commits (good and bad are the same or reversed)."""


def _make_run_id(culprit: str | None) -> str:
    """A sortable, human-readable id minted when a trace is written: a UTC
    timestamp plus a short commit fingerprint so URLs stay unique per run."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fingerprint = (culprit or "unresolved")[:7]
    return f"{stamp}-{fingerprint}"


@dataclass(frozen=True)
class BisectResult:
    culprit: str
    trace: list[TraceStep]
    run_id: str | None = None
    range_commit_count: int = 1

    @property
    def efficiency(self) -> dict[str, int]:
        return bisection_efficiency(self.range_commit_count, [step.to_dict() for step in self.trace])


class BisectEngine:
    def __init__(
        self,
        repo: Path,
        command: str,
        runs: int | None = None,
        rerun_schedule: Sequence[int] | None = None,
    ) -> None:
        """Configure the escalation schedule used to classify each candidate commit.

        `rerun_schedule` takes precedence when given. `runs` is retained as a
        backward-compatible shorthand for a single-tier schedule `(runs,)`. If
        neither is given, the schedule defaults to DEFAULT_RERUN_SCHEDULE.
        """
        if rerun_schedule is not None:
            schedule = tuple(rerun_schedule)
        elif runs is not None:
            schedule = (runs,)
        else:
            schedule = DEFAULT_RERUN_SCHEDULE
        self.repo, self.command, self.rerun_schedule = repo.resolve(), command, schedule

    def _commits(self, good: str, bad: str) -> list[str]:
        return commit_range(self.repo, good, bad)

    def _trial(self, revision: str) -> TrialResult:
        with disposable_worktree(self.repo, revision) as worktree:
            return run_command_with_schedule(self.command, worktree, self.rerun_schedule)

    @staticmethod
    def _step(revision: str, trial: TrialResult, decision: str, substitute_for: str | None = None) -> TraceStep:
        return TraceStep(
            commit=revision,
            classification=trial.classification,
            attempt_count=len(trial.attempts),
            outputs=[a.output for a in trial.attempts],
            retry=max(0, len(trial.escalation) - 1),
            decision=decision,
            outcomes=["pass" if a.passed else "fail" for a in trial.attempts],
            escalation=list(trial.escalation),
            substitute_for=substitute_for,
        )

    @staticmethod
    def _substitution_order(index: int, low: int, high: int) -> Iterator[int]:
        """Yield interior candidate indices in ``(low, high)`` nearest to ``index``
        first, alternating toward the unexplored newer (bad) side before the older
        (good) side. Excludes the flaky ``index`` itself and both known boundaries."""
        offset = 1
        while True:
            emitted = False
            for candidate in (index + offset, index - offset):
                if low < candidate < high:
                    emitted = True
                    yield candidate
            if not emitted:
                return
            offset += 1

    @staticmethod
    def _command_run_error(trial: TrialResult) -> bool:
        """True when every attempt exited 126/127 — the shell could not run the
        command (not executable / not found), an environment problem rather than a
        genuine test failure that should steer the search."""
        return bool(trial.attempts) and all(a.returncode in (126, 127) for a in trial.attempts)

    def search(self, good: str, bad: str, trace_path: Path | None = None) -> BisectResult:
        try:
            commits = self._commits(good, bad)
        except ValueError as exc:
            raise EmptyRange(
                f"No commits to search between {good!r} and {bad!r}: the range is empty. "
                "good and bad may be the same commit, or reversed — provide a good commit that is an "
                "ancestor of a distinct bad commit."
            ) from exc

        trace: list[TraceStep] = []
        # Anchor verification. The binary search below assumes good truly passes and
        # bad truly fails; it never revisits them. Verify both first so we never
        # report a misleading culprit for a range with no regression, search from an
        # untrustworthy (flaky) baseline, or mistake a broken command for a failure.
        self._verify_anchor(good, "baseline", trace, trace_path)
        bad_rev = commits[-1]
        self._verify_anchor(bad_rev, "anchor", trace, trace_path)

        low, high = -1, len(commits) - 1
        while high - low > 1:
            index = (low + high) // 2
            decision_index, classification = self._decide(commits, index, low, high, trace, trace_path)
            if classification == Classification.PASS:
                low = decision_index
            else:
                high = decision_index
        culprit = commits[high]
        run_id = _make_run_id(culprit)
        self._write_trace(trace, trace_path, culprit, run_id, len(commits))
        LOG.info("========== CULPRIT CONFIRMED: %s ==========", culprit)
        return BisectResult(culprit=culprit, trace=trace, run_id=run_id, range_commit_count=len(commits))

    def _verify_anchor(self, revision: str, role: str, trace: list[TraceStep], trace_path: Path | None) -> None:
        """Test a good ('baseline') or bad ('anchor') boundary commit and abort with a
        clear error if it cannot be trusted. good must consistently pass; bad must
        consistently fail. Either being flaky, or the command failing to run, or a
        good that already fails / a bad that already passes, is reported explicitly."""
        trial = self._trial(revision)
        trace.append(self._step(revision, trial, f"{role}_{trial.classification}"))
        LOG.info("%s %s: %s", role, revision[:12], trial.classification)

        if self._command_run_error(trial):
            self._write_trace(trace, trace_path)
            raise ReproductionCommandError(
                f"The reproduction command failed to run at {revision[:12]} "
                f"(exit code {trial.attempts[-1].returncode}, e.g. command not found). This is a "
                "command/environment problem, not a test failure — check the command and try again."
            )
        if trial.classification == Classification.FLAKY:
            self._write_trace(trace, trace_path)
            noun = "good baseline" if role == "baseline" else "bad commit"
            raise UnreliableBaseline(
                f"Cannot establish a reliable baseline: the {noun} {revision[:12]} is flaky (its result is "
                "not consistent across reruns). Bisection needs trustworthy passing and failing anchors."
            )
        if role == "baseline" and trial.classification == Classification.FAIL:
            self._write_trace(trace, trace_path)
            raise UnreliableBaseline(
                f"The good baseline {revision[:12]} already fails the reproduction command. The regression "
                "may predate this range, or the command may be misconfigured (e.g. a wrong test path). Pick "
                "an earlier good commit, or check the command."
            )
        if role == "anchor" and trial.classification == Classification.PASS:
            self._write_trace(trace, trace_path)
            raise NoRegressionFound(
                f"No regression found in the given range: the bad commit {revision[:12]} passes the "
                "reproduction command, the same outcome as the good baseline. There is nothing to bisect."
            )

    def _decide(
        self,
        commits: list[str],
        index: int,
        low: int,
        high: int,
        trace: list[TraceStep],
        trace_path: Path | None,
    ) -> tuple[int, Classification]:
        """Resolve a trusted pass/fail decision at (or near) ``index``.

        The midpoint is tried first; its escalation schedule already re-runs it at
        larger rerun counts before returning FLAKY. If it is still flaky, route
        around it by probing the nearest interior commits until one resolves to a
        confident pass/fail, recording the substitution. Only if every substitute in
        the remaining range is also flaky do we fall back to human guidance.
        """
        revision = commits[index]
        trial = self._trial(revision)
        if trial.classification == Classification.FLAKY:
            tiers = " -> ".join(str(tier.runs) for tier in trial.escalation)
            LOG.info(
                "[FLAKY] %s  mixed results after %d attempts (rerun tiers: %s)",
                revision[:12], len(trial.attempts), tiers,
            )
        else:
            LOG.info("[%s] %s  consistent after %d attempts", trial.classification.upper(), revision[:12], len(trial.attempts))
        if trial.classification != Classification.FLAKY:
            trace.append(self._step(revision, trial, f"trusted_{trial.classification}"))
            return index, trial.classification

        # Midpoint stayed flaky even after the full escalation schedule. Do not stop:
        # route around it using an adjacent commit as a substitute decision point.
        trace.append(self._step(revision, trial, "untrusted_flaky"))
        LOG.info("[FLAKY] %s  unresolved after the configured rerun schedule; routing around", revision[:12])
        for candidate in self._substitution_order(index, low, high):
            substitute = commits[candidate]
            sub_trial = self._trial(substitute)
            if sub_trial.classification == Classification.FLAKY:
                trace.append(self._step(substitute, sub_trial, "untrusted_flaky", substitute_for=revision))
                LOG.info("[FLAKY] substitute %s  also mixed; trying the next candidate", substitute[:12])
                continue
            decision = f"substituted_{sub_trial.classification}"
            trace.append(self._step(substitute, sub_trial, decision, substitute_for=revision))
            LOG.info("[ROUTED] %s  substitute %s is %s", revision[:12], substitute[:12], sub_trial.classification.upper())
            return candidate, sub_trial.classification

        # Every interior commit in the remaining range is persistently flaky: this is
        # the rare terminal state where automated routing is impossible.
        self._write_trace(trace, trace_path)
        raise UnresolvedFlakyCommit(
            f"Commit {revision} and every substitute in the remaining range are persistently flaky; human guidance required"
        )

    @staticmethod
    def _write_trace(trace: list[TraceStep], path: Path | None, culprit: str | None = None, run_id: str | None = None, range_commit_count: int | None = None) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        steps = [step.to_dict() for step in trace]
        payload: dict[str, object] = {"run_id": run_id or _make_run_id(culprit), "culprit": culprit, "steps": steps}
        if range_commit_count is not None:
            payload["bisection_efficiency"] = bisection_efficiency(range_commit_count, steps)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
