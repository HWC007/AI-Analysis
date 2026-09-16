from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResearchConfig:
    base_url: str = "http://ai.moldex3d.com:4000/v1"
    provider: str = "openai"
    model: str = "gpt-5.2"
    search_context_size: str = "medium"
    workers: int = 8
    max_retries: int = 3
    max_rounds: int = 3
    cache_path: Path = Path("company-research-cache.json")
    no_web_search: bool = False
    refresh: bool = False


@dataclass(frozen=True)
class AnalysisConfig:
    base_url: str = "http://ai.moldex3d.com:4000/v1"
    model: str = "gpt-5.6-luna"
    workers: int = 8
    max_retries: int = 3
    prompt_path: Path = Path(__file__).with_name("analysis_prompt.md")


@dataclass(frozen=True)
class RunConfig:
    input_path: Path = Path("Apify-raw-structured.csv")
    output_path: Path = Path("Apify-raw-structured.csv")
    api_key_file: Path = Path(__file__).parent.parent / "analyzer" / "openai-api.txt"
    api_key: str = ""
    batch_size: int = 20
    chunk_size: int = 100
    max_error_rounds: int = 10
    status_report_path: Path | None = None
    ids: frozenset[str] | None = None
    reanalyze_all: bool = False
    limit: int = 0
    run_dir: Path = Path("analyzer_nextgen_runs")
    resume_checkpoint: Path | None = None
