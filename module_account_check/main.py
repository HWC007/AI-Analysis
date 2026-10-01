from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from pathlib import Path

from .coordinator import Coordinator
from .csv_store import read_csv
from .model_config import ModelConfig, RunConfig


def main():
    root = Path(__file__).parent.parent
    parser = argparse.ArgumentParser(description="Modular true account status checker")
    parser.add_argument("--account-csv", default=str(Path(__file__).with_name("salesforce_data") / "account_target_check.csv"))
    parser.add_argument("--opty-csv", default=str(Path(__file__).with_name("salesforce_data") / "opty_check.csv"))
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--run-root", default=str(Path(__file__).with_name("runs")))
    parser.add_argument("--base-url", default="http://ai.moldex3d.com:4000/v1")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--api-key-file", default=str(root / "analyzer" / "openai-api.txt"))
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-error-rounds", type=int, default=2)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--checkpoint-seconds", type=int, default=60)
    parser.add_argument("--no-ai", action="store_true")
    args = parser.parse_args()
    if args.output_csv:
        output_csv = Path(args.output_csv)
        output_json = Path(args.output_json or output_csv.with_suffix(".json"))
        run_dir = output_csv.parent
    else:
        run_root = Path(args.run_root)
        run_name = datetime.now().strftime("%Y%m%d_%H%M")
        run_dir = run_root / run_name
        suffix = 1
        while run_dir.exists():
            run_dir = run_root / f"{run_name}_{suffix:02d}"
            suffix += 1
        run_dir.mkdir(parents=True, exist_ok=True)
        output_csv = run_dir / "account_target_check.csv"
        output_json = Path(args.output_json) if args.output_json else run_dir / "account_target_check.json"
    key = os.getenv("OPENAI_API_KEY", "") or Path(args.api_key_file).read_text(encoding="utf-8").strip()
    accounts, opportunities = read_csv(Path(args.account_csv)), read_csv(Path(args.opty_csv))
    summary = Coordinator(accounts, opportunities, ModelConfig(args.base_url, args.model, Path(args.api_key_file), 180, args.workers, args.max_retries), RunConfig(Path(args.account_csv), Path(args.opty_csv), output_csv, output_json, args.as_of_date, args.checkpoint_every, args.checkpoint_seconds, args.max_error_rounds, args.no_ai), date.fromisoformat(args.as_of_date), key).run()
    print(f"Run folder: {run_dir}")
    print(f"Wrote {output_csv}")
    print(f"Wrote {output_json}")
    print(summary)


if __name__ == "__main__": main()
