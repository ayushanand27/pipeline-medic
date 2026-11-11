"""End-to-end tests of the agent loop against a fake GitHub (no network)."""

import json
from pathlib import Path

from medic import agent, diagnose as diagnose_module
from medic.agent import handle_run
from medic.config import Config
from medic.github_client import PullRequestsNotAllowed

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


class FakeGitHub:
    def __init__(self, log_name: str, files: dict[str, str], branch: str = "feature", conclusion: str = "failure"):
        self.repo = "owner/name"
        self.allow_pull_requests = True
        self.log = (FIXTURES / log_name).read_text(encoding="utf-8")
        self.files = files
        self.run = {
            "conclusion": conclusion,
            "head_branch": branch,
            "head_sha": "abc123",
            "name": "demo-ci",
            "run_number": 7,
            "html_url": "https://github.test/run/7",
        }
        self.branches: dict[str, str] = {}
        self.written: dict[str, str] = {}
        self.pull_requests: list[dict] = []
        self.issues: list[dict] = []

    def get_run(self, run_id):
        return self.run

    def failed_jobs(self, run_id):
        return [{"id": 1}]

    def job_log(self, job_id):
        return self.log

    def get_file(self, path, ref):
        return self.files.get(path)

    def branch_exists(self, branch):
        return branch in self.branches

    def create_branch(self, branch, from_sha):
        self.branches[branch] = from_sha

    def update_file(self, path, text, branch, message):
        self.written[path] = text

    def open_pull_request(self, title, body, head, base):
        if not self.allow_pull_requests:
            raise PullRequestsNotAllowed()
        self.pull_requests.append({"title": title, "body": body, "head": head, "base": base})
        return "https://github.test/pull/1"

    def open_issue(self, title, body):
        self.issues.append({"title": title, "body": body})
        return "https://github.test/issues/1"

    def issue_exists(self, title):
        return any(issue["title"] == title for issue in self.issues)


def repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_missing_dependency_gets_a_pull_request():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\nhttpx\npytest\n"})
    outcome = handle_run(gh, 42, Config())
    assert outcome.action == "pull_request"
    assert gh.written["demo-app/requirements.txt"].endswith("fastapi\n")
    pr = gh.pull_requests[0]
    assert pr["head"] == "medic/fix-run-42" and pr["base"] == "feature"
    assert gh.branches["medic/fix-run-42"] == "abc123"
    assert "Root cause" in pr["body"] and "+fastapi" in pr["body"]


def test_bad_pin_gets_a_pull_request():
    gh = FakeGitHub("bad_pin.log", {"demo-app/requirements.txt": "fastapi==99.0.0\nuvicorn\n"})
    assert handle_run(gh, 43, Config()).action == "pull_request"
    assert gh.written["demo-app/requirements.txt"] == "fastapi\nuvicorn\n"


def test_test_failure_without_llm_opens_an_issue_and_changes_nothing():
    gh = FakeGitHub("test_failure.log", {})
    outcome = handle_run(gh, 44, Config())
    assert outcome.action == "issue"
    assert not gh.written and not gh.pull_requests and not gh.branches
    assert "AssertionError" in gh.issues[0]["body"]


def test_test_failure_with_llm_gets_a_pull_request(monkeypatch):
    buggy = repo_file("demo-app/app/pricing.py").replace("0 if discounted >=", "0 if amount >=")
    files = {
        "demo-app/tests/test_pricing.py": repo_file("demo-app/tests/test_pricing.py"),
        "demo-app/app/pricing.py": buggy,
    }
    seen = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            answer = {
                "root_cause": "Free delivery is checked on the price before the coupon.",
                "edits": [{"path": "demo-app/app/pricing.py", "search": "0 if amount >=", "replace": "0 if discounted >="}],
            }
            return {"choices": [{"message": {"content": json.dumps(answer)}}]}

    def fake_post(url, **kwargs):
        seen["prompt"] = kwargs["json"]["messages"][1]["content"]
        return Response()

    monkeypatch.setattr(diagnose_module.requests, "post", fake_post)
    cfg = Config(llm_base_url="http://llm.test/v1", llm_api_key="k", llm_model="m")
    gh = FakeGitHub("test_failure.log", files)

    outcome = handle_run(gh, 45, cfg)
    assert outcome.action == "pull_request"
    # The log names only the test file. The agent must find pricing.py through the test's imports.
    assert "--- demo-app/app/pricing.py ---" in seen["prompt"]
    assert gh.written["demo-app/app/pricing.py"] == repo_file("demo-app/app/pricing.py")
    assert "LLM" in gh.pull_requests[0]["body"]


def test_medic_never_fixes_its_own_branch():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"}, branch="medic/fix-run-1")
    assert handle_run(gh, 46, Config()).action == "skipped"
    assert not gh.pull_requests and not gh.issues


def test_passing_run_is_skipped():
    gh = FakeGitHub("missing_module.log", {}, conclusion="success")
    assert handle_run(gh, 47, Config()).action == "skipped"


def test_same_run_is_not_handled_twice():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    handle_run(gh, 48, Config())
    assert handle_run(gh, 48, Config()).action == "skipped"
    assert len(gh.pull_requests) == 1


def test_dry_run_diagnose_reads_local_files():
    result = agent.diagnose(
        (FIXTURES / "bad_pin.log").read_text(encoding="utf-8"),
        lambda path: "fastapi==99.0.0\n" if path == "demo-app/requirements.txt" else None,
        Config(),
    )
    assert result.plan is not None and result.plan.changes[0].new == "fastapi\n"


def test_fix_is_not_lost_when_the_repo_blocks_pull_requests():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    gh.allow_pull_requests = False
    outcome = handle_run(gh, 49, Config())
    assert outcome.action == "issue"
    assert gh.written["demo-app/requirements.txt"] == "uvicorn\nfastapi\n"
    assert "compare/feature...medic/fix-run-49" in gh.issues[0]["body"]
