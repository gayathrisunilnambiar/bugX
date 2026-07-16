from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .git import commit_range, disposable_worktree
from .models import Classification, DEFAULT_RERUN_SCHEDULE, TraceStep, TrialResult
from .runner import run_command_with_schedule

LOG = logging.getLogger(__name__)


class UnresolvedFlakyCommit(RuntimeError):
    pass


@dataclass(frozen=True)
class BisectResult:
    culprit: str
    trace: list[TraceStep]


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

    def _trial(self, revision: str) -> TrialResult:
        with disposable_worktree(self.repo, revision) as worktree:
            return run_command_with_schedule(self.command, worktree, self.rerun_schedule)

    def search(self, good: str, bad: str, trace_path: Path | None = None) -> BisectResult:
        commits = commit_range(self.repo, good, bad)
        trace: list[TraceStep] = []
        low, high = -1, len(commits) - 1
        while high - low > 1:
            index = (low + high) // 2
            revision = commits[index]
            trial = self._trial(revision)
            step = TraceStep(
                revision,
                trial.classification,
                len(trial.attempts),
                [a.output for a in trial.attempts],
                0,
                "untrusted_flaky" if trial.classification == Classification.FLAKY else f"trusted_{trial.classification}",
                ["pass" if a.passed else "fail" for a in trial.attempts],
            )
            trace.append(step)
            LOG.info("tested %s: %s (%d attempts)", revision[:12], trial.classification, len(trial.attempts))
            if trial.classification == Classification.FLAKY:
                # A mixed result cannot be allowed to select a bisection branch.
                # Probe the immediately newer revision instead. It is accepted only
                # if stable; otherwise the evidence remains genuinely unresolved.
                neighbor_index = index + 1
                if neighbor_index > high:
                    self._write_trace(trace, trace_path)
                    raise UnresolvedFlakyCommit(f"Midpoint {revision} remained flaky with no stable neighboring probe")
                neighbor = commits[neighbor_index]
                neighbor_trial = self._trial(neighbor)
                neighbor_decision = "trusted_pass_after_flaky" if neighbor_trial.classification == Classification.PASS else "trusted_fail_after_flaky"
                trace.append(TraceStep(
                    neighbor,
                    neighbor_trial.classification,
                    len(neighbor_trial.attempts),
                    [a.output for a in neighbor_trial.attempts],
                    0,
                    neighbor_decision if neighbor_trial.classification != Classification.FLAKY else "untrusted_flaky_neighbor",
                    ["pass" if a.passed else "fail" for a in neighbor_trial.attempts],
                ))
                LOG.info("flaky midpoint %s excluded; neighboring probe %s: %s", revision[:12], neighbor[:12], neighbor_trial.classification)
                if neighbor_trial.classification == Classification.FLAKY:
                    self._write_trace(trace, trace_path)
                    raise UnresolvedFlakyCommit(f"Midpoint {revision} and neighboring probe {neighbor} are flaky")
                if neighbor_trial.classification == Classification.PASS:
                    low = neighbor_index
                else:
                    high = neighbor_index
                continue
            if trial.classification == Classification.PASS:
                low = index
            else:
                high = index
        result = BisectResult(culprit=commits[high], trace=trace)
        self._write_trace(trace, trace_path, result.culprit)
        return result

    @staticmethod
    def _write_trace(trace: list[TraceStep], path: Path | None, culprit: str | None = None) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"culprit": culprit, "steps": [step.to_dict() for step in trace]}, indent=2), encoding="utf-8")
