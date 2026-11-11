"""Build the input file for the OPA policy check.

Usage:
    python scripts/policy_input.py demo-app:<tag> security.json > policy-input.json

It puts together the Kubernetes objects we are about to apply (with the real image)
and the security summary from `python -m medic.triage`.
"""

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def inside_repo(path: str) -> Path:
    """The file name comes from the command line, so only accept files inside this repo."""
    base = os.path.realpath(ROOT)
    full = os.path.realpath(path)
    if not full.startswith(base + os.sep):
        sys.exit(f"refusing to read '{path}': it is outside the repository")
    return Path(full)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    image, security_file = sys.argv[1], sys.argv[2]
    text = (ROOT / "deploy" / "k8s" / "deployment.yaml").read_text(encoding="utf-8")
    text = text.replace("demo-app:IMAGE_TAG", image)
    manifests = [doc for doc in yaml.safe_load_all(text) if doc]
    security = json.loads(inside_repo(security_file).read_text(encoding="utf-8"))
    security.pop("findings", None)  # the policy only needs the counts
    json.dump({"manifests": manifests, "security": security}, sys.stdout, indent=2)
