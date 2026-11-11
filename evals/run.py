"""Evaluation set for the agent's decisions.

Unit tests check single functions. This checks the behaviour that matters to a user:
for a given failed build, does the agent pick the right response?

    fix      = propose a code change
    retry    = run the job again (network or service problem)
    escalate = do not touch the code, hand it to a person with a diagnosis

Run:  python -m evals.run
Exit code 1 if the score is below the required level. CI runs this on every push.
"""

import json
import sys
from pathlib import Path

from medic.agent import diagnose
from medic.config import Config
from medic.log_parser import TRANSIENT

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_SCORE = 1.0  # the rule-based layer must get every case right


def run_case(case: dict) -> tuple[bool, str]:
    log = (ROOT / case["log_file"]).read_text(encoding="utf-8") if "log_file" in case else case["log"]
    files = case["files"]
    result = diagnose(log, files.get, Config())

    if result.failure.kind == TRANSIENT:
        decision = "retry"
    elif result.plan is not None:
        decision = "fix"
    else:
        decision = "escalate"

    expect = case["expect"]
    problems = []
    if result.failure.kind != expect["kind"]:
        problems.append(f"kind {result.failure.kind}, expected {expect['kind']}")
    if decision != expect["decision"]:
        problems.append(f"decision {decision}, expected {expect['decision']}")
    if "adds" in expect and result.plan is not None:
        new_text = "".join(change.new for change in result.plan.changes)
        if expect["adds"] not in new_text:
            problems.append(f"fix does not contain {expect['adds']!r}")
    return (not problems, "; ".join(problems) or f"{result.failure.kind} -> {decision}")


def main() -> int:
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        ok, detail = run_case(case)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['name']}: {detail}")
    score = passed / len(cases)
    print(f"\nscore: {passed}/{len(cases)} ({score:.0%}), required {REQUIRED_SCORE:.0%}")
    return 0 if score >= REQUIRED_SCORE else 1


if __name__ == "__main__":
    sys.exit(main())
