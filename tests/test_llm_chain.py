"""The LangChain chain is run for real here, with a fake chat model in place of the network."""

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from medic.config import Config
from medic.diagnose import llm_based
from medic.llm_chain import PROMPT, ask
from medic.log_parser import TEST_FAILURE, Failure

CFG = Config(llm_base_url="http://llm.test/v1", llm_api_key="k", llm_model="m")


def model_saying(text: str) -> FakeListChatModel:
    return FakeListChatModel(responses=[text])


def test_chain_returns_the_json_answer():
    answer = ask("system", "user", CFG, model=model_saying('{"root_cause": "r", "edits": []}'))
    assert answer == {"root_cause": "r", "edits": []}


def test_chain_reads_json_inside_a_code_fence():
    fenced = "```json\n{\"root_cause\": \"r\", \"edits\": []}\n```"
    assert ask("system", "user", CFG, model=model_saying(fenced))["root_cause"] == "r"


def test_chain_raises_on_an_answer_that_is_not_json():
    with pytest.raises(OutputParserException):
        ask("system", "user", CFG, model=model_saying("sorry, I cannot help"))


def test_braces_in_logs_and_code_are_not_read_as_template_fields():
    messages = PROMPT.format_messages(system="reply as {json}", user="data = {'a': 1}")
    assert messages[0].content == "reply as {json}" and messages[1].content == "data = {'a': 1}"


def test_real_chain_feeds_the_fix_logic():
    files = {"demo-app/app/pricing.py": "x = amount >= LIMIT\n"}
    reply = (
        '{"root_cause": "wrong value", "edits": [{"path": "demo-app/app/pricing.py", '
        '"search": "amount >= LIMIT", "replace": "discounted >= LIMIT"}]}'
    )

    def chain_ask(system, user, cfg):
        return ask(system, user, cfg, model=model_saying(reply))

    plan = llm_based(Failure(TEST_FAILURE, "t.py::test_a", "AssertionError"), files, CFG, ask=chain_ask)
    assert plan.changes[0].new == "x = discounted >= LIMIT\n"
