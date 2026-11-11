"""MCP server: lets an IDE assistant or another agent use pipeline-medic as tools.

Run it (stdio transport):
    GITHUB_TOKEN=... MEDIC_REPO=owner/name python -m medic.mcp_server

Needs the extra package in requirements-mcp.txt.
"""

import os

from mcp.server.mcpserver import MCPServer

from . import tools
from .config import Config
from .github_client import GitHub

server = MCPServer(
    "pipeline-medic",
    instructions=(
        "Tools for failed CI runs of one GitHub repository. "
        "Use explain_failure first. It is read-only. "
        "Call open_fix only when the user wants the fix pushed, because it creates a branch and a pull request."
    ),
)


def _github() -> GitHub:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("MEDIC_REPO")
    if not token or not repo:
        raise RuntimeError("set GITHUB_TOKEN and MEDIC_REPO (owner/name) before starting the server")
    return GitHub(token, repo)


@server.tool()
def list_failed_runs(limit: int = 5) -> list[dict]:
    """List the most recent failed CI runs of the repository, newest first."""
    return tools.list_failed_runs(_github(), limit)


@server.tool()
def explain_failure(run_id: int) -> dict:
    """Explain why a CI run failed: the error, the root cause and the proposed fix as a diff. Read-only."""
    return tools.explain_failure(_github(), run_id, Config.from_env())


@server.tool()
def open_fix(run_id: int) -> dict:
    """Push the proposed fix for a failed run on a new branch and open a pull request. This writes to the repository."""
    return tools.open_fix(_github(), run_id, Config.from_env())


if __name__ == "__main__":
    server.run()
