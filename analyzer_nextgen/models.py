from dataclasses import dataclass, field


UNAVAILABLE_RESEARCH = (
    "Priority 1 research unavailable after the configured research retries. "
    "Do not infer company qualification from missing research."
)


@dataclass
class ResearchResult:
    company_key: str
    company: str
    report: str = ""
    usable: bool = False
    error: str = ""
    attempts: int = 0


@dataclass
class RunStatus:
    research_failures: dict[str, dict] = field(default_factory=dict)
    faulty_rows: dict[str, dict] = field(default_factory=dict)
    research_rounds: int = 0
    analysis_rounds: int = 0
