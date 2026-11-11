"""Turn a raw CI log into a small, structured Failure.

This part is plain code (regex), not an LLM. It is cheap, repeatable and easy to test.
"""

import re
from dataclasses import dataclass, field

# GitHub Actions puts a timestamp in front of every log line.
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z ?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")
_BAD_PIN = re.compile(r"No matching distribution found for (\S+)")
_FAILED_TEST = re.compile(r"^FAILED (\S+)", re.MULTILINE)
_PY_PATH = re.compile(r"([\w\-./]+\.py)(?::\d+|\", line \d+)")

MISSING_MODULE = "missing_module"
BAD_PIN = "bad_pin"
TEST_FAILURE = "test_failure"
UNKNOWN = "unknown"


@dataclass
class Failure:
    kind: str
    detail: str  # module name, bad requirement, or failed test id
    excerpt: str  # the part of the log around the error
    files: list[str] = field(default_factory=list)  # python files named in the log


def clean(log_text: str) -> str:
    """Remove timestamps and colour codes so the patterns below can match."""
    lines = []
    for line in log_text.splitlines():
        line = _ANSI.sub("", line.lstrip("﻿"))
        lines.append(_TIMESTAMP.sub("", line))
    return "\n".join(lines)


def _excerpt(text: str, position: int, before: int = 25, after: int = 15) -> str:
    lines = text.splitlines()
    line_no = text.count("\n", 0, position)
    start = max(0, line_no - before)
    return "\n".join(lines[start : line_no + after + 1])


def _files_in(text: str) -> list[str]:
    seen: list[str] = []
    for match in _PY_PATH.finditer(text):
        path = match.group(1)
        if "site-packages" in path or path in seen:
            continue
        seen.append(path)
    return seen


def extract_failure(log_text: str) -> Failure:
    """Find the first known error in the log. Order matters: install errors come first."""
    text = clean(log_text)

    match = _BAD_PIN.search(text)
    if match:
        return Failure(BAD_PIN, match.group(1), _excerpt(text, match.start()))

    match = _MISSING_MODULE.search(text)
    if match:
        module = match.group(1).split(".")[0]
        return Failure(MISSING_MODULE, module, _excerpt(text, match.start()))

    match = _FAILED_TEST.search(text)
    if match:
        # For a test failure the useful part is the traceback, which pytest prints
        # above the "FAILED ..." summary line.
        excerpt = _excerpt(text, match.start(), before=60, after=5)
        return Failure(TEST_FAILURE, match.group(1), excerpt, _files_in(excerpt))

    error_at = text.find("##[error]")
    position = error_at if error_at != -1 else max(0, len(text) - 1)
    return Failure(UNKNOWN, "", _excerpt(text, position, before=40, after=5))
