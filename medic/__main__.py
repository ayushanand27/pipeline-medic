"""Command line entry point.

Real run (what the GitHub Action does):
    python -m medic --repo owner/name --run-id 123456

Dry run on a saved log, no GitHub needed:
    python -m medic --log-file tests/fixtures/missing_module.log --workdir .
"""

import argparse
import os
import sys
from pathlib import Path

from . import guard
from .agent import diagnose, handle_run
from .config import Config
from .github_client import GitHub


def _write_summary(run_id: int, outcome) -> None:
    """Show the result on the workflow run page (GitHub reads this file)."""
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    lines = [
        "## pipeline-medic",
        "",
        "| Run | What failed | Action | Fix verified | Link |",
        "| --- | --- | --- | --- | --- |",
        f"| {run_id} | {outcome.kind or '-'} | {outcome.action} | {outcome.verified or '-'} | {outcome.url or '-'} |",
        "",
        outcome.message,
        "",
    ]
    with open(summary_file, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="medic", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/name")
    parser.add_argument("--run-id", type=int, help="id of the failed GitHub Actions run")
    parser.add_argument("--log-file", help="dry run: read this log file, do not call GitHub")
    parser.add_argument("--workdir", default=".", help="dry run: folder that holds the repo files")
    args = parser.parse_args(argv)
    cfg = Config.from_env()

    if args.log_file:
        root = Path(args.workdir)

        def read_file(path: str) -> str | None:
            target = root / path
            return target.read_text(encoding="utf-8") if target.is_file() else None

        result = diagnose(Path(args.log_file).read_text(encoding="utf-8"), read_file, cfg)
        print(f"failure: {result.failure.kind} {result.failure.detail}")
        if result.plan is None:
            print(f"no fix: {result.note}")
            return 0
        print(f"root cause ({result.plan.source}): {result.plan.root_cause}")
        print(guard.render_diff(result.plan))
        return 0

    token = os.getenv("GITHUB_TOKEN")
    if not (args.repo and args.run_id and token):
        parser.error("give --repo and --run-id and set GITHUB_TOKEN, or use --log-file for a dry run")
    outcome = handle_run(GitHub(token, args.repo), args.run_id, cfg)
    print(f"medic: {outcome.action}: {outcome.message} {outcome.url}".strip())
    _write_summary(args.run_id, outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
