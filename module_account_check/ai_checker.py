from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from .deterministic_checker import TYPES, STATUSES
from .model_config import ModelConfig


class AiChecker:
    def __init__(self, config: ModelConfig, api_key: str, logger=None):
        self.config, self.api_key, self.logger = config, api_key, logger
        rules_path = Path(__file__).with_name("ai_rules.md")
        rules = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else ""
        self.system = (
            "Classify one exact account's opportunity history. Return JSON only with "
            "customer_type and maintenance_status. Allowed customer_type values: "
            + ", ".join(sorted(TYPES - {""}))
            + ". Allowed statuses: Ongoing, Expired, or empty. Respect the deterministic "
            "timeline evidence. Active direct relationships (RTO, MA/buyout, leasing, or PPU) "
            "always supersede alliance activity. Alliance is selected only when no active direct "
            "relationship remains. An incomplete RTO is RTO customer; completed RTO is buyout. "
            "Do not invent evidence.\n\nDetailed classification contract:\n" + rules
        )

    def classify(self, account: str, rows: list[dict]) -> dict[str, str]:
        body = {"model": self.config.model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [
            {"role": "system", "content": self.system},
            {"role": "user", "content": json.dumps({"account_short_name": account, "opportunities": rows}, ensure_ascii=False)},
        ]}
        last = ""
        for attempt in range(1, self.config.max_retries + 1):
            try:
                req = urllib.request.Request(self.config.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                    result = json.loads(response.read().decode())
                content = result["choices"][0]["message"]["content"]
                value = json.loads(content) if isinstance(content, str) else content
                ctype, status = value.get("customer_type", ""), value.get("maintenance_status", "")
                if ctype not in TYPES or status not in STATUSES: raise ValueError("AI taxonomy validation failed")
                return {"customer_type": ctype, "maintenance_status": status}
            except Exception as exc:
                last = str(exc)
                if attempt < self.config.max_retries: time.sleep(min(30, 2 ** attempt))
        raise RuntimeError(f"AI classification failed for {account}: {last}")
