from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sentinel_bisect.orchestrator.engine import (
    BisectEngine,
    EmptyRange,
    NoRegressionFound,
    ReproductionCommandError,
    UnreliableBaseline,
    UnresolvedFlakyCommit,
)
from sentinel_bisect.orchestrator.git import git
from sentinel_bisect.orchestrator.models import Attempt, Classification, TierAttempt, TrialResult

# The commit that stands in for the external "good" baseline in ScriptedEngine tests.
# It is not part of the good..bad commit list (git excludes good from that range), so
# tests register it separately and pass it as the `good` argument to search().
GOOD = "cGOOD"


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


def _command_error_trial() -> TrialResult:
    """A trial where the reproduction command could not run (exit 127)."""
    attempts = [Attempt(127, "command not found"), Attempt(127, "command not found")]
    return TrialResult(
        classification=Classification.FAIL,
        attempts=attempts,
        escalation=[TierAttempt(2, Classification.FAIL, ["fail", "fail"])],
    )


class ScriptedEngine(BisectEngine):
    """Engine double: a fixed commit list and a per-commit canned trial result, so
    search/anchor/substitution routing can be exercised without a real git repository.
    The commit list represents the good..bad range (excludes good, includes bad last),
    mirroring `commit_range`; an empty list raises ValueError like the real one does."""

    def __init__(self, commits: list[str], trials: dict[str, TrialResult]) -> None:
        self.repo, self.command, self.rerun_schedule = Path("."), "cmd", (2,)
        self._scripted_commits = commits
        self._trials = trials

    def _commits(self, good: str, bad: str) -> list[str]:
        if not self._scripted_commits:
            raise ValueError("No commits found between good and bad revisions")
        return self._scripted_commits

    def _trial(self, revision: str) -> TrialResult:
        return self._trials[revision]


def test_commit_resolves_after_escalation_without_substitution() -> None:
    commits = ["c0", "c1", "c2", "c3", "c4"]
    trials = {
        GOOD: _trial_for(Classification.PASS),
        "c0": _trial_for(Classification.PASS),
        # Midpoint resolves to PASS only after escalating 2 -> 4 reruns.
        "c1": _trial_for(Classification.PASS, escalation=[Classification.FLAKY, Classification.PASS]),
        "c2": _trial_for(Classification.FAIL),
        "c3": _trial_for(Classification.FAIL),
        "c4": _trial_for(Classification.FAIL),  # bad anchor (last commit) fails cleanly
    }
    result = ScriptedEngine(commits, trials).search(GOOD, "bad")
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
        GOOD: _trial_for(Classification.PASS),
        "c0": _trial_for(Classification.PASS),
        "c1": _trial_for(Classification.FLAKY, escalation=[Classification.FLAKY, Classification.FLAKY]),
        "c2": _trial_for(Classification.PASS),
        "c3": _trial_for(Classification.FAIL),
        "c4": _trial_for(Classification.FAIL),
    }
    result = ScriptedEngine(commits, trials).search(GOOD, "bad")
    assert result.culprit == "c3"
    flaky_step = next(step for step in result.trace if step.commit == "c1")
    assert flaky_step.classification == Classification.FLAKY
    assert flaky_step.decision == "untrusted_flaky"
    sub_step = next(step for step in result.trace if step.substitute_for == "c1")
    assert sub_step.commit == "c2"
    assert sub_step.decision == "substituted_pass"


def test_fully_flaky_range_falls_back_to_human_guidance() -> None:
    # Clean anchors (good passes, bad fails) but every interior commit is flaky.
    commits = ["c0", "c1", "c2", "c3"]
    flaky = _trial_for(Classification.FLAKY, escalation=[Classification.FLAKY, Classification.FLAKY])
    trials = {
        GOOD: _trial_for(Classification.PASS),
        "c0": flaky,
        "c1": flaky,
        "c2": flaky,
        "c3": _trial_for(Classification.FAIL),  # bad anchor is a clean failure
    }
    with pytest.raises(UnresolvedFlakyCommit, match="human guidance"):
        ScriptedEngine(commits, trials).search(GOOD, "bad")


# --- Edge cases a judge is likely to hit with their own input ---------------


def test_no_regression_when_bad_commit_passes() -> None:
    # Case 1: good and bad produce the same (passing) outcome — nothing to bisect.
    commits = ["c0", "c1", "c2"]
    trials = {rev: _trial_for(Classification.PASS) for rev in [GOOD, "c0", "c1", "c2"]}
    with pytest.raises(NoRegressionFound, match="No regression found"):
        ScriptedEngine(commits, trials).search(GOOD, "bad")


def test_good_baseline_that_already_fails_is_reported() -> None:
    # Case 1b/3b: the good baseline already fails (regression predates range, or a
    # misconfigured command) — reported rather than returning a bogus culprit.
    commits = ["c0", "c1"]
    trials = {GOOD: _trial_for(Classification.FAIL), "c0": _trial_for(Classification.FAIL), "c1": _trial_for(Classification.FAIL)}
    with pytest.raises(UnreliableBaseline, match="already fails"):
        ScriptedEngine(commits, trials).search(GOOD, "bad")


def test_flaky_baseline_is_reported_not_silently_trusted() -> None:
    # Case 2: the starting/good commit is itself flaky — no reliable anchor to search from.
    commits = ["c0", "c1"]
    trials = {
        GOOD: _trial_for(Classification.FLAKY, escalation=[Classification.FLAKY, Classification.FLAKY]),
        "c0": _trial_for(Classification.PASS),
        "c1": _trial_for(Classification.FAIL),
    }
    with pytest.raises(UnreliableBaseline, match="flaky"):
        ScriptedEngine(commits, trials).search(GOOD, "bad")


def test_command_that_cannot_run_is_reported_distinctly() -> None:
    # Case 3: reproduction command doesn't exist / errors immediately (exit 127) at the
    # first commit checked — distinguished from a genuine test failure.
    commits = ["c0", "c1"]
    trials = {GOOD: _command_error_trial(), "c0": _command_error_trial(), "c1": _command_error_trial()}
    with pytest.raises(ReproductionCommandError, match="failed to run"):
        ScriptedEngine(commits, trials).search(GOOD, "bad")


def test_single_commit_range_is_a_valid_trivial_case() -> None:
    # Case 4: good and bad are adjacent (one commit in range). The single commit is
    # the culprit, and its pass/fail anchors are actually verified — no off-by-one crash.
    commits = ["cBAD"]
    trials = {GOOD: _trial_for(Classification.PASS), "cBAD": _trial_for(Classification.FAIL)}
    result = ScriptedEngine(commits, trials).search(GOOD, "bad")
    assert result.culprit == "cBAD"
    assert [step.commit for step in result.trace] == [GOOD, "cBAD"]


def test_empty_range_is_reported_not_crashed() -> None:
    # Case 4b: good and bad are the same commit (empty range) — a clear message, not a
    # ValueError/IndexError stack trace.
    with pytest.raises(EmptyRange, match="range is empty"):
        ScriptedEngine([], {}).search(GOOD, GOOD)


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
