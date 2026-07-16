from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from sentinel_bisect.orchestrator.models import Classification, TrialResult
from sentinel_bisect.orchestrator.runner import run_command


@dataclass(frozen=True)
class VerificationResult:
    applied: bool
    trial: TrialResult | None
    message: str

    @property
    def verified(self) -> bool:
        return self.applied and self.trial is not None and self.trial.classification == Classification.PASS


def verify_patch(worktree: Path, patch: str, command: str, runs: int = 3, smoke_command: str | None = None) -> VerificationResult:
    applied = subprocess.run(["git", "apply", "--whitespace=fix", "-"], cwd=worktree, input=patch, text=True, capture_output=True, check=False)
    if applied.returncode:
        return VerificationResult(False, None, applied.stderr.strip())
    trial = run_command(command, worktree, runs)
    if trial.classification != Classification.PASS:
        return VerificationResult(True, trial, "Target test did not pass consistently")
    if smoke_command:
        smoke = run_command(smoke_command, worktree, runs)
        if smoke.classification != Classification.PASS:
            return VerificationResult(True, smoke, "Smoke test did not pass consistently")
    return VerificationResult(True, trial, "Patch verified")
