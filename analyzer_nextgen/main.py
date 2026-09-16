import argparse
import os
from pathlib import Path

from .analysis_manager import AnalysisManager
from .config import AnalysisConfig, ResearchConfig, RunConfig
from .csv_store import CsvStore
from .research_manager import ResearchManager
from .retry_coordinator import RetryCoordinator


def read_key(explicit: str, path: Path) -> str:
    key = explicit or os.getenv("OPENAI_API_KEY", "")
    if not key and path.is_file():
        key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError(f"No LiteLLM API key supplied; set OPENAI_API_KEY or create {path}.")
    return key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Next-generation modular prospect analyzer")
    parser.add_argument("--input", default=".\\Apify-raw-structured.csv")
    parser.add_argument("--output", default=".\\Apify-raw-structured.csv")
    parser.add_argument("--api-key-file", default=str(Path(__file__).parent.parent / "analyzer" / "openai-api.txt"))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="http://ai.moldex3d.com:4000/v1")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--research-provider", choices=("openai", "gemini", "generic"), default="openai")
    parser.add_argument("--research-model", default="gpt-5.2")
    parser.add_argument("--search-context-size", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--no-web-search", action="store_true")
    parser.add_argument("--research-cache", default=".\\company-research-cache.json")
    parser.add_argument("--refresh-research", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--research-workers", type=int, default=0)
    parser.add_argument("--analysis-workers", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-research-rounds", type=int, default=3)
    parser.add_argument("--max-error-rounds", type=int, default=10)
    parser.add_argument("--status-report", default="")
    parser.add_argument("--ids", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--reanalyze-all", action="store_true")
    return parser.parse_args()


def select_targets(rows: list[dict], args: argparse.Namespace) -> list[dict]:
    if args.ids and args.reanalyze_all:
        raise RuntimeError("Use either --ids or --reanalyze-all, not both.")
    if args.ids:
        requested = {part.strip() for part in args.ids.split(",") if part.strip()}
        if not requested or not all(value.isdigit() for value in requested):
            raise RuntimeError("--ids must be a comma-separated list of numeric row IDs.")
        found = {str(row.get("id", "")).strip(): row for row in rows}
        missing = sorted(requested - found.keys(), key=int)
        if missing:
            raise RuntimeError("Requested ID(s) not found: " + ", ".join(missing))
        targets = [found[value] for value in requested]
    else:
        targets = [
            row for row in rows
            if args.reanalyze_all
            or not row.get("AI_Judgement", "").strip()
            or row.get("AI_Judgement") == "Error"
            or not row.get("AI_Explanation", "").strip()
        ]
    return targets[:args.limit] if args.limit > 0 else targets


def main() -> None:
    args = parse_args()
    for name in ("workers", "batch_size", "chunk_size", "max_retries", "max_research_rounds", "max_error_rounds"):
        if getattr(args, name) < 1:
            raise RuntimeError(f"--{name.replace('_', '-')} must be at least 1.")
    shared_workers = args.workers
    research_workers = args.research_workers or shared_workers
    analysis_workers = args.analysis_workers or shared_workers
    key_path = Path(args.api_key_file)
    api_key = read_key(args.api_key, key_path)

    store = CsvStore(Path(args.input), Path(args.output))
    rows = store.load()
    targets = select_targets(rows, args)
    print(f"Next-gen analyzer: {len(targets)} target row(s)")

    research_config = ResearchConfig(
        base_url=args.base_url,
        provider=args.research_provider,
        model=args.research_model,
        search_context_size=args.search_context_size,
        workers=research_workers,
        max_retries=args.max_retries,
        max_rounds=args.max_research_rounds,
        cache_path=Path(args.research_cache),
        no_web_search=args.no_web_search,
        refresh=args.refresh_research,
    )
    analysis_config = AnalysisConfig(
        base_url=args.base_url,
        model=args.model,
        workers=analysis_workers,
        max_retries=args.max_retries,
    )
    run_config = RunConfig(
        input_path=Path(args.input),
        output_path=Path(args.output),
        api_key_file=key_path,
        api_key=args.api_key,
        batch_size=args.batch_size,
        chunk_size=args.chunk_size,
        max_error_rounds=args.max_error_rounds,
        status_report_path=Path(args.status_report) if args.status_report else None,
        reanalyze_all=args.reanalyze_all,
        limit=args.limit,
    )
    coordinator = RetryCoordinator(
        run_config,
        ResearchManager(research_config, api_key),
        AnalysisManager(analysis_config, api_key),
        store,
    )
    coordinator.run(targets)
    status_path = run_config.status_report_path or Path(args.output).with_suffix(".status.json")
    coordinator.save_status(status_path, targets)
    print(f"Saved analysis to {args.output}")
    print(f"Saved status report to {status_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
