"""Decide the root cause and the fix.

Two layers:
1. Rules for errors that have one known fix (missing package, version that does not exist).
2. An LLM for everything else (for example a failing test). It is optional.
"""

import json
import re

import requests

from .config import Config
from .log_parser import BAD_PIN, MISSING_MODULE, Failure
from .models import FileChange, Plan

# Import name -> PyPI package name, for the common cases where they differ.
_PACKAGE_NAMES = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
}

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _requirement_name(line: str) -> str:
    match = _REQ_NAME.match(line)
    return match.group(1).lower().replace("_", "-") if match else ""


def rule_based(failure: Failure, files: dict[str, str]) -> Plan | None:
    """files maps a dependency file path to its current text."""
    if failure.kind == MISSING_MODULE:
        package = _PACKAGE_NAMES.get(failure.detail, failure.detail)
        for path, text in files.items():
            names = [_requirement_name(line) for line in text.splitlines()]
            if package.lower() in names:
                continue  # already listed, so this file is not the problem
            new = text if text.endswith("\n") or not text else text + "\n"
            new += package + "\n"
            cause = (
                f"The code imports `{failure.detail}` but `{package}` is not listed in `{path}`, "
                "so it was never installed in CI."
            )
            return Plan(cause, [FileChange(path, text, new)], "rule")

    if failure.kind == BAD_PIN:
        name = _requirement_name(failure.detail)
        for path, text in files.items():
            lines = text.splitlines(keepends=True)
            for index, line in enumerate(lines):
                if name and _requirement_name(line) == name and line.strip() != name:
                    ending = "\n" if line.endswith("\n") else ""
                    lines[index] = name + ending
                    cause = (
                        f"`{path}` asks for `{failure.detail}`, and pip could not find that version. "
                        "The pin is removed so pip installs the latest working version. "
                        "Pin it again to a real version after checking."
                    )
                    return Plan(cause, [FileChange(path, text, "".join(lines))], "rule")
    return None


_SYSTEM_PROMPT = """You fix failing CI builds.
You get the error part of a CI log and the files involved.
Find the root cause and give the smallest change that fixes it.
Fix the application code, not the test, unless the test itself is clearly wrong.
Reply with JSON only, in this shape:
{"root_cause": "one or two plain sentences",
 "edits": [{"path": "file path exactly as given", "search": "exact text to replace", "replace": "new text"}]}
Each "search" must be copied exactly from the file and must appear only once in it.
If you are not sure, return an empty "edits" list."""


def _parse_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.find("{") :]
    start, end = content.find("{"), content.rfind("}")
    return json.loads(content[start : end + 1])


def llm_based(failure: Failure, files: dict[str, str], cfg: Config, post=None) -> Plan | None:
    """Ask the LLM. Returns None if it is off, fails, or gives nothing usable."""
    if not cfg.llm_enabled or not files:
        return None

    file_blocks = "\n\n".join(f"--- {path} ---\n{text}" for path, text in files.items())
    user_prompt = f"Failed check: {failure.detail}\n\nLog:\n{failure.excerpt}\n\nFiles:\n{file_blocks}"
    post = post or requests.post
    try:
        response = post(
            f"{cfg.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {cfg.llm_api_key}"},
            json={
                "model": cfg.llm_model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        answer = _parse_json(response.json()["choices"][0]["message"]["content"])
    except (requests.RequestException, KeyError, IndexError, ValueError) as error:
        print(f"medic: LLM step failed: {error}")
        return None

    changes: dict[str, FileChange] = {}
    for edit in answer.get("edits") or []:
        path, search, replace = edit.get("path"), edit.get("search"), edit.get("replace")
        if path not in files or not search or replace is None:
            return None
        current = changes[path].new if path in changes else files[path]
        if current.count(search) != 1:
            return None  # the model did not copy the text exactly, so do not guess
        changes[path] = FileChange(path, files[path], current.replace(search, replace))

    root_cause = str(answer.get("root_cause") or "").strip()
    if not changes or not root_cause:
        return None
    return Plan(root_cause, list(changes.values()), "llm")
