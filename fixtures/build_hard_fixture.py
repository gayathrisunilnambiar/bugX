"""Regenerate a second, harder regression history for demonstrating the
--analyze/--verify reasoning-effort escalation ladder (see analysis/escalation.py).

Unlike fixtures/build_fixture.py (which demonstrates flaky-commit routing), this
fixture has no flaky test — its introducing commit breaks a *shared* parsing helper
used by two functions. The declared reproduction command only exercises one of them
(`parse_total`); the other (`parse_average`) is only checked by --smoke-command. A
patch that special-cases the symptom visible in the failing output — rather than
fixing the shared `_parse_values` helper the diff actually shows is broken — will
still fail the smoke command, which is what should trigger escalation to the next
reasoning-effort tier. Whether a low-effort tier actually takes that shortcut is a
real model behavior this repo cannot confirm without a live OPENAI_API_KEY; see
DECISIONS.md.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent / "hard-regression-demo"
COMMIT_INDEX = 0


def _remove_tree(target: Path, attempts: int = 6) -> None:
    """See fixtures/build_fixture.py — same Windows-safe retry/readonly handling,
    duplicated rather than shared so the two fixture generators stay independent."""
    def clear_readonly(action: object, path: str, _exc: object) -> None:
        Path(path).chmod(stat.S_IWRITE)
        action(path)  # type: ignore[operator]

    for attempt in range(attempts):
        try:
            shutil.rmtree(target, onerror=clear_readonly)
            return
        except OSError:
            if attempt == attempts - 1 or not target.exists():
                if not target.exists():
                    return
                raise
            time.sleep(0.3)


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True)


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(message: str) -> None:
    global COMMIT_INDEX
    run("git", "add", ".")
    environment = os.environ.copy()
    timestamp = f"2024-02-01T00:00:{COMMIT_INDEX:02d}+0000"
    environment["GIT_AUTHOR_DATE"] = timestamp
    environment["GIT_COMMITTER_DATE"] = timestamp
    subprocess.run(("git", "commit", "-m", message), cwd=ROOT, check=True, capture_output=True, env=environment)
    COMMIT_INDEX += 1


_INITIAL_CALCULATOR = (
    '"""Tiny calculator fixture with a shared parsing helper."""\n\n'
    "def _parse_values(text: str) -> list[int]:\n"
    "    return [int(part.strip()) for part in text.split(',') if part.strip()]\n\n\n"
    "def parse_total(text: str) -> int:\n"
    "    return sum(_parse_values(text))\n\n\n"
    "def parse_average(text: str) -> float:\n"
    "    values = _parse_values(text)\n"
    "    return sum(values) / len(values)\n"
)

_INITIAL_TEST = (
    "from calculator import parse_average, parse_total\n\n"
    "def test_parse_total():\n"
    "    assert parse_total('1, 2, 3') == 6\n\n"
    "def test_parse_average():\n"
    "    assert parse_average('2, 4, 6') == 4\n"
)

# This is deliberately a domain-derived invariant rather than a list of previous
# failures.  For every canonical comma-separated sequence in a small valid domain,
# the shared parser must preserve every integer segment in order.  It therefore
# catches wrapper-level special cases and helper fixes that only retain the first
# few values, while the root-cause fix (iterate over all parts) satisfies it.
_INVARIANT_TEST = (
    "from itertools import product\n\n"
    "import pytest\n\n"
    "from calculator import _parse_values\n\n"
    "@pytest.mark.parametrize(\n"
    "    'values',\n"
    "    [list(values) for size in range(1, 5) for values in product(range(-2, 3), repeat=size)],\n"
    ")\n"
    "def test_parse_values_preserves_every_valid_segment(values):\n"
    "    text = ', '.join(f' {value} ' for value in values)\n"
    "    assert _parse_values(text) == values\n"
)

# The bug: "optimize" _parse_values by dropping the last segment, assuming callers
# already validated trailing input. This breaks parse_total's target test directly
# (visible in the failing output) and parse_average's smoke test via the same shared
# helper (not visible unless the diff's change to _parse_values is read carefully).
_REGRESSED_CALCULATOR = (
    '"""Tiny calculator fixture with a shared parsing helper."""\n\n'
    "def _parse_values(text: str) -> list[int]:\n"
    "    # Optimization: assume the last segment was already validated upstream and\n"
    "    # skip re-parsing it.\n"
    "    parts = [part.strip() for part in text.split(',') if part.strip()]\n"
    "    return [int(part) for part in parts[:-1]]\n\n\n"
    "def parse_total(text: str) -> int:\n"
    "    return sum(_parse_values(text))\n\n\n"
    "def parse_average(text: str) -> float:\n"
    "    values = _parse_values(text)\n"
    "    return sum(values) / len(values)\n"
)


def main() -> None:
    global COMMIT_INDEX
    COMMIT_INDEX = 0
    if ROOT.exists():
        _remove_tree(ROOT)
    ROOT.mkdir(parents=True)
    run("git", "init")
    run("git", "config", "user.email", "demo@example.test")
    run("git", "config", "user.name", "Sentinel Demo")

    write("calculator.py", _INITIAL_CALCULATOR)
    write("pyproject.toml", "[tool.pytest.ini_options]\npythonpath = ['.']\n")
    write("tests/test_calculator.py", _INITIAL_TEST)
    write("README.md", "# Hard regression fixture\n")
    commit("initial calculator with shared parsing helper")

    write("README.md", "# Hard regression fixture\n\nDemonstrates the analysis escalation ladder.\n")
    commit("document fixture purpose")

    write("tests/test_invariants.py", _INVARIANT_TEST)
    commit("add shared parser invariant coverage")

    write(
        "tests/test_calculator.py",
        _INITIAL_TEST + "\ndef test_parse_total_single_value():\n    assert parse_total('9') == 9\n",
    )
    commit("add single-value coverage")

    write("calculator.py", _INITIAL_CALCULATOR.replace("Tiny calculator fixture", "Tiny calculator fixture (documented)"))
    commit("add module docstring detail")

    write("calculator.py", _REGRESSED_CALCULATOR)
    commit("optimize shared value parsing")

    write("README.md", "# Hard regression fixture\n\nReproduction target: pytest -q tests/test_calculator.py::test_parse_total\n")
    commit("document focused reproduction target")

    write(
        "tests/test_calculator.py",
        _INITIAL_TEST
        + "\ndef test_parse_total_single_value():\n    assert parse_total('9') == 9\n\n"
        "def test_parse_average_pair():\n    assert parse_average('10, 20') == 15\n",
    )
    commit("add paired-average coverage")

    print(f"Fixture created at {ROOT}")


if __name__ == "__main__":
    main()
