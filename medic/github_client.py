"""A thin wrapper over the GitHub REST API. Only the calls the agent needs."""

import base64

import requests

API = "https://api.github.com"


class PullRequestsNotAllowed(Exception):
    """The token may push branches but may not open pull requests (a repo setting)."""


class GitHub:
    def __init__(self, token: str, repo: str):
        self.repo = repo  # "owner/name"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _url(self, path: str) -> str:
        return f"{API}/repos/{self.repo}{path}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self.session.request(method, self._url(path), timeout=30, **kwargs)
        response.raise_for_status()
        return response

    # ---- reading the failed run -------------------------------------------------
    def get_run(self, run_id: int) -> dict:
        return self._request("GET", f"/actions/runs/{run_id}").json()

    def failed_jobs(self, run_id: int) -> list[dict]:
        jobs = self._request("GET", f"/actions/runs/{run_id}/jobs", params={"per_page": 100}).json()["jobs"]
        return [job for job in jobs if job.get("conclusion") == "failure"]

    def job_log(self, job_id: int) -> str:
        return self._request("GET", f"/actions/jobs/{job_id}/logs").text

    def get_file(self, path: str, ref: str) -> str | None:
        """Return the file text at a commit, or None if the file does not exist."""
        response = self.session.get(self._url(f"/contents/{path}"), params={"ref": ref}, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) or data.get("type") != "file":
            return None
        return base64.b64decode(data["content"]).decode("utf-8")

    # ---- writing the fix --------------------------------------------------------
    def branch_exists(self, branch: str) -> bool:
        response = self.session.get(self._url(f"/git/ref/heads/{branch}"), timeout=30)
        return response.status_code == 200

    def create_branch(self, branch: str, from_sha: str) -> None:
        self._request("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": from_sha})

    def update_file(self, path: str, text: str, branch: str, message: str) -> None:
        current = self._request("GET", f"/contents/{path}", params={"ref": branch}).json()
        self._request(
            "PUT",
            f"/contents/{path}",
            json={
                "message": message,
                "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
                "branch": branch,
                "sha": current["sha"],
            },
        )

    def open_pull_request(self, title: str, body: str, head: str, base: str) -> str:
        payload = {"title": title, "body": body, "head": head, "base": base}
        response = self.session.post(self._url("/pulls"), json=payload, timeout=30)
        if response.status_code == 403:
            raise PullRequestsNotAllowed()
        response.raise_for_status()
        return response.json()["html_url"]

    def open_issue(self, title: str, body: str) -> str:
        return self._request("POST", "/issues", json={"title": title, "body": body}).json()["html_url"]

    def issue_exists(self, title: str) -> bool:
        issues = self._request("GET", "/issues", params={"state": "open", "per_page": 100}).json()
        return any(issue.get("title") == title for issue in issues)
