from dataclasses import dataclass, field


@dataclass
class Classification:
    customer_type: str
    maintenance_status: str
    metadata: dict = field(default_factory=dict)


@dataclass
class RunState:
    completed_accounts: set[str] = field(default_factory=set)
    errors: list[dict] = field(default_factory=list)
    ai_results: list[dict] = field(default_factory=list)
    phase: str = "starting"
    round_number: int = 0
