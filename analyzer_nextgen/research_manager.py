import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .config import ResearchConfig
from .models import ResearchResult


def company_key(name: str) -> str:
    return str(name or "").strip().casefold()


REFUSAL_PATTERN = re.compile(
    r"(?i)web research failed|unable to access the web|web-browsing tool.*(?:failing|error)|"
    r"can.t complete.*research|found no tool response|cannot assist|can.t assist|"
    r"i(?:'m| am) sorry.{0,100}(?:cannot|can.t|unable)|as an ai"
)


def usable_report(report: str, sources: list[dict] | None = None) -> bool:
    """Accept sourced evidence from text or provider citation metadata."""
    text = str(report or "").strip()
    source_urls = [
        str(source.get("url", ""))
        for source in (sources or [])
        if isinstance(source, dict) and str(source.get("url", "")).startswith("http")
    ]
    if not text or not (re.search(r"https?://\S+", text) or source_urls):
        return False
    return not REFUSAL_PATTERN.search(text)


def _text_content(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (_text_content(item) for item in value) if part)
    if isinstance(value, dict):
        text = value.get("text", "")
        return text if isinstance(text, str) else ""
    return ""


def _collect_sources(value, sources: list[dict]) -> None:
    """Collect URLs from OpenAI annotations and Gemini grounding metadata."""
    if isinstance(value, dict):
        url = value.get("url") or value.get("uri") or value.get("link")
        if isinstance(url, str) and re.match(r"https?://\S+", url):
            title = value.get("title") or value.get("name") or ""
            item = {"url": url, "title": str(title)}
            if item not in sources:
                sources.append(item)
        for child in value.values():
            _collect_sources(child, sources)
    elif isinstance(value, list):
        for child in value:
            _collect_sources(child, sources)


def _validation_failure(report: str, sources: list[dict]) -> str:
    text = str(report or "").strip()
    if not text:
        return "empty_response"
    if REFUSAL_PATTERN.search(text):
        return "refusal"
    if not (re.search(r"https?://\S+", text) or sources):
        return "missing_source"
    return ""


class ResearchValidationError(RuntimeError):
    def __init__(self, failure_class: str):
        super().__init__(f"research response failed validation: {failure_class}")
        self.failure_class = failure_class


class ResearchManager:
    def __init__(self, config: ResearchConfig, api_key: str, logger=None):
        self.config = config
        self.api_key = api_key
        self.logger = logger
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
                    "sources": value.get("sources", []),
                }
            else:
                result[key] = {"company": key, "researched_at": "", "report": str(value), "sources": []}
        return result

    def save_cache(self, company_names: dict[str, str] | None = None) -> None:
        company_names = company_names or {}
        payload = {
            key: {
                "company": entry.get("company") or company_names.get(key, key),
                "researched_at": entry.get("researched_at", ""),
                "report": entry.get("report", ""),
                "sources": entry.get("sources", []),
            }
            for key, entry in sorted(self.cache.items())
            if usable_report(entry.get("report", ""), entry.get("sources", []))
        }
        self.config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.cache_path.with_suffix(self.config.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.config.cache_path)

    def cached_report(self, key: str) -> str | None:
        entry = self.cache.get(key)
        report = entry.get("report", "") if entry else ""
        sources = entry.get("sources", []) if entry else []
        return report if usable_report(report, sources) else None

    def _request(self, company: str, attempt: int = 1) -> tuple[str, list[dict]]:
        prompt = (
            f"Research {company}. Find the official website and reliable sources describing its business "
            "activities, products, services, industries, and evidence of injection-mold design, "
            "injection-molded plastic production, mold-tooling engineering, mold trials, hot-runner "
            "systems, mold cooling or conformal cooling, plastics engineering, Moldflow, Cadmould, "
            "or Moldex3D. Distinguish confirmed facts from uncertainty and return source URLs."
        )
        if attempt == 2:
            prompt += (
                " Use the exact company name as a search term, disambiguate similarly named companies, "
                "and prefer the official company website or a reputable business registry."
            )
        elif attempt >= 3:
            prompt += (
                " Return a concise evidence-based report followed by a Sources section containing at least "
                "one complete https URL. Do not return an apology or a statement about tool limitations."
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

        sources: list[dict] = []
        _collect_sources(data, sources)
        if data.get("output_text"):
            report = data["output_text"]
        elif data.get("choices"):
            message = data["choices"][0].get("message", {})
            report = _text_content(message.get("content", ""))
            _collect_sources(message.get("annotations", []), sources)
        else:
            report = "\n".join(
                content.get("text", "")
                for output in data.get("output", [])
                for content in output.get("content", [])
                if content.get("type") == "output_text"
            )
        if sources and not re.search(r"https?://\S+", report or ""):
            report = (report or "").rstrip() + "\n\nSources:\n" + "\n".join(
                f"- {source.get('title') or 'Source'}: {source['url']}" for source in sources
            )
        return report, sources

    def research_one(self, company: str) -> ResearchResult:
        key = company_key(company)
        last_error = ""
        last_failure_class = ""
        for attempt in range(1, self.config.max_retries + 1):
            started = time.monotonic()
            if self.logger:
                self.logger.log("research_attempt_start", company=company, model=self.config.model, attempt=attempt)
            try:
                report, sources = self._request(company, attempt)
                failure_class = _validation_failure(report, sources)
                if failure_class:
                    raise ResearchValidationError(failure_class)
                if self.logger:
                    self.logger.log(
                        "research_attempt_success", company=company, model=self.config.model,
                        attempt=attempt, source_count=len(sources),
                        elapsed_seconds=round(time.monotonic() - started, 3),
                    )
                return ResearchResult(key, company, report.strip(), True, attempts=attempt, sources=sources)
            except Exception as exc:
                last_error = str(exc)
                if isinstance(exc, ResearchValidationError):
                    last_failure_class = exc.failure_class
                elif isinstance(exc, TimeoutError):
                    last_failure_class = "api_timeout"
                elif isinstance(exc, urllib.error.URLError):
                    last_failure_class = "api_connection"
                else:
                    last_failure_class = "api_error"
                if self.logger:
                    self.logger.log(
                        "research_attempt_failure", company=company, model=self.config.model,
                        attempt=attempt, failure_class=last_failure_class,
                        elapsed_seconds=round(time.monotonic() - started, 3), error=last_error,
                    )
                if attempt < self.config.max_retries:
                    time.sleep(min(30, 2 ** (attempt + 1)))
        return ResearchResult(
            key, company, error=last_error, attempts=self.config.max_retries,
            failure_class=last_failure_class,
        )

    def research_companies(self, companies: dict[str, str], refresh: bool = False) -> dict[str, ResearchResult]:
        pending = {
            key: name for key, name in companies.items()
            if refresh or self.cached_report(key) is None
        }
        if not pending or self.config.no_web_search:
            return {}
        if self.logger:
            self.logger.log(
                "research_batch_start", company_count=len(pending), workers=self.config.workers,
                model=self.config.model,
            )
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
                        "sources": result.sources,
                    }
        self.save_cache(companies)
        if self.logger:
            self.logger.log(
                "research_batch_complete", company_count=len(pending),
                successful=sum(result.usable for result in results.values()),
                failed=sum(not result.usable for result in results.values()),
            )
        return results
