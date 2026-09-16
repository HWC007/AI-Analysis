# Next-generation analyzer

The next-generation analyzer loads the authoritative P1–P5 evaluation specification from `analysis_prompt.md`. The prompt file contains only the analysis task, scoring rules, and required response format. Do not edit its P1–P5 wording without explicit approval.

## Setup

Create `analyzer\openai-api.txt` containing only the LiteLLM virtual key, or set `OPENAI_API_KEY`. The same LiteLLM proxy key can be used for profile analysis and research. The selected Gemini provider must also be configured in the LiteLLM gateway.

Run the program as a module from the repository root:

```text
python -m analyzer_nextgen.main `
  --input .\Apify-raw-structured-new.csv `
  --output .\Apify-raw-structured-new.csv `
  --research-provider openai `
  --research-model gpt-5.2 `
  --workers 8 `
  --batch-size 20 `
  --chunk-size 100
```

For Gemini research:

```text
python -m analyzer_nextgen.main `
  --research-provider gemini `
  --research-model gemini-2.5-flash
```

Profile analysis remains independently controlled by `--model`.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `main.py` | Command-line entry point; loads configuration, creates services, selects rows, and starts the coordinator. |
| `config.py` | Defines separate research, analysis, and run configuration objects. |
| `research_manager.py` | Performs company web research, validates reports, handles retries, and manages the reusable research cache. |
| `analysis_manager.py` | Sends profile-analysis requests and calculates `AI_Judgement` and `AI_Weighting` from the validated P1–P5 response. |
| `response_parser.py` | Parses the JSON response and verifies one correctly placed terminal conclusion for each Priority 1–5 section. |
| `retry_coordinator.py` | Coordinates batches, research recovery rounds, recovered-row reanalysis, and faulty-row retries. |
| `csv_store.py` | Loads structured CSV data and saves batch results. |
| `models.py` | Holds shared research-result, status, and temporary-placeholder structures. |
| `run_logger.py` | Appends thread-safe structured request, batch, retry, and lifecycle events to `events.jsonl`. |
| `checkpoint_store.py` | Atomically saves and loads the current resumable workflow state. |
| `analysis_prompt.md` | Authoritative P1–P5 definitions, scoring rules, evidence requirements, and JSON response format. This file must not be reworded without explicit approval. |

## Run folders and resume

Each run creates a folder under `analyzer_nextgen_runs` containing:

```text
<run-id>/
├── events.jsonl
├── checkpoint.json
├── status.json
└── run_config.json
```

Press `Ctrl+C` to request a graceful stop. On Windows, the coordinator polls active analysis futures every 0.5 seconds so cancellation is detected promptly. Running API requests are not forcibly terminated; they finish or reach their configured timeout. After cancellation is detected, no new work is started and the CSV, research cache, checkpoint, and status report are saved. Resume an interrupted run with:

```text
python -m analyzer_nextgen.main --resume .\analyzer_nextgen_runs\<run-id>\checkpoint.json
```

## Command-line options

| Option | Function | Default / notes |
|---|---|---|
| `--input PATH` | Input structured CSV. | `Apify-raw-structured.csv` |
| `--output PATH` | CSV to update. | Same input path by default. |
| `--api-key-file PATH` | File containing the LiteLLM key. | `analyzer\openai-api.txt` |
| `--base-url URL` | LiteLLM/OpenAI-compatible endpoint. | `http://ai.moldex3d.com:4000/v1` |
| `--model NAME` | Model for profile analysis. | `gpt-5.6-luna` |
| `--analysis-prompt PATH` | Five-priority Markdown prompt used for profile analysis. | `analyzer_nextgen\analysis_prompt.md` |
| `--research-provider NAME` | Research provider adapter. | `openai`, `gemini`, or `generic` |
| `--research-model NAME` | Model used for company research. | `gpt-5.2` |
| `--search-context-size SIZE` | Research search context. | `medium` |
| `--no-web-search` | Disable company research. | Uses a temporary placeholder. |
| `--research-cache PATH` | Persistent company research cache. | `company-research-cache.json` |
| `--refresh-research` | Refresh current-run companies while preserving other cache entries. | Off by default. |
| `--workers N` | Shared research and analysis worker count. | `8` |
| `--research-workers N` | Override research worker count. | Uses `--workers`. |
| `--analysis-workers N` | Override analysis worker count. | Uses `--workers`. |
| `--batch-size N` | Rows saved per research/analysis batch. | `20` |
| `--chunk-size N` | Outer processing boundary retained for run compatibility. | `100` |
| `--max-retries N` | Attempts per research or analysis request. | `3` |
| `--max-research-rounds N` | Complete recovery rounds for unavailable companies. | `3` |
| `--max-error-rounds N` | Complete recovery rounds for faulty rows. | `10` |
| `--status-report PATH` | Final status report path. | `<output>.status.json` |
| `--run-dir PATH` | Root folder for per-run logs, checkpoints, status, and configuration. | `analyzer_nextgen_runs` |
| `--resume PATH` | Resume from an existing `checkpoint.json`. | Off by default. |
| `--ids ID,...` | Analyze only selected row IDs. | Supports targeted tests. |
| `--limit N` | Limit selected target rows. | `0` means no limit. |
| `--reanalyze-all` | Reprocess every row. | Off by default. |

The program researches unique companies concurrently, analyzes rows after each research batch, saves the output after each batch, retries unavailable company research after the main pass, reanalyzes recovered rows, and finally retries faulty analysis rows. Generated CSVs, caches, logs, checkpoints, and status files should not be committed to Git.
