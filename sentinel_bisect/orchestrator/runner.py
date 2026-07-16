from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from .models import Attempt, Classification, TrialResult


def classify_attempts(attempts: list[Attempt]) -> Classification:
    """Classify repeated runs conservatively; mixed outcomes are flaky."""
    if not attempts:
        raise ValueError("At least one test attempt is required")
    outcomes = {attempt.passed for attempt in attempts}
    if outcomes == {True}:
        return Classification.PASS
    if outcomes == {False}:
        return Classification.FAIL
    return Classification.FLAKY


def _run_once(command: str, cwd: Path) -> Attempt:
    completed = subprocess.run(command, cwd=cwd, shell=True, text=True, capture_output=True, check=False)
    output = (completed.stdout + completed.stderr)[-12000:]
    return Attempt(returncode=completed.returncode, output=output)


def run_command(command: str, cwd: Path, runs: int) -> TrialResult:
    if runs < 1:
        raise ValueError("runs must be at least 1")
    attempts = [_run_once(command, cwd) for _ in range(runs)]
    return TrialResult(classification=classify_attempts(attempts), attempts=attempts)


def run_command_with_schedule(command: str, cwd: Path, rerun_schedule: Sequence[int]) -> TrialResult:
    """Classify a candidate using an adaptive escalation schedule of rerun counts.

    Each tier is a fresh, independent batch of runs (not appended to the previous
    tier's attempts): a bigger sample can resolve unanimously even when a smaller
    one didn't. A clean, unanimous result at the lowest tier resolves immediately
    without wasting time on larger tiers. Escalation to the next tier only happens
    when a tier's batch is mixed. If every tier is exhausted and still mixed, the
    trial is classified flaky using the final (largest) tier's attempts.
    """
    if not rerun_schedule:
        raise ValueError("rerun_schedule must contain at least one tier")
    attempts: list[Attempt] = []
    for tier in rerun_schedule:
        attempts = [_run_once(command, cwd) for _ in range(tier)]
        classification = classify_attempts(attempts)
        if classification != Classification.FLAKY:
            return TrialResult(classification=classification, attempts=attempts)
    return TrialResult(classification=Classification.FLAKY, attempts=attempts)
