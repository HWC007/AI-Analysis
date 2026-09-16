import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

from .config import AnalysisConfig, ResearchConfig, RunConfig
from .csv_store import CsvStore
from .models import RunStatus, UNAVAILABLE_RESEARCH
from .research_manager import ResearchManager, company_key
from .analysis_manager import AnalysisManager


class CancellationRequested(RuntimeError):
    pass


class RetryCoordinator:
    def __init__(self, run: RunConfig, research: ResearchManager, analysis: AnalysisManager, store: CsvStore, logger=None, checkpoint=None, cancel_event=None, checkpoint_state=None):
        self.run_config = run
        self.research = research
        self.analysis = analysis
        self.store = store
        self.status = RunStatus()
        self.affected_rows: dict[str, list[dict]] = {}
        self.primary_refresh_phase = True
        self.logger = logger
        self.checkpoint = checkpoint
        self.cancel_event = cancel_event
        self.completed_row_ids = set((checkpoint_state or {}).get("completed_row_ids", []))

    def _check_cancelled(self):
        if self.cancel_event and self.cancel_event.is_set():
            raise CancellationRequested("Cancellation requested")

    def _save_checkpoint(self, phase: str, **extra):
        if not self.checkpoint:
            return
        state = {
            "status": self.status.status,
            "phase": phase,
            "completed_row_ids": sorted(self.completed_row_ids),
            "research_failures": list(self.status.research_failures),
            "faulty_row_ids": sorted(self.status.faulty_rows),
            **extra,
        }
        self.checkpoint.save(state)

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
            self._check_cancelled()
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
                pending = set(futures)
                while pending:
                    # Polling keeps Ctrl+C/cancel_event responsive on Windows
                    # instead of waiting indefinitely inside as_completed().
                    self._check_cancelled()
                    done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    for future in done:
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
            self.completed_row_ids.update(str(row.get("id", "")) for row in batch if row.get("id", "") != "")
            self._save_checkpoint("analysis", batch_completed=start + len(batch), total_targets=len(targets), label=label)
            if self.logger:
                self.logger.log("batch_saved", label=label, batch_completed=start + len(batch), total_targets=len(targets), row_ids=[str(row.get("id", "")) for row in batch])
            print(f"{label}: saved {min(start + self.run_config.batch_size, len(targets))}/{len(targets)} rows")
        return errors

    def _retry_research(self) -> None:
        self.primary_refresh_phase = False
        for round_number in range(1, self.research.config.max_rounds + 1):
            self._check_cancelled()
            if not self.status.research_failures:
                break
            self.status.research_rounds = round_number
            self._save_checkpoint("research_recovery", research_round=round_number)
            companies = {
                key: item["company"] for key, item in self.status.research_failures.items()
            }
            results = self.research.research_companies(companies, refresh=True)
            recovered = [key for key, result in results.items() if result.usable]
            for key in recovered:
                rows = list({id(row): row for row in self.affected_rows.get(key, [])}.values())
                del self.status.research_failures[key]
                new_errors = self._analyze_pass(rows, f"P1 recovery round {round_number}")
                new_error_ids = {str(row.get("id", id(row))) for row in new_errors}
                for row in rows:
                    row_id = str(row.get("id", id(row)))
                    if row_id not in new_error_ids:
                        self.status.faulty_rows.pop(row_id, None)
                for row in new_errors:
                    row_id = str(row.get("id", id(row)))
                    self.status.faulty_rows[row_id] = {"row_id": str(row.get("id", ""))}
            if not recovered:
                print(f"No company research recovered in round {round_number}.")

    def run(self, targets: list[dict]) -> RunStatus:
        try:
            self._save_checkpoint("analysis", total_targets=len(targets))
            errors = self._analyze_pass(targets, "Main analysis pass")
            self.status.faulty_rows = {
                str(row.get("id", id(row))): {"row_id": str(row.get("id", ""))}
                for row in errors
            }
            self._retry_research()
            for round_number in range(1, self.run_config.max_error_rounds + 1):
                self._check_cancelled()
                error_rows = [row for row in targets if row.get("AI_Judgement") == "Error"]
                if not error_rows:
                    break
                self.status.analysis_rounds = round_number
                errors = self._analyze_pass(error_rows, f"AI error retry round {round_number}")
                self.status.faulty_rows = {
                    str(row.get("id", id(row))): {"row_id": str(row.get("id", ""))}
                    for row in errors
                }
        except CancellationRequested:
            self.status.status = "interrupted"
            self._save_checkpoint("interrupted")
            if self.logger:
                self.logger.log("run_interrupted", completed_row_count=len(self.completed_row_ids))
            return self.status
        self.status.status = "completed"
        self._save_checkpoint("completed")
        if self.logger:
            self.logger.log("run_completed", faulty_row_count=len(self.status.faulty_rows), research_failure_count=len(self.status.research_failures))
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
            "status": self.status.status,
        }
        status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
