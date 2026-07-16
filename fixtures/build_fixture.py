"""Regenerate the self-contained regression history used by tests and demos."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent / "flaky-regression-demo"
COMMIT_INDEX = 0


def _remove_tree(target: Path, attempts: int = 6) -> None:
    """Delete a git worktree tree robustly. Git marks packed/object files read-only,
    and on Windows/WSL a just-finished process (a disposable worktree, pytest, the
    flaky marker) can briefly hold a handle so removal fails with PermissionError.
    Clear the read-only bit on each failure and retry the whole removal a few times
    with a short backoff, so regenerating the fixture in quick succession is reliable.
    """
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
    timestamp = f"2024-01-01T00:00:{COMMIT_INDEX:02d}+0000"
    environment["GIT_AUTHOR_DATE"] = timestamp
    environment["GIT_COMMITTER_DATE"] = timestamp
    subprocess.run(("git", "commit", "-m", message), cwd=ROOT, check=True, capture_output=True, env=environment)
    COMMIT_INDEX += 1


def main() -> None:
    global COMMIT_INDEX
    COMMIT_INDEX = 0
    if ROOT.exists():
        _remove_tree(ROOT)
    ROOT.mkdir(parents=True)
    run("git", "init")
    run("git", "config", "user.email", "demo@example.test")
    run("git", "config", "user.name", "Sentinel Demo")
    write("calculator.py", "def parse_total(text: str) -> int:\n    return sum(int(part.strip()) for part in text.split(','))\n")
    write("pyproject.toml", "[tool.pytest.ini_options]\npythonpath = ['.']\n")
    write("tests/test_calculator.py", "from calculator import parse_total\n\ndef test_parse_total():\n    assert parse_total('1, 2, 3') == 6\n")
    write("README.md", "# Flaky regression fixture\n")
    commit("initial calculator and regression test")
    write("calculator.py", "\"\"\"Tiny calculator fixture.\"\"\"\n\ndef parse_total(text: str) -> int:\n    return sum(int(part.strip()) for part in text.split(','))\n")
    commit("document parser")
    write("tests/test_calculator.py", "from calculator import parse_total\n\ndef test_parse_total():\n    assert parse_total('1, 2, 3') == 6\n\ndef test_single_value():\n    assert parse_total('9') == 9\n")
    commit("add single value coverage")
    write("README.md", "# Flaky regression fixture\n\nThe standard demo command exercises the calculator test target.\n")
    commit("clarify fixture usage")
    write("tests/test_calculator.py", "from pathlib import Path\n\nfrom calculator import parse_total\n\ndef test_parse_total():\n    assert parse_total('1, 2, 3') == 6\n\ndef test_single_value():\n    assert parse_total('9') == 9\n\ndef test_unrelated_intermittent_probe():\n    # A state-leak test: consecutive process runs alternate fail/pass. It is\n    # unrelated to parse_total and deliberately guarantees a mixed demo trace.\n    marker = Path('.sentinel-flaky-marker')\n    if marker.exists():\n        marker.unlink()\n    else:\n        marker.write_text('state leaked', encoding='utf-8')\n        raise AssertionError('unrelated intermittent probe')\n")
    commit("add known intermittent monitoring probe")
    write("calculator.py", "\"\"\"Tiny calculator fixture.\"\"\"\n\ndef parse_total(text: str) -> int:\n    parts = [int(part.strip()) for part in text.split(',')]\n    return sum(parts)\n")
    write("tests/test_calculator.py", "from calculator import parse_total\n\ndef test_parse_total():\n    assert parse_total('1, 2, 3') == 6\n\ndef test_single_value():\n    assert parse_total('9') == 9\n\ndef test_whitespace():\n    assert parse_total('4, 5') == 9\n")
    commit("refactor parser and isolate intermittent probe")
    write("README.md", "# Flaky regression fixture\n\nThe parser reproduction target is stable after the monitoring probe is isolated.\n")
    commit("record stable parser investigation")
    write("calculator.py", "\"\"\"Tiny calculator fixture.\"\"\"\n\ndef parse_total(text: str) -> int:\n    parts = [int(part.strip()) for part in text.split(',')]\n    # Regression: only the first value is retained after the optimization.\n    return parts[0]\n")
    commit("optimize parser result handling")
    write("README.md", "# Flaky regression fixture\n\nThe parser investigation should run `pytest -q tests/test_calculator.py`.\n")
    commit("document focused reproduction")
    write("tests/test_calculator.py", "from calculator import parse_total\n\ndef test_parse_total():\n    assert parse_total('1, 2, 3') == 6\n\ndef test_single_value():\n    assert parse_total('9') == 9\n\ndef test_whitespace():\n    assert parse_total('4, 5') == 9\n\ndef test_zero_value():\n    assert parse_total('0') == 0\n")
    commit("add whitespace regression coverage")
    print(f"Fixture created at {ROOT}")


if __name__ == "__main__":
    main()
