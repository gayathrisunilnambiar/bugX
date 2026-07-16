from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from .git import commit_range, disposable_worktree
from .models import Classification, DEFAULT_RERUN_SCHEDULE, TraceStep, TrialResult
from .runner import run_command_with_schedule

LOG = logging.getLogger(__name__)


class UnresolvedFlakyCommit(RuntimeError):
    """Raised only when a flaky decision point cannot be routed around because the
    entire remaining search range is persistently flaky — a rare terminal state."""


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

    def search(self, good: str, bad: str, trace_path: Path | None = None) -> BisectResult:
        commits = self._commits(good, bad)
        trace: list[TraceStep] = []
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
        self._write_trace(trace, trace_path, culprit, run_id)
        return BisectResult(culprit=culprit, trace=trace, run_id=run_id)

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
        LOG.info("tested %s: %s (%d attempts)", revision[:12], trial.classification, len(trial.attempts))
        if trial.classification != Classification.FLAKY:
            trace.append(self._step(revision, trial, f"trusted_{trial.classification}"))
            return index, trial.classification

        # Midpoint stayed flaky even after the full escalation schedule. Do not stop:
        # route around it using an adjacent commit as a substitute decision point.
        trace.append(self._step(revision, trial, "untrusted_flaky"))
        LOG.info("midpoint %s unresolved after escalation; routing around", revision[:12])
        for candidate in self._substitution_order(index, low, high):
            substitute = commits[candidate]
            sub_trial = self._trial(substitute)
            if sub_trial.classification == Classification.FLAKY:
                trace.append(self._step(substitute, sub_trial, "untrusted_flaky", substitute_for=revision))
                LOG.info("substitute probe %s also flaky; trying next", substitute[:12])
                continue
            decision = f"substituted_{sub_trial.classification}"
            trace.append(self._step(substitute, sub_trial, decision, substitute_for=revision))
            LOG.info("routed around %s using substitute %s: %s", revision[:12], substitute[:12], sub_trial.classification)
            return candidate, sub_trial.classification

        # Every interior commit in the remaining range is persistently flaky: this is
        # the rare terminal state where automated routing is impossible.
        self._write_trace(trace, trace_path)
        raise UnresolvedFlakyCommit(
            f"Commit {revision} and every substitute in the remaining range are persistently flaky; human guidance required"
        )

    @staticmethod
    def _write_trace(trace: list[TraceStep], path: Path | None, culprit: str | None = None, run_id: str | None = None) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"run_id": run_id or _make_run_id(culprit), "culprit": culprit, "steps": [step.to_dict() for step in trace]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
