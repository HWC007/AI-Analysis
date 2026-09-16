import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .config import ResearchConfig
from .models import ResearchResult


def company_key(name: str) -> str:
    return str(name or "").strip().casefold()


def usable_report(report: str) -> bool:
    """Accept weak but sourced evidence; reject empty, refusal, and failed reports."""
    text = str(report or "").strip()
    if not text or not re.search(r"https?://\S+", text):
        return False
    return not re.search(
        r"(?i)web research failed|unable to access the web|web-browsing tool.*(?:failing|error)|"
        r"can.t complete.*research|found no tool response|cannot assist|can.t assist|"
        r"i(?:'|’)m sorry.{0,100}(?:cannot|can.t|unable)|as an ai",
        text,
    )


class ResearchManager:
    def __init__(self, config: ResearchConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        self.cache: dict[str, dict] = self._load_cache(config.cache_path)

    @staticmethod
    def _load_cache(path: Path) -> dict[str, dict]:
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        result = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[key] = {
                    "company": value.get("company", key),
                    "researched_at": value.get("researched_at", ""),
                    "report": value.get("report", ""),
                }
            else:
                result[key] = {"company": key, "researched_at": "", "report": str(value)}
        return result

    def save_cache(self, company_names: dict[str, str] | None = None) -> None:
        company_names = company_names or {}
        payload = {
            key: {
                "company": entry.get("company") or company_names.get(key, key),
                "researched_at": entry.get("researched_at", ""),
                "report": entry.get("report", ""),
            }
            for key, entry in sorted(self.cache.items())
            if usable_report(entry.get("report", ""))
        }
        self.config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.cache_path.with_suffix(self.config.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.config.cache_path)

    def cached_report(self, key: str) -> str | None:
        entry = self.cache.get(key)
        report = entry.get("report", "") if entry else ""
        return report if usable_report(report) else None

    def _request(self, company: str) -> str:
        prompt = (
            f"Research {company}. Find the official website and reliable sources describing its business "
            "activities, products, services, industries, and evidence of injection-mold design, "
            "injection-molded plastic production, mold-tooling engineering, mold trials, hot-runner "
            "systems, mold cooling or conformal cooling, plastics engineering, Moldflow, Cadmould, "
            "or Moldex3D. Distinguish confirmed facts from uncertainty and return source URLs."
        )
        provider = self.config.provider.casefold()
        if provider in {"openai", "responses"}:
            body = {
                "model": self.config.model,
                "tools": [{"type": "web_search_preview"}],
                "input": prompt,
            }
            endpoint = "/responses"
        else:
            # Gemini grounding and other LiteLLM providers use the compatible
            # chat endpoint. Provider-specific routing is handled by LiteLLM.
            body = {
                "model": self.config.model,
                "messages": [{"role": "user", "content": prompt}],
                "web_search_options": {"search_context_size": self.config.search_context_size},
            }
            endpoint = "/chat/completions"
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + endpoint,
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode())
        if data.get("output_text"):
            return data["output_text"]
        if data.get("choices"):
            return data["choices"][0]["message"].get("content", "")
        texts = [
            content.get("text", "")
            for output in data.get("output", [])
            for content in output.get("content", [])
            if content.get("type") == "output_text"
        ]
        return "\n".join(texts)

    def research_one(self, company: str) -> ResearchResult:
        key = company_key(company)
        last_error = ""
        for attempt in range(1, self.config.max_retries + 1):
            try:
                report = self._request(company)
                if not usable_report(report):
                    raise RuntimeError("response was empty, a refusal/failure message, or had no source URL")
                return ResearchResult(key, company, report.strip(), True, attempts=attempt)
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.config.max_retries:
                    time.sleep(min(30, 2 ** (attempt + 1)))
        return ResearchResult(key, company, error=last_error, attempts=self.config.max_retries)

    def research_companies(self, companies: dict[str, str], refresh: bool = False) -> dict[str, ResearchResult]:
        pending = {
            key: name for key, name in companies.items()
            if refresh or self.cached_report(key) is None
        }
        if not pending or self.config.no_web_search:
            return {}
        results = {}
        with ThreadPoolExecutor(max_workers=max(1, self.config.workers)) as pool:
            futures = {pool.submit(self.research_one, name): key for key, name in pending.items()}
            for future in as_completed(futures):
                result = future.result()
                results[result.company_key] = result
                if result.usable:
                    self.cache[result.company_key] = {
                        "company": result.company,
                        "researched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "report": result.report,
                    }
        self.save_cache(companies)
        return results
