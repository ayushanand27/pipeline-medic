"""End-to-end tests of the agent loop against a fake GitHub (no network)."""

from pathlib import Path

from medic import agent
from medic.agent import handle_run
from medic.config import Config
from medic.github_client import PullRequestsNotAllowed
from medic.verify import VerifyResult

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
        self.changed_files = ["demo-app/requirements.txt"]
        self.labels: list[tuple[str, str]] = []
        self.reruns: list[int] = []
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

    def commit_files(self, sha):
        return self.changed_files

    def rerun_failed_jobs(self, run_id):
        self.reruns.append(run_id)

    def add_label(self, url, label):
        self.labels.append((url, label))

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

    def fake_ask(system, user, cfg):
        seen["prompt"] = user
        return {
            "root_cause": "Free delivery is checked on the price before the coupon.",
            "edits": [{"path": "demo-app/app/pricing.py", "search": "0 if amount >=", "replace": "0 if discounted >="}],
        }

    monkeypatch.setattr("medic.llm_chain.ask", fake_ask)
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


# ---- verification before the pull request ---------------------------------------

def verifier_that(passes: bool):
    calls = []

    def verifier(plan, sha, command, timeout=600):
        calls.append((sha, command))
        return VerifyResult(passes, command, "9 passed" if passes else "1 failed")

    verifier.calls = calls
    return verifier


def test_verified_fix_gets_a_pull_request_that_says_so():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    verifier = verifier_that(True)
    outcome = handle_run(gh, 50, Config(verify_command="pytest"), verifier=verifier)
    assert outcome.action == "pull_request" and outcome.verified == "passed"
    assert verifier.calls == [("abc123", "pytest")]
    body = gh.pull_requests[0]["body"]
    assert "`pytest` passed" in body and "9 passed" in body
    assert gh.labels == [("https://github.test/pull/1", "pipeline-medic")]


def test_fix_that_fails_verification_never_becomes_a_pull_request():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    outcome = handle_run(gh, 51, Config(verify_command="pytest"), verifier=verifier_that(False))
    assert outcome.action == "issue" and outcome.verified == "failed"
    assert not gh.branches and not gh.written and not gh.pull_requests
    assert "Proposed fix (rejected)" in gh.issues[0]["body"] and "FAILED" in gh.issues[0]["body"]


def test_without_a_verify_command_the_pull_request_says_not_verified():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    outcome = handle_run(gh, 52, Config())
    assert outcome.verified == "not run"
    assert "Not run" in gh.pull_requests[0]["body"]


def test_pull_request_lists_the_files_changed_in_the_failing_commit():
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    handle_run(gh, 53, Config())
    assert "Files changed in the failing commit" in gh.pull_requests[0]["body"]


# ---- network problems are retried, not "fixed" ------------------------------------

def transient_github(tmp_path, attempt: int) -> FakeGitHub:
    gh = FakeGitHub("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    gh.log = "Collecting fastapi\nERROR: HTTPSConnectionPool(host='pypi.org'): Read timed out.\n##[error]exit code 1\n"
    gh.run["run_attempt"] = attempt
    return gh


def test_network_failure_is_retried_once(tmp_path):
    gh = transient_github(tmp_path, attempt=1)
    outcome = handle_run(gh, 54, Config())
    assert outcome.action == "rerun" and gh.reruns == [54]
    assert not gh.pull_requests and not gh.issues and not gh.written


def test_network_failure_after_a_retry_goes_to_a_person(tmp_path):
    gh = transient_github(tmp_path, attempt=2)
    outcome = handle_run(gh, 55, Config())
    assert outcome.action == "issue" and gh.reruns == []
    assert "already failed again" in gh.issues[0]["body"]
