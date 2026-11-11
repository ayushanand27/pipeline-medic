"""Build the input file for the OPA policy check.

Usage:
    python scripts/policy_input.py demo-app:<tag> > reports/policy-input.json

It puts together the Kubernetes objects we are about to apply (with the real image)
and the security summary that `python -m medic.triage` wrote to reports/security.json.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


SECURITY_FILE = ROOT / "reports" / "security.json"  # fixed location, written by medic.triage


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    image = sys.argv[1]
    if not SECURITY_FILE.is_file():
        sys.exit("reports/security.json not found. Run `python -m medic.triage --out reports/security.json` first.")
    text = (ROOT / "deploy" / "k8s" / "deployment.yaml").read_text(encoding="utf-8")
    text = text.replace("demo-app:IMAGE_TAG", image)
    manifests = [doc for doc in yaml.safe_load_all(text) if doc]
    security = json.loads(SECURITY_FILE.read_text(encoding="utf-8"))
    security.pop("findings", None)  # the policy only needs the counts
    json.dump({"manifests": manifests, "security": security}, sys.stdout, indent=2)
