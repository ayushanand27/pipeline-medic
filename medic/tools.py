"""The agent's abilities as plain functions. The MCP server exposes these as tools."""

from . import guard
from .agent import diagnose_run, handle_run
from .config import Config


def list_failed_runs(gh, limit: int = 5) -> list[dict]:
    """Recent failed CI runs, newest first."""
    return [
        {
            "run_id": run["id"],
            "workflow": run["name"],
            "branch": run["head_branch"],
            "commit": run["head_sha"][:7],
            "url": run["html_url"],
        }
        for run in gh.list_failed_runs(max(1, min(limit, 20)))
    ]


def explain_failure(gh, run_id: int, cfg: Config) -> dict:
    """Why a run failed and what the fix would be. Read-only: nothing is changed."""
    run = gh.get_run(run_id)
    if run.get("conclusion") != "failure":
        return {"run_id": run_id, "failed": False, "message": "this run did not fail"}
    diagnosis = diagnose_run(gh, run, run_id, cfg)
    result = {
        "run_id": run_id,
        "failed": True,
        "branch": run["head_branch"],
        "kind": diagnosis.failure.kind,
        "detail": diagnosis.failure.detail,
        "log_excerpt": diagnosis.failure.excerpt[-2000:],
    }
    if diagnosis.plan is None:
        result.update({"fix_available": False, "note": diagnosis.note})
    else:
        result.update(
            {
                "fix_available": True,
                "root_cause": diagnosis.plan.root_cause,
                "fix_source": diagnosis.plan.source,
                "diff": guard.render_diff(diagnosis.plan),
            }
        )
    return result


def open_fix(gh, run_id: int, cfg: Config) -> dict:
    """Push the fix on a new branch and open a pull request (or an issue if there is no safe fix)."""
    outcome = handle_run(gh, run_id, cfg)
    return {"action": outcome.action, "message": outcome.message, "url": outcome.url}
