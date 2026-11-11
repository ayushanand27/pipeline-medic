"""All settings come from environment variables, so the same code runs locally and in CI."""

import os
from dataclasses import dataclass, field


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class Config:
    # The agent may only edit files under these folders.
    allowed_paths: list[str] = field(default_factory=lambda: ["demo-app/"])
    # The agent may never edit files under these folders, even if allowed above.
    blocked_paths: list[str] = field(default_factory=lambda: [".github/", "deploy/", "medic/"])
    # Dependency files the rule-based fixes look at, in order.
    requirements_paths: list[str] = field(default_factory=lambda: ["demo-app/requirements.txt"])
    max_files_changed: int = 3
    max_changed_lines: int = 20
    # Optional LLM (any OpenAI-compatible API). Without a key only the rule-based fixes run.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls()
        if os.getenv("MEDIC_ALLOWED_PATHS"):
            cfg.allowed_paths = _split(os.environ["MEDIC_ALLOWED_PATHS"])
        if os.getenv("MEDIC_REQUIREMENTS_PATHS"):
            cfg.requirements_paths = _split(os.environ["MEDIC_REQUIREMENTS_PATHS"])
        cfg.llm_base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        cfg.llm_api_key = os.getenv("LLM_API_KEY", "")
        cfg.llm_model = os.getenv("LLM_MODEL", "")
        return cfg
