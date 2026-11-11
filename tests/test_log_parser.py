from pathlib import Path

import pytest

from medic.log_parser import BAD_PIN, MISSING_MODULE, TEST_FAILURE, TRANSIENT, UNKNOWN, extract_failure

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_missing_module_is_found():
    failure = extract_failure(load("missing_module.log"))
    assert failure.kind == MISSING_MODULE
    assert failure.detail == "fastapi"


def test_bad_pin_is_found():
    failure = extract_failure(load("bad_pin.log"))
    assert failure.kind == BAD_PIN
    assert failure.detail == "fastapi==99.0.0"


def test_failed_test_is_found_with_its_file():
    failure = extract_failure(load("test_failure.log"))
    assert failure.kind == TEST_FAILURE
    assert failure.detail == "demo-app/tests/test_pricing.py::test_coupon_is_applied_before_delivery_check"
    assert "demo-app/tests/test_pricing.py" in failure.files
    assert "AssertionError" in failure.excerpt


def test_timestamps_are_removed_from_the_excerpt():
    failure = extract_failure(load("missing_module.log"))
    assert "2026-11-11T17:00:00" not in failure.excerpt


def test_submodule_import_reports_the_top_package():
    failure = extract_failure("ModuleNotFoundError: No module named 'yaml.loader'")
    assert failure.detail == "yaml"


def test_unknown_error_does_not_crash():
    failure = extract_failure("step one\n##[error]Process completed with exit code 2.\n")
    assert failure.kind == UNKNOWN
    assert "exit code 2" in failure.excerpt


def test_empty_log_does_not_crash():
    assert extract_failure("").kind == UNKNOWN


@pytest.mark.parametrize(
    "line",
    [
        "curl: (6) Could not resolve host: github.com",
        "urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(host='pypi.org', port=443): Read timed out.",
        "error: RPC failed; HTTP 503 Service Unavailable",
        "toomanyrequests: 429 Too Many Requests",
        "##[error]The runner has received a shutdown signal.",
    ],
)
def test_network_and_service_problems_are_transient(line):
    assert extract_failure(f"step 1\n{line}\n##[error]exit code 1").kind == TRANSIENT


def test_a_real_error_wins_over_a_network_warning():
    log = "WARNING: Retrying after connection broken: Read timed out\nModuleNotFoundError: No module named 'fastapi'\n"
    assert extract_failure(log).kind == MISSING_MODULE
