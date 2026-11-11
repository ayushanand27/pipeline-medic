"""Tests for the agent's tools and for the MCP server that exposes them."""

import asyncio

import pytest

from medic import tools
from medic.config import Config
from test_agent import FakeGitHub


class FakeGitHubWithRuns(FakeGitHub):
    def list_failed_runs(self, limit=5):
        run = dict(self.run, id=42, head_sha="abc1234567")
        return [run][:limit]


def test_list_failed_runs_gives_short_rows():
    gh = FakeGitHubWithRuns("missing_module.log", {})
    assert tools.list_failed_runs(gh) == [
        {"run_id": 42, "workflow": "demo-ci", "branch": "feature", "commit": "abc1234", "url": "https://github.test/run/7"}
    ]


def test_explain_failure_is_read_only():
    gh = FakeGitHubWithRuns("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    result = tools.explain_failure(gh, 42, Config())
    assert result["fix_available"] and result["fix_source"] == "rule"
    assert "+fastapi" in result["diff"]
    assert not gh.branches and not gh.written and not gh.pull_requests and not gh.issues


def test_explain_failure_without_a_fix_says_why():
    gh = FakeGitHubWithRuns("test_failure.log", {})
    result = tools.explain_failure(gh, 42, Config())
    assert result["fix_available"] is False and "LLM" in result["note"]


def test_explain_failure_on_a_passing_run():
    gh = FakeGitHubWithRuns("missing_module.log", {}, conclusion="success")
    assert tools.explain_failure(gh, 42, Config())["failed"] is False


def test_open_fix_opens_a_pull_request():
    gh = FakeGitHubWithRuns("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    result = tools.open_fix(gh, 42, Config())
    assert result["action"] == "pull_request" and result["url"]


def test_mcp_server_lists_and_runs_the_tools(monkeypatch):
    pytest.importorskip("mcp")
    from mcp import Client

    from medic import mcp_server

    gh = FakeGitHubWithRuns("missing_module.log", {"demo-app/requirements.txt": "uvicorn\n"})
    monkeypatch.setattr(mcp_server, "_github", lambda: gh)

    async def scenario():
        async with Client(mcp_server.server) as client:
            listed = await client.list_tools()
            result = await client.call_tool("explain_failure", {"run_id": 42})
            return {tool.name for tool in listed.tools}, result

    names, result = asyncio.run(scenario())
    assert names == {"list_failed_runs", "explain_failure", "open_fix"}
    assert "fastapi" in str(result)
    assert not gh.pull_requests  # explain_failure must not write
