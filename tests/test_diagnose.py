import json

from medic.config import Config
from medic.diagnose import llm_based, rule_based
from medic.log_parser import BAD_PIN, MISSING_MODULE, TEST_FAILURE, Failure

REQ = "demo-app/requirements.txt"


def test_missing_module_is_added_to_requirements():
    plan = rule_based(Failure(MISSING_MODULE, "fastapi", ""), {REQ: "uvicorn\nhttpx\n"})
    assert plan.changes[0].new == "uvicorn\nhttpx\nfastapi\n"
    assert plan.source == "rule"


def test_import_name_is_mapped_to_package_name():
    plan = rule_based(Failure(MISSING_MODULE, "yaml", ""), {REQ: "uvicorn"})
    assert plan.changes[0].new == "uvicorn\npyyaml\n"


def test_module_already_listed_gives_no_plan():
    assert rule_based(Failure(MISSING_MODULE, "fastapi", ""), {REQ: "fastapi\n"}) is None


def test_bad_pin_is_removed_and_other_lines_are_kept():
    plan = rule_based(Failure(BAD_PIN, "fastapi==99.0.0", ""), {REQ: "uvicorn\nfastapi==99.0.0\nhttpx\n"})
    assert plan.changes[0].new == "uvicorn\nfastapi\nhttpx\n"


def test_test_failure_has_no_rule():
    assert rule_based(Failure(TEST_FAILURE, "t.py::test_x", ""), {"demo-app/app/x.py": "a = 1\n"}) is None


class FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def llm_config() -> Config:
    return Config(llm_base_url="http://llm.test/v1", llm_api_key="k", llm_model="m")


FILES = {"demo-app/app/pricing.py": "x = amount >= LIMIT\ny = 2\n"}
FAILURE = Failure(TEST_FAILURE, "demo-app/tests/test_pricing.py::test_a", "AssertionError")


def fake_post(answer):
    content = answer if isinstance(answer, str) else json.dumps(answer)
    return lambda *args, **kwargs: FakeResponse(content)


def test_llm_edit_is_applied():
    answer = {
        "root_cause": "Delivery is checked on the wrong value.",
        "edits": [{"path": "demo-app/app/pricing.py", "search": "amount >= LIMIT", "replace": "discounted >= LIMIT"}],
    }
    plan = llm_based(FAILURE, FILES, llm_config(), post=fake_post(answer))
    assert plan.source == "llm"
    assert plan.changes[0].new == "x = discounted >= LIMIT\ny = 2\n"


def test_llm_answer_inside_a_code_fence_is_read():
    answer = '```json\n{"root_cause": "r", "edits": [{"path": "demo-app/app/pricing.py", "search": "y = 2", "replace": "y = 3"}]}\n```'
    assert llm_based(FAILURE, FILES, llm_config(), post=fake_post(answer)) is not None


def test_llm_edit_that_does_not_match_the_file_is_dropped():
    answer = {"root_cause": "r", "edits": [{"path": "demo-app/app/pricing.py", "search": "not in file", "replace": "z"}]}
    assert llm_based(FAILURE, FILES, llm_config(), post=fake_post(answer)) is None


def test_llm_edit_to_a_file_it_was_not_given_is_dropped():
    answer = {"root_cause": "r", "edits": [{"path": ".github/workflows/ci.yml", "search": "a", "replace": "b"}]}
    assert llm_based(FAILURE, FILES, llm_config(), post=fake_post(answer)) is None


def test_llm_garbage_answer_gives_no_plan():
    assert llm_based(FAILURE, FILES, llm_config(), post=fake_post("sorry, I cannot help")) is None


def test_llm_is_skipped_without_a_key():
    def must_not_be_called(*args, **kwargs):
        raise AssertionError("LLM was called without a key")

    assert llm_based(FAILURE, FILES, Config(), post=must_not_be_called) is None
