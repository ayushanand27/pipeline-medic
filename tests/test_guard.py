import pytest

from medic.config import Config
from medic.guard import PlanRejected, check, is_allowed
from medic.models import FileChange, Plan

CFG = Config()


def plan(*changes: FileChange) -> Plan:
    return Plan("cause", list(changes), "llm")


def test_small_change_in_allowed_folder_passes():
    check(plan(FileChange("demo-app/app/pricing.py", "a = 1\n", "a = 2\n")), CFG)


@pytest.mark.parametrize(
    "path",
    [".github/workflows/demo-ci.yml", "medic/guard.py", "deploy/k8s/deployment.yaml", "README.md", "/etc/passwd", "demo-app/../medic/guard.py"],
)
def test_paths_outside_the_allowed_folder_are_blocked(path):
    assert not is_allowed(path, CFG)
    with pytest.raises(PlanRejected):
        check(plan(FileChange(path, "a\n", "b\n")), CFG)


def test_big_change_is_rejected():
    new = "".join(f"line {number}\n" for number in range(50))
    with pytest.raises(PlanRejected, match="limit"):
        check(plan(FileChange("demo-app/app/pricing.py", "a\n", new)), CFG)


def test_too_many_files_is_rejected():
    changes = [FileChange(f"demo-app/f{number}.py", "a\n", "b\n") for number in range(4)]
    with pytest.raises(PlanRejected):
        check(plan(*changes), CFG)


def test_empty_or_no_op_plan_is_rejected():
    with pytest.raises(PlanRejected):
        check(plan(), CFG)
    with pytest.raises(PlanRejected):
        check(plan(FileChange("demo-app/app/pricing.py", "same\n", "same\n")), CFG)
