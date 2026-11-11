import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "metrics_check", Path(__file__).resolve().parent.parent / "deploy" / "metrics_check.py"
)
metrics_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics_check)


def test_no_errors_passes():
    passed, message = metrics_check.verdict(total=40, errors=0)
    assert passed and "0 server errors in 40 requests" in message


def test_too_many_errors_fails():
    passed, _ = metrics_check.verdict(total=100, errors=5)
    assert not passed


def test_exactly_at_the_limit_passes():
    passed, _ = metrics_check.verdict(total=100, errors=1)
    assert passed


def test_too_little_traffic_is_not_trusted():
    passed, message = metrics_check.verdict(total=3, errors=0)
    assert not passed and "need 20" in message
