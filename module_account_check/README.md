# module_account_check

Modular true-account status checker for the account and opportunity CSV reports.

## Output contract

The program updates only these two result columns in the account CSV:

- `AI_customer_type`
- `AI_maintenance_status`

Diagnostics, AI responses, failures, checkpoints, and summary counters are stored in the matching JSON output and adjacent checkpoint/event files.

## Modules

| Module | Responsibility |
|---|---|
| `main.py` | CLI and dependency wiring. |
| `model_config.py` | API/model/run configuration. |
| `csv_store.py` | Encoding-aware CSV loading and atomic CSV saving. |
| `deterministic_checker.py` | Product qualification, RTO/MA rules, transitions, and status. |
| `ai_checker.py` | Validated OpenAI-compatible API calls using `ai_rules.md`. |
| `coordinator.py` | Concurrent AI work, guardrails, retries, checkpoints, and output. |
| `checkpoint_store.py` | Atomic resumable state. |
| `run_logger.py` | Thread-safe JSONL lifecycle events. |
| `ai_rules.md` | AI classification contract. |

## Run

From the repository root. If no output path is specified, a new run folder is created automatically:

```text
module_account_check/runs/YYYYMMDD_HHMM/
├── account_target_check.csv
├── account_target_check.json
├── account_target_check.checkpoint.json
└── account_target_check.events.jsonl
```

Run with the default timestamped output:

```powershell
python -m module_account_check.main `
  --account-csv .\module_account_check\salesforce_data\account_target_check.csv `
  --opty-csv .\module_account_check\salesforce_data\opty_check.csv `
  --model gpt-5.6-luna `
  --workers 16 `
  --max-retries 2 `
  --max-error-rounds 2
```

Use `--run-root PATH` to change the run-folder root. Explicit `--output-csv` and `--output-json` paths are supported for controlled test or overwrite runs.

Use `--no-ai` for a deterministic-only run. Use `--as-of-date YYYY-MM-DD` to make date-sensitive results reproducible.

## Saving and recovery

The coordinator saves the CSV during an active AI round according to `--checkpoint-every` or `--checkpoint-seconds`, and writes these files inside the same run folder:

- `account_target_check.checkpoint.json`
- `account_target_check.events.jsonl`
- `account_target_check.json`

CSV writes are atomic. The checkpoint records completed accounts, phase, errors, and round number. API requests use concurrent workers and per-request retries. A later enhancement can resume pending accounts directly from the checkpoint; deterministic results are always available even when AI is unavailable.

## Classification design

The deterministic layer reconstructs history chronologically. It supports transitions between buyout, incomplete RTO, completed RTO, PPU, leasing, and alliance royalty. Current leasing includes both Extreme subscriptions and explicit leasing/rental records. A newer successful alliance royalty may supersede an older direct-software relationship. AI resolves only ambiguous identity/lineage cases and cannot override protected deterministic conclusions such as completed RTO expiry, historical MA expiry, or a lost MA without a later successful event.

The implementation uses the API key in `analyzer\openai-api.txt` by default and the OpenAI-compatible endpoint configured in `model_config.py`/CLI.
