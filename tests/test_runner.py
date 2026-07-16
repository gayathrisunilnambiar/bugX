from __future__ import annotations

import sys
from pathlib import Path

from sentinel_bisect.orchestrator.models import Attempt, Classification
from sentinel_bisect.orchestrator.runner import classify_attempts, run_command_with_schedule


def test_all_successes_are_pass() -> None:
    assert classify_attempts([Attempt(0, ""), Attempt(0, "")]) == Classification.PASS


def test_all_failures_are_fail() -> None:
    assert classify_attempts([Attempt(1, ""), Attempt(2, "")]) == Classification.FAIL


def test_mixed_outcomes_are_flaky() -> None:
    assert classify_attempts([Attempt(0, ""), Attempt(1, ""), Attempt(0, "")]) == Classification.FLAKY


def _scripted_command(tmp_path: Path, exit_codes: list[int]) -> str:
    """Build a shell command whose exit code advances through `exit_codes` on each
    successive invocation (holding the last value once exhausted), backed by a
    counter file so the schedule's fresh batches can be scripted deterministically."""
    codes_file = tmp_path / "codes.txt"
    codes_file.write_text(",".join(str(c) for c in exit_codes))
    counter_file = tmp_path / "counter.txt"
    counter_file.write_text("0")
    script_file = tmp_path / "script.py"
    script_file.write_text(
        "import pathlib\n"
        f"codes = pathlib.Path(r'{codes_file}').read_text().split(',')\n"
        f"counter_path = pathlib.Path(r'{counter_file}')\n"
        "i = int(counter_path.read_text())\n"
        "counter_path.write_text(str(i + 1))\n"
        "raise SystemExit(int(codes[min(i, len(codes) - 1)]))\n"
    )
    return f"{sys.executable} {script_file}"


def test_immediate_resolution_at_lowest_tier_does_not_escalate(tmp_path: Path) -> None:
    command = _scripted_command(tmp_path, [0] * 20)
    result = run_command_with_schedule(command, tmp_path, (3, 7, 15))
    assert result.classification == Classification.PASS
    assert len(result.attempts) == 3


def test_escalates_to_second_tier_when_first_tier_is_mixed(tmp_path: Path) -> None:
    # First 3 calls (tier 1) are mixed; the next fresh batch of 7 (tier 2) is unanimous.
    exit_codes = [0, 1, 0] + [0] * 7
    command = _scripted_command(tmp_path, exit_codes)
    result = run_command_with_schedule(command, tmp_path, (3, 7, 15))
    assert result.classification == Classification.PASS
    assert len(result.attempts) == 7


def test_escalates_to_third_tier_when_first_two_tiers_are_mixed(tmp_path: Path) -> None:
    # Tier 1 (3 calls) mixed, tier 2 (7 calls) mixed, tier 3 (15 calls) unanimous.
    exit_codes = [0, 1, 0] + [0, 1, 0, 0, 0, 0, 0] + [1] * 15
    command = _scripted_command(tmp_path, exit_codes)
    result = run_command_with_schedule(command, tmp_path, (3, 7, 15))
    assert result.classification == Classification.FAIL
    assert len(result.attempts) == 15


def test_stays_flaky_after_exhausting_every_tier(tmp_path: Path) -> None:
    exit_codes = [0, 1, 0] + [0, 1, 0, 0, 0, 0, 0] + [0, 1] + [0] * 13
    command = _scripted_command(tmp_path, exit_codes)
    result = run_command_with_schedule(command, tmp_path, (3, 7, 15))
    assert result.classification == Classification.FLAKY
    assert len(result.attempts) == 15


def test_single_tier_schedule_matches_previous_fixed_n_behavior(tmp_path: Path) -> None:
    """A one-element schedule (the --runs shorthand) never escalates, matching the
    old fixed-rerun-count behavior: a mixed result at that count stays flaky."""
    command = _scripted_command(tmp_path, [0, 1])
    result = run_command_with_schedule(command, tmp_path, (2,))
    assert result.classification == Classification.FLAKY
    assert len(result.attempts) == 2
