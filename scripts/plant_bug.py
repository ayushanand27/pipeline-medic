"""Break the demo app on purpose, so you can watch pipeline-medic fix it.

Usage:
    python scripts/plant_bug.py missing-dep   # a package the code needs is removed from requirements
    python scripts/plant_bug.py bad-pin       # a package is pinned to a version that does not exist
    python scripts/plant_bug.py logic-bug     # a real bug in the price logic, so a test fails

Then commit on a new branch and push. demo-ci fails, and medic opens a PR (or an issue).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "demo-app" / "requirements.txt"
PRICING = ROOT / "demo-app" / "app" / "pricing.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        sys.exit(f"expected to find {old!r} exactly once in {path.name}; is a bug already planted?")
    path.write_text(text.replace(old, new), encoding="utf-8")


BUGS = {
    "missing-dep": lambda: replace_once(REQUIREMENTS, "fastapi\n", ""),
    "bad-pin": lambda: replace_once(REQUIREMENTS, "fastapi\n", "fastapi==99.0.0\n"),
    "logic-bug": lambda: replace_once(
        PRICING, "0 if discounted >= FREE_DELIVERY_ABOVE", "0 if amount >= FREE_DELIVERY_ABOVE"
    ),
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in BUGS:
        sys.exit(__doc__)
    BUGS[sys.argv[1]]()
    print(f"planted: {sys.argv[1]}")
