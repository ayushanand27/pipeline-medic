"""verify_plan is tested against a real temporary git repository."""

import subprocess

import pytest

from medic.models import FileChange, Plan
from medic.verify import verify_plan

CHECK = "python -c \"import sys; sys.exit(0 if open('state.txt').read().strip() == 'good' else 1)\""


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    (tmp_path / "state.txt").write_text("broken\n")
    git("add", ".")
    git("commit", "-q", "-m", "broken commit")
    sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return tmp_path, sha


def plan(new_text: str, path: str = "state.txt") -> Plan:
    return Plan("cause", [FileChange(path, "broken\n", new_text)], "rule")


def test_good_fix_passes(repo):
    path, sha = repo
    result = verify_plan(plan("good\n"), sha, CHECK, repo_dir=str(path), use_venv=False)
    assert result.passed


def test_bad_fix_fails(repo):
    path, sha = repo
    result = verify_plan(plan("still broken\n"), sha, CHECK, repo_dir=str(path), use_venv=False)
    assert not result.passed


def test_the_real_checkout_is_never_touched(repo):
    path, sha = repo
    verify_plan(plan("good\n"), sha, CHECK, repo_dir=str(path), use_venv=False)
    assert (path / "state.txt").read_text() == "broken\n"
    worktrees = subprocess.run(
        ["git", "-C", str(path), "worktree", "list"], capture_output=True, text=True
    ).stdout.strip().splitlines()
    assert len(worktrees) == 1  # the temporary one was removed


def test_secrets_are_not_passed_to_the_check(repo, monkeypatch):
    path, sha = repo
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    leak_check = "python -c \"import os, sys; sys.exit(1 if 'GITHUB_TOKEN' in os.environ else 0)\""
    assert verify_plan(plan("good\n"), sha, leak_check, repo_dir=str(path), use_venv=False).passed


def test_slow_check_times_out(repo):
    path, sha = repo
    result = verify_plan(plan("good\n"), sha, "sleep 5", repo_dir=str(path), timeout=1, use_venv=False)
    assert not result.passed and "timed out" in result.output


def test_write_outside_the_worktree_is_refused(repo):
    path, sha = repo
    result = verify_plan(plan("x", path="../escape.txt"), sha, CHECK, repo_dir=str(path), use_venv=False)
    assert not result.passed and "outside" in result.output


def test_unknown_commit_fails_cleanly(repo):
    path, _ = repo
    result = verify_plan(plan("good\n"), "0" * 40, CHECK, repo_dir=str(path), use_venv=False)
    assert not result.passed and "could not check out" in result.output
