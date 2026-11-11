"""The agent loop: read the failed run -> diagnose -> check the plan -> open a PR or an issue."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from . import guard
from .config import Config
from .diagnose import llm_based, rule_based
from .github_client import PullRequestsNotAllowed
from .log_parser import BAD_PIN, MISSING_MODULE, TEST_FAILURE, TRANSIENT, Failure, extract_failure
from .models import Plan
from .verify import VerifyResult, verify_plan

BRANCH_PREFIX = "medic/"
LABEL = "pipeline-medic"
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
    action: str  # "pull_request", "issue", "rerun" or "skipped"
    message: str
    url: str = ""
    kind: str = ""  # what failed
    verified: str = ""  # "passed", "failed" or "not run"


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


def _context_files(
    failure: Failure, read_file: ReadFile, cfg: Config, changed_files: list[str] | None = None
) -> dict[str, str]:
    if failure.kind in (MISSING_MODULE, BAD_PIN):
        candidates = list(cfg.requirements_paths)
    elif failure.kind == TEST_FAILURE:
        test_file = failure.detail.split("::")[0]
        candidates = []
        for log_path in failure.files + [test_file]:
            candidates.extend(_repo_paths(log_path, cfg))
        # The commit that broke the build is the most likely place for the bug.
        candidates.extend(path for path in (changed_files or []) if path.endswith(".py"))
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


def diagnose(
    log_text: str, read_file: ReadFile, cfg: Config, changed_files: list[str] | None = None
) -> Diagnosis:
    """Pure decision step. No GitHub writes happen here, so it is easy to test."""
    failure = extract_failure(log_text)
    if failure.kind == TRANSIENT:
        return Diagnosis(failure, None, "This looks like a network or service problem, not a code problem.")
    files = _context_files(failure, read_file, cfg, changed_files)

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


def _changed_section(changed_files: list[str]) -> str:
    if not changed_files:
        return ""
    listed = "\n".join(f"- `{path}`" for path in changed_files[:15])
    return f"**Files changed in the failing commit**\n{listed}\n\n"


def _verify_section(result: VerifyResult | None) -> str:
    if result is None:
        return "**Verification**\nNot run (no verify command is configured). Check the fix before merging.\n\n"
    state = "passed" if result.passed else "FAILED"
    return (
        f"**Verification**\nThe fix was applied to a clean copy of the failing commit and "
        f"`{result.command}` {state}.\n\n```\n{result.output[-1500:]}\n```\n\n"
    )


def _pr_body(run: dict, diagnosis: Diagnosis, changed_files: list[str], result: VerifyResult | None) -> str:
    plan = diagnosis.plan
    how = "a fixed rule" if plan.source == "rule" else "an LLM (please review with extra care)"
    return (
        f"The CI run [{run['name']} #{run['run_number']}]({run['html_url']}) failed.\n\n"
        f"**Root cause**\n{plan.root_cause}\n\n"
        f"**Fix**\nProposed by {how}. Changes:\n\n```diff\n{guard.render_diff(plan)}\n```\n\n"
        f"{_verify_section(result)}"
        f"{_changed_section(changed_files)}"
        f"**Log**\n```\n{diagnosis.failure.excerpt[-3000:]}\n```\n\n"
        "Opened by pipeline-medic. A person must review and merge it."
    )


def _issue_body(run: dict, diagnosis: Diagnosis, changed_files: list[str], extra: str = "") -> str:
    failure = diagnosis.failure
    return (
        f"The CI run [{run['name']} #{run['run_number']}]({run['html_url']}) failed "
        f"on branch `{run['head_branch']}`.\n\n"
        f"**What failed:** `{failure.kind}` {failure.detail}\n\n"
        f"**Why there is no fix PR:** {diagnosis.note}\n\n"
        f"{extra}"
        f"{_changed_section(changed_files)}"
        f"**Log**\n```\n{failure.excerpt[-3000:]}\n```\n\n"
        "Opened by pipeline-medic."
    )


def _changed_files(gh, sha: str) -> list[str]:
    try:
        return gh.commit_files(sha)
    except Exception:  # extra context only, never worth failing the run for
        return []


def diagnose_run(gh, run: dict, run_id: int, cfg: Config, changed_files: list[str] | None = None) -> Diagnosis:
    """Read-only: download the logs of a failed run and work out the fix. Writes nothing."""
    log_text = "\n".join(gh.job_log(job["id"]) for job in gh.failed_jobs(run_id))
    sha = run["head_sha"]
    if changed_files is None:
        changed_files = _changed_files(gh, sha)
    return diagnose(log_text, lambda path: gh.get_file(path, sha), cfg, changed_files)


def _open_issue(gh, run: dict, run_id: int, diagnosis: Diagnosis, changed: list[str], extra: str = "") -> Outcome:
    title = f"CI failed on {run['head_branch']}: {diagnosis.failure.kind} (run {run_id})"
    if gh.issue_exists(title):
        return Outcome("skipped", "an issue for this run already exists", kind=diagnosis.failure.kind)
    url = gh.open_issue(title, _issue_body(run, diagnosis, changed, extra))
    gh.add_label(url, LABEL)
    return Outcome("issue", diagnosis.note, url, kind=diagnosis.failure.kind)


def handle_run(gh, run_id: int, cfg: Config, verifier=verify_plan) -> Outcome:
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

    sha = run["head_sha"]
    changed = _changed_files(gh, sha)
    diagnosis = diagnose_run(gh, run, run_id, cfg, changed)
    kind = diagnosis.failure.kind

    if kind == TRANSIENT:
        # Retry once. If the second attempt also fails, a person should look.
        if run.get("run_attempt", 1) == 1:
            gh.rerun_failed_jobs(run_id)
            message = f"network or service problem ({diagnosis.failure.detail}), failed jobs restarted"
            return Outcome("rerun", message, kind=kind)
        diagnosis.note += " It already failed again after one automatic retry."
        return _open_issue(gh, run, run_id, diagnosis, changed)

    if diagnosis.plan is None:
        return _open_issue(gh, run, run_id, diagnosis, changed)

    result = None
    if cfg.verify_command:
        result = verifier(diagnosis.plan, sha, cfg.verify_command, timeout=cfg.verify_timeout_seconds)
        if not result.passed:
            # A fix that does not make the check pass is not worth a pull request.
            proposed = (
                f"**Proposed fix (rejected)**\n```diff\n{guard.render_diff(diagnosis.plan)}\n```\n\n"
                f"{_verify_section(result)}"
            )
            diagnosis.note = "A fix was proposed, but the check still failed with it applied."
            outcome = _open_issue(gh, run, run_id, diagnosis, changed, proposed)
            outcome.verified = "failed"
            return outcome
    verified = "not run" if result is None else "passed"

    gh.create_branch(fix_branch, sha)
    for change in diagnosis.plan.changes:
        gh.update_file(change.path, change.new, fix_branch, f"fix: {change.path} (CI run {run_id})")
    title = f"Fix CI: {kind.replace('_', ' ')} {diagnosis.failure.detail}".strip()
    body = _pr_body(run, diagnosis, changed, result)
    try:
        url = gh.open_pull_request(title[:120], body, fix_branch, branch)
    except PullRequestsNotAllowed:
        # The fix is already pushed. Do not lose it: point to the branch from an issue.
        compare = f"https://github.com/{gh.repo}/compare/{branch}...{fix_branch}?expand=1"
        note = (
            f"The fix is on branch `{fix_branch}`. [Open the pull request here]({compare}).\n\n"
            "I could not open it myself. To allow that: Settings → Actions → General → "
            "tick **Allow GitHub Actions to create and approve pull requests**.\n\n"
        )
        url = gh.open_issue(title[:120], note + body)
        gh.add_label(url, LABEL)
        return Outcome(
            "issue", "fix pushed, but this repo does not let Actions open pull requests", url, kind, verified
        )
    gh.add_label(url, LABEL)
    return Outcome("pull_request", diagnosis.plan.root_cause, url, kind, verified)
