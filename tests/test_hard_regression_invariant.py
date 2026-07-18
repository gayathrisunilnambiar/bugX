from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sentinel_bisect.verify.service import verify_patch


FIXTURE = Path(__file__).parents[1] / "fixtures" / "hard-regression-demo"
TARGET = "pytest -q tests/test_calculator.py::test_parse_total"
SMOKE = "pytest -q tests/test_calculator.py::test_parse_average"
INVARIANT = "pytest -q tests/test_invariants.py"

SHALLOW_REPLACEMENT = """def parse_total(text: str) -> int:
    if text == '1, 2, 3':
        return 6
    return sum(_parse_values(text))


def parse_average(text: str) -> float:
    if text == '2, 4, 6':
        return 4
    values = _parse_values(text)
    return sum(values) / len(values)
"""


def _fixture_copy(tmp_path: Path) -> Path:
    destination = tmp_path / "hard-regression-demo"
    shutil.copytree(FIXTURE, destination, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    for args in (("init",), ("config", "user.email", "test@example.test"), ("config", "user.name", "Test"), ("add", "."), ("commit", "-m", "fixture")):
        subprocess.run(("git", *args), cwd=destination, check=True, capture_output=True, text=True)
    return destination


def _hand_constructed_patch(worktree: Path, old: str, new: str) -> str:
    calculator = worktree / "calculator.py"
    original_bytes = calculator.read_bytes()
    old_bytes = old.replace("\n", "\r\n").encode("utf-8")
    new_bytes = new.replace("\n", "\r\n").encode("utf-8")
    assert old_bytes in original_bytes
    calculator.write_bytes(original_bytes.replace(old_bytes, new_bytes))
    patch = subprocess.run(("git", "diff", "--", "calculator.py"), cwd=worktree, check=True, capture_output=True, text=True).stdout
    calculator.write_bytes(original_bytes)
    return patch


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("def parse_total(text: str) -> int:\n    return sum(_parse_values(text))\n\n\ndef parse_average(text: str) -> float:\n    values = _parse_values(text)\n    return sum(values) / len(values)\n", SHALLOW_REPLACEMENT),
        ("return [int(part) for part in parts[:-1]]", "return [int(part) for part in parts[:3]]"),
    ],
    ids=["hardcoded-wrappers", "first-three-only"],
)
def test_invariant_catches_flawed_patches_that_target_and_smoke_accept(tmp_path: Path, old: str, new: str) -> None:
    worktree = _fixture_copy(tmp_path)
    result = verify_patch(worktree, _hand_constructed_patch(worktree, old, new), TARGET, runs=1, smoke_command=SMOKE, invariant_command=INVARIANT)

    assert result.applied, result.message
    assert result.failed_gates == ("invariant",)
    assert [gate.passed for gate in result.gates] == [True, True, False]


def test_general_shared_helper_fix_passes_all_three_gates(tmp_path: Path) -> None:
    worktree = _fixture_copy(tmp_path)
    patch = _hand_constructed_patch(worktree, "return [int(part) for part in parts[:-1]]", "return [int(part) for part in parts]")
    result = verify_patch(worktree, patch, TARGET, runs=1, smoke_command=SMOKE, invariant_command=INVARIANT)

    assert result.applied, result.message
    assert result.verified
    assert [gate.passed for gate in result.gates] == [True, True, True]
