"""The agent loop: read the failed run -> diagnose -> check the plan -> open a PR or an issue."""

import re
from dataclasses import dataclass
from typing import Callable

from . import guard
from .config import Config
from .diagnose import llm_based, rule_based
from .log_parser import BAD_PIN, MISSING_MODULE, TEST_FAILURE, Failure, extract_failure
from .models import Plan

BRANCH_PREFIX = "medic/"
MAX_CONTEXT_FILES = 4
MAX_FILE_CHARS = 8000

ReadFile = Callable[[str], str | None]
_IMPORT = re.compile(r"^(?:from|import) ([\w.]+)", re.MULTILINE)


@dataclass
class Diagnosis:
    failure: Failure
    plan: Plan | None
    note: str  # why there is no plan, when there is none


@dataclass
class Outcome:
    action: str  # "pull_request", "issue" or "skipped"
    message: str
    url: str = ""


def _repo_paths(log_path: str, cfg: Config) -> list[str]:
    """Logs show paths in different forms. Turn one into possible repo paths."""
    log_path = log_path.lstrip("./")
    for allowed in cfg.allowed_paths:
        index = log_path.find(allowed)
        if index != -1:
            return [log_path[index:]]
    return [allowed + log_path for allowed in cfg.allowed_paths]


def _imported_modules(test_text: str) -> list[str]:
    """A failing test usually names only the test file. The bug is in the code it imports,
    so turn `from app.pricing import x` into `app/pricing.py`."""
    return [module.replace(".", "/") + ".py" for module in _IMPORT.findall(test_text)]


def _context_files(failure: Failure, read_file: ReadFile, cfg: Config) -> dict[str, str]:
    if failure.kind in (MISSING_MODULE, BAD_PIN):
        candidates = list(cfg.requirements_paths)
    elif failure.kind == TEST_FAILURE:
        test_file = failure.detail.split("::")[0]
        candidates = []
        for log_path in failure.files + [test_file]:
            candidates.extend(_repo_paths(log_path, cfg))
    else:
        candidates = []

    files: dict[str, str] = {}

    def add(path: str) -> str | None:
        if path in files or len(files) >= MAX_CONTEXT_FILES or not guard.is_allowed(path, cfg):
            return None
        text = read_file(path)
        if text is not None and len(text) <= MAX_FILE_CHARS:
            files[path] = text
        return text

    for path in candidates:
        text = add(path)
        if text and failure.kind == TEST_FAILURE:
            for module_path in _imported_modules(text):
                for repo_path in _repo_paths(module_path, cfg):
                    add(repo_path)
    return files


def diagnose(log_text: str, read_file: ReadFile, cfg: Config) -> Diagnosis:
    """Pure decision step. No GitHub writes happen here, so it is easy to test."""
    failure = extract_failure(log_text)
    files = _context_files(failure, read_file, cfg)

    plan = rule_based(failure, files) or llm_based(failure, files, cfg)
    if plan is None:
        if cfg.llm_enabled:
            return Diagnosis(failure, None, "No safe automatic fix was found.")
        return Diagnosis(failure, None, "No rule matches this failure and the LLM step is turned off.")
    try:
        guard.check(plan, cfg)
    except guard.PlanRejected as rejected:
        return Diagnosis(failure, None, f"A fix was proposed but the guardrails rejected it: {rejected}.")
    return Diagnosis(failure, plan, "")


def _pr_body(run: dict, diagnosis: Diagnosis) -> str:
    plan = diagnosis.plan
    how = "a fixed rule" if plan.source == "rule" else "an LLM (please review with extra care)"
    return (
        f"The CI run [{run['name']} #{run['run_number']}]({run['html_url']}) failed.\n\n"
        f"**Root cause**\n{plan.root_cause}\n\n"
        f"**Fix**\nProposed by {how}. Changes:\n\n```diff\n{guard.render_diff(plan)}\n```\n\n"
        f"**Log**\n```\n{diagnosis.failure.excerpt[-3000:]}\n```\n\n"
        "Opened by pipeline-medic. A person must review and merge it."
    )


def _issue_body(run: dict, diagnosis: Diagnosis) -> str:
    failure = diagnosis.failure
    return (
        f"The CI run [{run['name']} #{run['run_number']}]({run['html_url']}) failed "
        f"on branch `{run['head_branch']}`.\n\n"
        f"**What failed:** `{failure.kind}` {failure.detail}\n\n"
        f"**Why there is no fix PR:** {diagnosis.note}\n\n"
        f"**Log**\n```\n{failure.excerpt[-3000:]}\n```\n\n"
        "Opened by pipeline-medic."
    )


def handle_run(gh, run_id: int, cfg: Config) -> Outcome:
    run = gh.get_run(run_id)
    if run.get("conclusion") != "failure":
        return Outcome("skipped", f"run {run_id} did not fail")
    branch = run["head_branch"]
    if branch.startswith(BRANCH_PREFIX):
        # Never try to fix our own fix branch. This stops an endless loop.
        return Outcome("skipped", f"`{branch}` is a medic branch")

    fix_branch = f"{BRANCH_PREFIX}fix-run-{run_id}"
    if gh.branch_exists(fix_branch):
        return Outcome("skipped", f"`{fix_branch}` already exists")

    log_text = "\n".join(gh.job_log(job["id"]) for job in gh.failed_jobs(run_id))
    sha = run["head_sha"]
    diagnosis = diagnose(log_text, lambda path: gh.get_file(path, sha), cfg)

    if diagnosis.plan is None:
        title = f"CI failed on {branch}: {diagnosis.failure.kind} (run {run_id})"
        if gh.issue_exists(title):
            return Outcome("skipped", "an issue for this run already exists")
        url = gh.open_issue(title, _issue_body(run, diagnosis))
        return Outcome("issue", diagnosis.note, url)

    gh.create_branch(fix_branch, sha)
    for change in diagnosis.plan.changes:
        gh.update_file(change.path, change.new, fix_branch, f"fix: {change.path} (CI run {run_id})")
    title = f"Fix CI: {diagnosis.failure.kind.replace('_', ' ')} {diagnosis.failure.detail}".strip()
    url = gh.open_pull_request(title[:120], _pr_body(run, diagnosis), fix_branch, branch)
    return Outcome("pull_request", diagnosis.plan.root_cause, url)
