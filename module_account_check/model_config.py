from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelConfig:
    base_url: str = "http://ai.moldex3d.com:4000/v1"
    model: str = "gpt-5.6-luna"
    api_key_file: Path = Path(__file__).parent.parent / "analyzer" / "openai-api.txt"
    timeout_seconds: int = 180
    workers: int = 16
    max_retries: int = 2


@dataclass(frozen=True)
class RunConfig:
    account_csv: Path = Path(__file__).parent / "salesforce_data" / "account_target_check.csv"
    opty_csv: Path = Path(__file__).parent / "salesforce_data" / "opty_check.csv"
    output_csv: Path = Path(__file__).parent / "salesforce_data" / "account_target_check.csv"
    output_json: Path = Path(__file__).parent / "salesforce_data" / "account_target_check.json"
    as_of_date: str = ""
    checkpoint_every: int = 25
    checkpoint_seconds: int = 60
    max_error_rounds: int = 2
    no_ai: bool = False
