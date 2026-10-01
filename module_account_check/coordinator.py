from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from .ai_checker import AiChecker
from .checkpoint_store import CheckpointStore
from .csv_store import save_csv
from .deterministic_checker import classify
from .models import Classification, RunState
from .run_logger import RunLogger


class Coordinator:
    def __init__(self, accounts, opportunities, model_config, run_config, as_of: date, api_key: str):
        self.accounts = accounts
        self.by_account = {}
        for row in opportunities: self.by_account.setdefault(row.get("Account Short Name", ""), []).append(row)
        self.model_config, self.run_config, self.as_of = model_config, run_config, as_of
        self.ai = None if run_config.no_ai else AiChecker(model_config, api_key)
        self.state = RunState()
        self.checkpoint = CheckpointStore(run_config.output_json.with_suffix(".checkpoint.json"))
        self.logger = RunLogger(run_config.output_json.with_suffix(".events.jsonl"))
        self.results = {name: classify(name, rows, as_of) for name, rows in self.by_account.items()}

    def _apply(self):
        for row in self.accounts:
            result = self.results.get(row.get("Account Short Name", ""), Classification("", ""))
            row["AI_customer_type"], row["AI_maintenance_status"] = result.customer_type, result.maintenance_status

    def _save(self, phase):
        self._apply(); save_csv(self.run_config.output_csv, self.accounts)
        self.state.phase = phase
        self.checkpoint.save({"phase": phase, "completed_accounts": sorted(self.state.completed_accounts), "errors": self.state.errors, "round": self.state.round_number})

    def _protected(self, deterministic: Classification, ai: dict) -> bool:
        rule = str(deterministic.metadata.get("rule", ""))
        if rule.startswith("legacy MA-only history through 2016"):
            return not (ai["customer_type"] == deterministic.customer_type and ai["maintenance_status"] == deterministic.maintenance_status)
        if rule in {"completed software purchase without following MA", "latest MA lost without later closed-won event", "historical MA without continuation"}:
            return not (ai["customer_type"] == "Existing buyout software customer" and ai["maintenance_status"] == "Expired")
        if deterministic.customer_type == "RTO customer": return ai["customer_type"] != "RTO customer"
        if deterministic.customer_type == "Existing buyout software customer" and deterministic.maintenance_status == "Ongoing":
            return ai["customer_type"] in {"Leasing customer", "PPU customer"}
        return False

    def run(self):
        candidates = [name for name, result in self.results.items() if result.metadata.get("ambiguous") or result.metadata.get("edge_case") or result.metadata.get("rule") in {"unclassified", "legacy MA-only history through 2016; expired software customer"}]
        if self.ai and candidates:
            for round_no in range(self.run_config.max_error_rounds + 1):
                self.state.round_number = round_no + 1
                pending = [name for name in candidates if name not in self.state.completed_accounts]
                if not pending: break
                round_completed = 0
                last_checkpoint = time.monotonic()
                with ThreadPoolExecutor(max_workers=max(1, self.model_config.workers)) as pool:
                    futures = {pool.submit(self.ai.classify, name, self.by_account[name]): name for name in pending}
                    for future in as_completed(futures):
                        name = futures[future]
                        deterministic = self.results[name]
                        try:
                            ai = future.result()
                            if not self._protected(deterministic, ai):
                                self.results[name] = Classification(ai["customer_type"], ai["maintenance_status"], {"rule": "AI", "deterministic": deterministic.metadata})
                            self.state.completed_accounts.add(name)
                            self.state.ai_results.append({"account": name, "ai": ai, "deterministic": deterministic.metadata})
                        except Exception as exc:
                            self.state.errors.append({"account": name, "error": str(exc), "deterministic": deterministic.metadata})
                        round_completed += 1
                        now = time.monotonic()
                        if round_completed % max(1, self.run_config.checkpoint_every) == 0 or now - last_checkpoint >= self.run_config.checkpoint_seconds:
                            self._save(f"ai_round_{round_no + 1}_checkpoint")
                            self.logger.log("checkpoint_saved", round=round_no + 1, completed_in_round=round_completed, total_in_round=len(pending))
                            last_checkpoint = now
                self._save(f"ai_round_{round_no + 1}")
        self._save("completed")
        summary = {"account_rows": len(self.accounts), "opportunity_rows": sum(len(v) for v in self.by_account.values()), "unique_accounts": len(self.by_account), "errors": len(self.state.errors), "ai_accounts": len(self.state.ai_results), "customer_type_counts": {}, "maintenance_status_counts": {}}
        for row in self.accounts:
            summary["customer_type_counts"][row.get("AI_customer_type") or "<blank>"] = summary["customer_type_counts"].get(row.get("AI_customer_type") or "<blank>", 0) + 1
            summary["maintenance_status_counts"][row.get("AI_maintenance_status") or "<blank>"] = summary["maintenance_status_counts"].get(row.get("AI_maintenance_status") or "<blank>", 0) + 1
        payload = {"summary": summary, "errors": self.state.errors, "ai_accounts": self.state.ai_results, "checkpoint": str(self.checkpoint.path)}
        self.run_config.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
