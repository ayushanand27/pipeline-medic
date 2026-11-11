"""Safety checks that run on every plan before anything is written.

The agent is not trusted blindly. Code decides what it is allowed to touch.
"""

import difflib

from .config import Config
from .models import Plan


class PlanRejected(Exception):
    pass


def changed_lines(old: str, new: str) -> int:
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return sum(
        1
        for line in diff
        if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
    )


def is_allowed(path: str, cfg: Config) -> bool:
    if path.startswith("/") or ".." in path.split("/"):
        return False
    if any(path.startswith(blocked) for blocked in cfg.blocked_paths):
        return False
    return any(path.startswith(allowed) for allowed in cfg.allowed_paths)


def check(plan: Plan, cfg: Config) -> None:
    """Raise PlanRejected if the plan breaks a rule. Do nothing if it is fine."""
    if not plan.changes:
        raise PlanRejected("the plan changes no files")
    if len(plan.changes) > cfg.max_files_changed:
        raise PlanRejected(f"the plan changes more than {cfg.max_files_changed} files")

    total = 0
    for change in plan.changes:
        if not is_allowed(change.path, cfg):
            raise PlanRejected(f"`{change.path}` is outside the folders the agent may edit")
        if change.old == change.new:
            raise PlanRejected(f"`{change.path}` is not actually changed")
        total += changed_lines(change.old, change.new)
    if total > cfg.max_changed_lines:
        raise PlanRejected(f"the plan changes {total} lines, the limit is {cfg.max_changed_lines}")


def render_diff(plan: Plan) -> str:
    parts = []
    for change in plan.changes:
        diff = difflib.unified_diff(
            change.old.splitlines(),
            change.new.splitlines(),
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
            lineterm="",
        )
        parts.append("\n".join(diff))
    return "\n".join(parts)
