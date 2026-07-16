from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sentinel_bisect.orchestrator.engine import BisectEngine, UnresolvedFlakyCommit
from sentinel_bisect.orchestrator.git import git
from sentinel_bisect.orchestrator.models import Attempt, Classification, TierAttempt, TrialResult


def _trial_for(classification: Classification, escalation: list[Classification] | None = None) -> TrialResult:
    """Build a TrialResult with attempts consistent with the desired final
    classification, plus an optional per-tier escalation history."""
    if classification == Classification.PASS:
        attempts = [Attempt(0, ""), Attempt(0, "")]
    elif classification == Classification.FAIL:
        attempts = [Attempt(1, ""), Attempt(1, "")]
    else:
        attempts = [Attempt(1, ""), Attempt(0, "")]
    tiers = [
        TierAttempt(runs=2, classification=c, outcomes=["fail", "pass"] if c == Classification.FLAKY else [str(c)])
        for c in (escalation or [classification])
    ]
    return TrialResult(classification=classification, attempts=attempts, escalation=tiers)


class ScriptedEngine(BisectEngine):
    """Engine double: a fixed commit list and a per-commit canned trial result, so
    search/substitution routing can be exercised without a real git repository."""

    def __init__(self, commits: list[str], trials: dict[str, TrialResult]) -> None:
        self.repo, self.command, self.rerun_schedule = Path("."), "cmd", (2,)
        self._scripted_commits = commits
        self._trials = trials

    def _commits(self, good: str, bad: str) -> list[str]:
        return self._scripted_commits

    def _trial(self, revision: str) -> TrialResult:
        return self._trials[revision]


def test_commit_resolves_after_escalation_without_substitution() -> None:
    commits = ["c0", "c1", "c2", "c3", "c4"]
    trials = {
        "c0": _trial_for(Classification.PASS),
        # Midpoint resolves to PASS only after escalating 2 -> 4 reruns.
        "c1": _trial_for(Classification.PASS, escalation=[Classification.FLAKY, Classification.PASS]),
        "c2": _trial_for(Classification.FAIL),
        "c3": _trial_for(Classification.FAIL),
        "c4": _trial_for(Classification.FAIL),
    }
    result = ScriptedEngine(commits, trials).search("good", "bad")
    assert result.culprit == "c2"
    c1_step = next(step for step in result.trace if step.commit == "c1")
    assert len(c1_step.escalation) == 2
    assert c1_step.escalation[0].classification == Classification.FLAKY
    assert c1_step.escalation[-1].classification == Classification.PASS
    assert c1_step.classification == Classification.PASS
    assert all(step.substitute_for is None for step in result.trace)


def test_persistently_flaky_commit_is_routed_around_via_substitution() -> None:
    commits = ["c0", "c1", "c2", "c3", "c4"]
    trials = {
        # First midpoint (c1) stays flaky through the whole schedule; the nearest
        # interior substitute toward the bad side (c2) resolves cleanly to PASS,
        # letting the search route past c1 instead of stalling.
        "c0": _trial_for(Classification.PASS),
        "c1": _trial_for(Classification.FLAKY, escalation=[Classification.FLAKY, Classification.FLAKY]),
        "c2": _trial_for(Classification.PASS),
        "c3": _trial_for(Classification.FAIL),
        "c4": _trial_for(Classification.FAIL),
    }
    result = ScriptedEngine(commits, trials).search("good", "bad")
    assert result.culprit == "c3"
    flaky_step = next(step for step in result.trace if step.commit == "c1")
    assert flaky_step.classification == Classification.FLAKY
    assert flaky_step.decision == "untrusted_flaky"
    sub_step = next(step for step in result.trace if step.substitute_for == "c1")
    assert sub_step.commit == "c2"
    assert sub_step.decision == "substituted_pass"


def test_fully_flaky_range_falls_back_to_human_guidance() -> None:
    commits = ["c0", "c1", "c2"]
    flaky = _trial_for(Classification.FLAKY, escalation=[Classification.FLAKY, Classification.FLAKY])
    trials = {"c0": flaky, "c1": flaky, "c2": flaky}
    with pytest.raises(UnresolvedFlakyCommit, match="human guidance"):
        ScriptedEngine(commits, trials).search("good", "bad")


def build_fixture() -> Path:
    fixture_script = Path(__file__).parents[1] / "fixtures" / "build_fixture.py"
    subprocess.run([sys.executable, str(fixture_script)], check=True)
    return fixture_script.parent / "flaky-regression-demo"


def test_engine_finds_real_regression_without_mutating_fixture() -> None:
    repo = build_fixture()
    original = git(repo, "rev-parse", "HEAD")
    root = git(repo, "rev-list", "--max-parents=0", "HEAD")
    trace = repo.parent / "test-trace.json"
    result = BisectEngine(repo, "pytest -q tests/test_calculator.py", runs=2).search(root, "HEAD", trace)
    assert git(repo, "show", "-s", "--format=%s", result.culprit) == "optimize parser result handling"
    flaky_steps = [step for step in result.trace if step.classification.value == "flaky"]
    assert flaky_steps
    assert flaky_steps[0].outcomes == ["fail", "pass"]
    assert flaky_steps[0].decision == "untrusted_flaky"
    assert git(repo, "rev-parse", "HEAD") == original
    assert trace.exists()
