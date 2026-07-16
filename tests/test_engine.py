from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sentinel_bisect.orchestrator.engine import BisectEngine
from sentinel_bisect.orchestrator.git import git


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
