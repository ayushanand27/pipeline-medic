"""The LLM step, built as a LangChain chain:  prompt -> chat model -> JSON parser.

Any OpenAI-compatible API works (set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL).
The chat model can be swapped, which is how the tests run this chain without a network.
"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from .config import Config

# The log and the files are passed in as variables, so braces inside them are never read as template fields.
PROMPT = ChatPromptTemplate.from_messages([("system", "{system}"), ("human", "{user}")])


def build_chain(cfg: Config, model=None):
    if model is None:
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=cfg.llm_model,
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            temperature=0,  # same input should give the same fix
            timeout=60,
            max_retries=1,
        )
    return PROMPT | model | JsonOutputParser()


def ask(system: str, user: str, cfg: Config, model=None) -> dict:
    """Run the chain once and return the model's answer as a dict."""
    return build_chain(cfg, model).invoke({"system": system, "user": user})
