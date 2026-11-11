from pathlib import Path

import pytest

from medic import __main__ as cli
from medic.agent import Outcome

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def test_dry_run_prints_the_diagnosis_and_diff(tmp_path, capsys):
    (tmp_path / "demo-app").mkdir()
    (tmp_path / "demo-app" / "requirements.txt").write_text("fastapi==99.0.0\n")
    code = cli.main(["--log-file", str(FIXTURES / "bad_pin.log"), "--workdir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "failure: bad_pin fastapi==99.0.0" in out
    assert "-fastapi==99.0.0" in out and "+fastapi" in out


def test_dry_run_without_a_fix_says_why(tmp_path, capsys):
    cli.main(["--log-file", str(FIXTURES / "test_failure.log"), "--workdir", str(tmp_path)])
    assert "no fix:" in capsys.readouterr().out


def test_real_run_needs_repo_run_id_and_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["--repo", "owner/name"])


def test_real_run_calls_the_agent_and_writes_the_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    seen = {}

    def fake_handle_run(gh, run_id, cfg):
        seen["repo"], seen["run_id"] = gh.repo, run_id
        return Outcome("pull_request", "missing package", "https://github.test/pull/1", "missing_module", "passed")

    monkeypatch.setattr(cli, "handle_run", fake_handle_run)
    assert cli.main(["--repo", "owner/name", "--run-id", "7"]) == 0
    assert seen == {"repo": "owner/name", "run_id": 7}
    assert "medic: pull_request" in capsys.readouterr().out
    text = summary.read_text()
    assert "| 7 | missing_module | pull_request | passed | https://github.test/pull/1 |" in text
