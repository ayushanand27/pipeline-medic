from dataclasses import dataclass


@dataclass
class FileChange:
    path: str
    old: str
    new: str


@dataclass
class Plan:
    root_cause: str
    changes: list[FileChange]
    source: str  # "rule" or "llm"
