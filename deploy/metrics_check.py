"""Ask Prometheus for the error rate of the new release.

Usage:
    python deploy/metrics_check.py http://127.0.0.1:19090

Exit code 0 = error rate is fine. Exit code 1 = too many errors (or no data).
"""

import os
import sys
import time

import requests

MIN_REQUESTS = int(os.getenv("MIN_REQUESTS", "20"))  # wait until Prometheus has seen this many
MAX_ERROR_RATIO = float(os.getenv("MAX_ERROR_RATIO", "0.01"))  # 1%
WAIT_SECONDS = int(os.getenv("METRICS_WAIT_SECONDS", "90"))

# /health is left out: the readiness probe calls it all the time, and it would hide real traffic.
TOTAL = 'sum(http_requests_total{path!="/health"})'
ERRORS = 'sum(http_requests_total{path!="/health",status=~"5.."})'


def query(base_url: str, promql: str) -> float:
    response = requests.get(f"{base_url}/api/v1/query", params={"query": promql}, timeout=10)
    response.raise_for_status()
    result = response.json()["data"]["result"]
    return float(result[0]["value"][1]) if result else 0.0


def error_ratio(total: float, errors: float) -> float:
    return errors / total if total else 0.0


def verdict(total: float, errors: float) -> tuple[bool, str]:
    if total < MIN_REQUESTS:
        return False, f"only {total:.0f} requests seen, need {MIN_REQUESTS} to judge"
    ratio = error_ratio(total, errors)
    message = f"{errors:.0f} server errors in {total:.0f} requests ({ratio * 100:.2f}%), limit {MAX_ERROR_RATIO * 100:.2f}%"
    return ratio <= MAX_ERROR_RATIO, message


def main(base_url: str) -> int:
    deadline = time.time() + WAIT_SECONDS
    total = 0.0
    while time.time() < deadline:
        try:
            total = query(base_url, TOTAL)
        except requests.RequestException:
            total = 0.0
        if total >= MIN_REQUESTS:
            break
        time.sleep(5)
    try:
        errors = query(base_url, ERRORS)
    except requests.RequestException as error:
        print(f"metric check: cannot reach Prometheus: {error}")
        return 1
    passed, message = verdict(total, errors)
    print(f"metric check: {message}")
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1].rstrip("/")))
