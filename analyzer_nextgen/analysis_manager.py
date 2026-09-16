import json
import re
import time
import urllib.request
from pathlib import Path

from .config import AnalysisConfig
from .response_parser import parse_response


class AnalysisManager:
    def __init__(self, config: AnalysisConfig, api_key: str, logger=None):
        self.config = config
        self.api_key = api_key
        self.logger = logger
        self.definition_prompt = Path(config.prompt_path).read_text(encoding="utf-8")

    def analyze_one(self, row: dict, research: str) -> dict:
        profile = {
            key: re.sub("\\u00b7", "-", str(value)) if key.endswith("Tenure") else str(value)
            for key, value in row.items()
            if key not in {"AI_Judgement", "AI_Weighting", "AI_Explanation", "createdAt", "updatedAt"}
        }
        prompt = (
            "Use the complete Priority 1–5 definitions and scoring rules in the supplied analysis specification.\n\n"
            + self.definition_prompt
            + "\n\nGPT WEB RESEARCH FOR PRIORITY 1:\n"
            + research
            + "\n\nPROSPECT DATA:\n"
            + json.dumps(profile, ensure_ascii=False)
        )
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": "Return only the valid JSON object required by the analysis specification."},
                {"role": "user", "content": prompt},
            ],
        }
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        last_error = ""
        for attempt in range(1, self.config.max_retries + 1):
            started = time.monotonic()
            if self.logger:
                self.logger.log("analysis_attempt_start", row_id=str(row.get("id", "")), model=self.config.model, attempt=attempt)
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    data = json.loads(response.read().decode())
                content = data["choices"][0]["message"]["content"]
                normalized = parse_response(content)
                p1 = bool(normalized.get("priority_1_satisfied"))
                p2 = bool(normalized.get("priority_2_satisfied"))
                p3 = bool(normalized.get("priority_3_satisfied"))
                p4 = bool(normalized.get("priority_4_satisfied"))
                p5 = bool(normalized.get("priority_5_satisfied"))
                p4_other = bool(normalized.get("p4_in_other_sections"))
                p4_skills = bool(normalized.get("p4_in_skills_only"))
                p4_score = 0.05 if p4 and p4_other else 0.025 if p4 and p4_skills else 0
                result = {
                    "AI_Judgement": "Yes" if p1 or p2 or p3 or p5 else "No",
                    "AI_Weighting": round((2 if p1 else 0) + (2.5 if p2 else 0) + (1 if p3 else 0) + p4_score + (5 if p5 else 0), 3),
                    "AI_Explanation": normalized["explanation"],
                }
                if self.logger:
                    self.logger.log("analysis_attempt_success", row_id=str(row.get("id", "")), model=self.config.model, attempt=attempt, elapsed_seconds=round(time.monotonic() - started, 3))
                return result
            except Exception as exc:
                last_error = str(exc)
                if self.logger:
                    self.logger.log("analysis_attempt_failure", row_id=str(row.get("id", "")), model=self.config.model, attempt=attempt, elapsed_seconds=round(time.monotonic() - started, 3), error=last_error)
                if attempt < self.config.max_retries:
                    time.sleep(min(30, 2 ** (attempt + 1)))
        raise RuntimeError(f"profile analysis failed: {last_error}")
