import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .config import AnalysisConfig, ResearchConfig, RunConfig
from .csv_store import CsvStore
from .models import RunStatus, UNAVAILABLE_RESEARCH
from .research_manager import ResearchManager, company_key
from .analysis_manager import AnalysisManager


class RetryCoordinator:
    def __init__(self, run: RunConfig, research: ResearchManager, analysis: AnalysisManager, store: CsvStore):
        self.run_config = run
        self.research = research
        self.analysis = analysis
        self.store = store
        self.status = RunStatus()
        self.affected_rows: dict[str, list[dict]] = {}
        self.primary_refresh_phase = True

    def _companies(self, rows: list[dict]) -> dict[str, str]:
        return {
            company_key(row.get("Current_Company")): str(row.get("Current_Company", "")).strip()
            for row in rows if str(row.get("Current_Company", "")).strip()
        }

    def _research_for_batch(self, rows: list[dict]) -> dict[str, str]:
        companies = self._companies(rows)
        if self.research.config.no_web_search:
            return {key: "Web search disabled by command-line option." for key in companies}
        results = self.research.research_companies(
            companies,
            self.research.config.refresh and self.primary_refresh_phase,
        )
        reports = {}
        for key, name in companies.items():
            report = self.research.cached_report(key)
            if report:
                reports[key] = report
                continue
            reports[key] = UNAVAILABLE_RESEARCH
            self.status.research_failures[key] = {
                "company": name,
                "row_ids": [],
                "last_error": results.get(key).error if key in results else "",
            }
            self.affected_rows.setdefault(key, []).extend(
                row for row in rows if company_key(row.get("Current_Company")) == key
            )
        return reports

    def _analyze_pass(self, targets: list[dict], label: str) -> list[dict]:
        errors = []
        for start in range(0, len(targets), self.run_config.batch_size):
            batch = targets[start:start + self.run_config.batch_size]
            reports = self._research_for_batch(batch)
            with ThreadPoolExecutor(max_workers=max(1, self.analysis.config.workers)) as pool:
                futures = {
                    pool.submit(
                        self.analysis.analyze_one,
                        row,
                        reports.get(company_key(row.get("Current_Company")), UNAVAILABLE_RESEARCH),
                    ): row
                    for row in batch
                }
                for future in as_completed(futures):
                    row = futures[future]
                    try:
                        row.update(future.result())
                        CsvStore.mark_updated(row)
                    except Exception as exc:
                        has_valid_result = (
                            row.get("AI_Judgement") in {"Yes", "No"}
                            and str(row.get("AI_Explanation", "")).strip()
                        )
                        if not has_valid_result:
                            row["AI_Judgement"], row["AI_Weighting"], row["AI_Explanation"] = "Error", 0, str(exc)
                            errors.append(row)
                        else:
                            print(f"Preserved previous valid result for row {row.get('id', '')}: {exc}")
            self.store.save()
            print(f"{label}: saved {min(start + self.run.batch_size, len(targets))}/{len(targets)} rows")
        return errors

    def _retry_research(self) -> None:
        self.primary_refresh_phase = False
        for round_number in range(1, self.research.config.max_rounds + 1):
            if not self.status.research_failures:
                break
            self.status.research_rounds = round_number
            companies = {
                key: item["company"] for key, item in self.status.research_failures.items()
            }
            results = self.research.research_companies(companies, refresh=True)
            recovered = [key for key, result in results.items() if result.usable]
            for key in recovered:
                rows = list({id(row): row for row in self.affected_rows.get(key, [])}.values())
                for row in rows:
                    self.status.faulty_rows.pop(str(row.get("id", id(row))), None)
                del self.status.research_failures[key]
                self._analyze_pass(rows, f"P1 recovery round {round_number}")
            if not recovered:
                print(f"No company research recovered in round {round_number}.")

    def run(self, targets: list[dict]) -> RunStatus:
        errors = self._analyze_pass(targets, "Main analysis pass")
        self.status.faulty_rows = {
            str(row.get("id", id(row))): {"row_id": str(row.get("id", ""))}
            for row in errors
        }
        self._retry_research()
        for round_number in range(1, self.run_config.max_error_rounds + 1):
            error_rows = [row for row in targets if row.get("AI_Judgement") == "Error"]
            if not error_rows:
                break
            self.status.analysis_rounds = round_number
            errors = self._analyze_pass(error_rows, f"AI error retry round {round_number}")
            self.status.faulty_rows = {
                str(row.get("id", id(row))): {"row_id": str(row.get("id", ""))}
                for row in errors
            }
        for key, item in self.status.research_failures.items():
            item["row_ids"] = [str(row.get("id", "")) for row in self.affected_rows.get(key, [])]
        return self.status

    def save_status(self, status_path: Path, targets: list[dict]) -> None:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "rows_targeted": len(targets),
            "batch_size": self.run_config.batch_size,
            "research_workers": self.research.config.workers,
            "analysis_workers": self.analysis.config.workers,
            "research_model": self.research.config.model,
            "research_provider": self.research.config.provider,
            "research_failures": list(self.status.research_failures.values()),
            "faulty_row_ids": sorted(self.status.faulty_rows),
            "faulty_row_count": len(self.status.faulty_rows),
        }
        status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
