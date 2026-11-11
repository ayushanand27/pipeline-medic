"""Prove a fix before proposing it.

The agent applies the fix to a separate copy of the failing commit, runs the project's
own check command there, and only opens a pull request if that command passes.

Safety: the command runs with a minimal environment. Tokens and API keys are not passed
to it, because it executes code from the branch being repaired.
"""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import Plan

_SAFE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")


@dataclass
class VerifyResult:
    passed: bool
    command: str
    output: str  # last part of the command output


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def verify_plan(
    plan: Plan,
    sha: str,
    command: str,
    repo_dir: str = ".",
    timeout: int = 600,
    use_venv: bool = True,
) -> VerifyResult:
    """Apply the plan on top of commit `sha` in a temporary worktree and run `command` there."""
    repo = Path(repo_dir).resolve()
    with tempfile.TemporaryDirectory(prefix="medic-verify-") as tmp:
        worktree = Path(tmp) / "src"
        _git(repo, "fetch", "--quiet", "origin", sha)  # make sure the commit is available
        added = _git(repo, "worktree", "add", "--detach", str(worktree), sha)
        if added.returncode != 0:
            return VerifyResult(False, command, f"could not check out {sha}: {added.stderr.strip()[-500:]}")
        try:
            for change in plan.changes:
                target = (worktree / change.path).resolve()
                if worktree.resolve() not in target.parents:
                    return VerifyResult(False, command, f"refusing to write outside the worktree: {change.path}")
                target.write_text(change.new, encoding="utf-8")

            env = {key: os.environ[key] for key in _SAFE_ENV if key in os.environ}
            if use_venv:
                # A fresh virtual environment, so "the package is missing" is really tested.
                venv = Path(tmp) / "venv"
                subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
                env["PATH"] = f"{venv / 'bin'}{os.pathsep}{env.get('PATH', '')}"
                env["VIRTUAL_ENV"] = str(venv)
            try:
                done = subprocess.run(
                    command, shell=True, cwd=worktree, env=env, capture_output=True, text=True, timeout=timeout
                )
                output = (done.stdout + done.stderr)[-2000:]
                return VerifyResult(done.returncode == 0, command, output)
            except subprocess.TimeoutExpired:
                return VerifyResult(False, command, f"timed out after {timeout} seconds")
        finally:
            _git(repo, "worktree", "remove", "--force", str(worktree))
