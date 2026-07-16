from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

DEFAULT_RERUN_SCHEDULE: tuple[int, ...] = (3, 7, 15)


def parse_rerun_schedule(raw: str) -> tuple[int, ...]:
    """Parse a comma-separated escalation schedule like "3,7,15" into strictly increasing tiers."""
    try:
        tiers = tuple(int(part.strip()) for part in raw.split(","))
    except ValueError as exc:
        raise ValueError(f"rerun schedule must be comma-separated integers, got {raw!r}") from exc
    if not tiers:
        raise ValueError("rerun schedule must contain at least one tier")
    if any(tier < 1 for tier in tiers):
        raise ValueError("rerun schedule tiers must each be >= 1")
    if list(tiers) != sorted(set(tiers)):
        raise ValueError("rerun schedule tiers must be strictly increasing with no duplicates")
    return tiers


class Classification(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    FLAKY = "flaky"


@dataclass(frozen=True)
class Attempt:
    returncode: int
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class TrialResult:
    classification: Classification
    attempts: list[Attempt]

    def to_dict(self) -> dict[str, object]:
        return {"classification": self.classification, "attempts": [asdict(a) for a in self.attempts]}


@dataclass(frozen=True)
class TraceStep:
    commit: str
    classification: Classification
    attempt_count: int
    outputs: list[str]
    retry: int = 0
    decision: str = "trusted"
    outcomes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        # Keep the classification evidence together at the top of JSON traces;
        # captured command output follows for readers who need raw diagnostics.
        return {
            "commit": self.commit,
            "classification": self.classification,
            "attempt_count": self.attempt_count,
            "outcomes": self.outcomes,
            "decision": self.decision,
            "retry": self.retry,
            "outputs": self.outputs,
        }
