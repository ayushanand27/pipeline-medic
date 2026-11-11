"""Check that every package in demo-app/requirements.txt is pinned in demo-app/requirements.lock.

Refresh the lock with:
    pip install uv
    uv pip compile demo-app/requirements.txt --python-version 3.12 --no-header \\
        --generate-hashes -o demo-app/requirements.lock
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^([A-Za-z0-9_.\-]+)")


def names(path: Path) -> set[str]:
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = NAME.match(line.strip())
        if match and not line.lstrip().startswith("#"):
            found.add(match.group(1).lower().replace("_", "-"))
    return found


if __name__ == "__main__":
    wanted = names(ROOT / "demo-app" / "requirements.txt")
    locked = names(ROOT / "demo-app" / "requirements.lock")
    missing = sorted(wanted - locked)
    if missing:
        sys.exit(f"not in requirements.lock: {', '.join(missing)}\n{__doc__}")
    print(f"lock is in sync ({len(wanted)} packages, {len(locked)} pinned)")
