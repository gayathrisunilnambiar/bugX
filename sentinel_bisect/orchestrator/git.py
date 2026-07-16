from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def commit_range(repo: Path, good: str, bad: str) -> list[str]:
    commits = git(repo, "rev-list", "--ancestry-path", "--reverse", f"{good}..{bad}").splitlines()
    if not commits:
        raise ValueError("No commits found between good and bad revisions")
    return commits


@contextmanager
def disposable_worktree(repo: Path, revision: str) -> Iterator[Path]:
    # Keep temporary worktrees adjacent to the inspected repository. This avoids
    # platform-specific temp-directory permissions and never touches its checkout.
    staging = repo.parent / ".sentinel-worktrees"
    staging.mkdir(exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="sentinel-bisect-", dir=staging))
    try:
        git(repo, "worktree", "add", "--detach", "--force", str(path), revision)
        yield path
    finally:
        try:
            git(repo, "worktree", "remove", "--force", str(path))
        finally:
            shutil.rmtree(path, ignore_errors=True)
