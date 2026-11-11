"""The GitHub client is tested against a fake HTTP session, so no network is used."""

import base64

import pytest
import requests

from medic.github_client import GitHub, PullRequestsNotAllowed


class Response:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class Session:
    """Answers from a table of (METHOD, path-ending) -> Response, and records every call."""

    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for (route_method, ending), response in self.routes.items():
            if method == route_method and url.endswith(ending):
                return response
        return Response(404)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def client(routes) -> GitHub:
    gh = GitHub("token", "owner/name")
    gh.session = Session(routes)
    return gh


def test_token_is_sent_as_a_bearer_header():
    assert GitHub("abc", "owner/name").session.headers["Authorization"] == "Bearer abc"


def test_failed_jobs_keeps_only_failures():
    jobs = {"jobs": [{"id": 1, "conclusion": "success"}, {"id": 2, "conclusion": "failure"}]}
    gh = client({("GET", "/actions/runs/9/jobs"): Response(payload=jobs)})
    assert [job["id"] for job in gh.failed_jobs(9)] == [2]


def test_job_log_and_run_are_read():
    gh = client(
        {
            ("GET", "/actions/jobs/2/logs"): Response(text="boom"),
            ("GET", "/actions/runs/9"): Response(payload={"conclusion": "failure"}),
            ("GET", "/actions/runs"): Response(payload={"workflow_runs": [{"id": 9}]}),
        }
    )
    assert gh.job_log(2) == "boom"
    assert gh.get_run(9)["conclusion"] == "failure"
    assert gh.list_failed_runs(3) == [{"id": 9}]


def test_get_file_decodes_content_and_handles_missing_files():
    content = base64.b64encode(b"fastapi\n").decode()
    gh = client({("GET", "/contents/req.txt"): Response(payload={"type": "file", "content": content})})
    assert gh.get_file("req.txt", "sha") == "fastapi\n"
    assert gh.get_file("nope.txt", "sha") is None


def test_get_file_on_a_folder_returns_none():
    gh = client({("GET", "/contents/demo-app"): Response(payload=[{"name": "a"}])})
    assert gh.get_file("demo-app", "sha") is None


def test_commit_files_lists_names():
    gh = client({("GET", "/commits/abc"): Response(payload={"files": [{"filename": "a.py"}, {"filename": "b.py"}]})})
    assert gh.commit_files("abc") == ["a.py", "b.py"]


def test_update_file_sends_the_current_sha_and_encoded_text():
    gh = client(
        {
            ("GET", "/contents/req.txt"): Response(payload={"sha": "old"}),
            ("PUT", "/contents/req.txt"): Response(payload={}),
        }
    )
    gh.update_file("req.txt", "fastapi\n", "medic/fix", "fix")
    method, _, kwargs = gh.session.calls[-1]
    assert method == "PUT" and kwargs["json"]["sha"] == "old" and kwargs["json"]["branch"] == "medic/fix"
    assert base64.b64decode(kwargs["json"]["content"]) == b"fastapi\n"


def test_branch_helpers():
    gh = client({("GET", "/git/ref/heads/medic/fix"): Response(), ("POST", "/git/refs"): Response(payload={})})
    assert gh.branch_exists("medic/fix") and not gh.branch_exists("other")
    gh.create_branch("medic/fix", "abc")
    assert gh.session.calls[-1][2]["json"] == {"ref": "refs/heads/medic/fix", "sha": "abc"}


def test_open_pull_request_returns_the_url():
    gh = client({("POST", "/pulls"): Response(payload={"html_url": "https://github.test/pull/1"})})
    assert gh.open_pull_request("t", "b", "head", "base") == "https://github.test/pull/1"


def test_blocked_pull_request_raises_a_clear_error():
    gh = client({("POST", "/pulls"): Response(status=403)})
    with pytest.raises(PullRequestsNotAllowed):
        gh.open_pull_request("t", "b", "head", "base")


def test_issues_and_labels():
    gh = client(
        {
            ("POST", "/issues"): Response(payload={"html_url": "https://github.test/issues/4"}),
            ("GET", "/issues"): Response(payload=[{"title": "CI failed"}]),
            ("POST", "/issues/4/labels"): Response(payload={}),
            ("POST", "/actions/runs/9/rerun-failed-jobs"): Response(payload={}),
        }
    )
    assert gh.open_issue("CI failed", "body").endswith("/issues/4")
    assert gh.issue_exists("CI failed") and not gh.issue_exists("other")
    gh.add_label("https://github.test/issues/4", "pipeline-medic")
    assert gh.session.calls[-1][2]["json"] == {"labels": ["pipeline-medic"]}
    gh.rerun_failed_jobs(9)


def test_label_problems_never_fail_the_run():
    gh = client({})
    gh.add_label("https://github.test/issues/not-a-number", "x")
    gh.add_label("https://github.test/issues/5", "x")  # 404 from the fake
