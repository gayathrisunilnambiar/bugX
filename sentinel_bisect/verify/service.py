from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from sentinel_bisect.orchestrator.models import Classification, TrialResult
from sentinel_bisect.orchestrator.runner import run_command


@dataclass(frozen=True)
class VerificationGate:
    """The result of one independently required verification command."""

    name: str
    command: str
    trial: TrialResult

    @property
    def passed(self) -> bool:
        return self.trial.classification == Classification.PASS

    def to_dict(self) -> dict[str, str | bool]:
        return {"name": self.name, "command": self.command, "classification": self.trial.classification.value, "passed": self.passed}


@dataclass(frozen=True)
class VerificationResult:
    applied: bool
    trial: TrialResult | None
    message: str
    gates: tuple[VerificationGate, ...] = ()

    @property
    def verified(self) -> bool:
        if not self.applied:
            return False
        if self.gates:
            return all(gate.passed for gate in self.gates)
        # Compatibility for callers constructing historical/simple results directly.
        return self.trial is not None and self.trial.classification == Classification.PASS

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(gate.name for gate in self.gates if not gate.passed)

    def gates_dict(self) -> list[dict[str, str | bool]]:
        return [gate.to_dict() for gate in self.gates]


def verify_patch(
    worktree: Path, patch: str, command: str, runs: int = 3, smoke_command: str | None = None,
    invariant_command: str | None = None,
) -> VerificationResult:
    applied = subprocess.run(["git", "apply", "--whitespace=fix", "-"], cwd=worktree, input=patch, text=True, capture_output=True, check=False)
    if applied.returncode:
        return VerificationResult(False, None, applied.stderr.strip())
    commands = [("target", command)]
    if smoke_command:
        commands.append(("smoke", smoke_command))
    if invariant_command:
        commands.append(("invariant", invariant_command))
    gates = tuple(VerificationGate(name, gate_command, run_command(gate_command, worktree, runs)) for name, gate_command in commands)
    failed = tuple(gate.name for gate in gates if not gate.passed)
    if failed:
        return VerificationResult(True, gates[0].trial, f"Verification gates failed: {', '.join(failed)}", gates)
    return VerificationResult(True, gates[0].trial, "Patch verified", gates)
