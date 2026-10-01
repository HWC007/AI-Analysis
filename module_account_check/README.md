# module_account_check

True account-status classification for Salesforce account and opportunity CSV reports.

The checker uses deterministic evidence first and sends only ambiguous histories to the AI
arbitrator. It writes the two classification columns required by the account report:

- `AI_customer_type`
- `AI_maintenance_status`

The exact link between the account and opportunity reports is `Account Short Name`.
No Salesforce ID or fuzzy account-name matching is used.

## Customer types

- `Existing buyout software customer`
- `RTO customer`
- `Leasing customer`
- `PPU customer`
- `Service/Training customer`
- `Potential customer`
- `Customer by alliance`

Maintenance status is `Ongoing`, `Expired`, or blank when maintenance status does not apply.
Partner and reseller records are identified from `Customer Type Auto` and retain blank result
fields in the current output contract.

## Checking sequence

The deterministic checker processes each account's complete opportunity history in chronological
order. Event ordering uses Close Date first and Created Date as the fallback/tie-breaker.

1. Match opportunities to the account by exact `Account Short Name`.
2. Apply the `Customer Type Auto` override: `Partner` and `Reseller` are not reclassified by
   opportunity history.
3. Exclude non-qualifying noise, including `iSLM`, `ADD`, `FEA`, and `Other` records. Upgrade
   records are used only when they continue an established buyout lineage. Unrelated cloud
   subscriptions are not treated as leasing.
4. Detect an incomplete RTO sequence. An incomplete RTO is an `RTO customer`; a completed RTO
   continues into the buyout lineage.
5. Identify direct relationships: buyout software, MA, leasing/rental, and PPU.
6. Apply the direct-relationship precedence rule:

   > An active MA/buyout, RTO, leasing, or PPU relationship always supersedes alliance activity,
   > even when the alliance royalty opportunity is newer.

7. Evaluate maintenance for the direct relationship:
   - active MA or valid current relationship → `Ongoing`;
   - completed RTO with no following MA → `Expired`;
   - latest MA lost without a later qualifying purchase → `Expired`;
   - PPU beyond its stated usage period, or one year by default → `Expired`;
   - leasing beyond its stated term, or one year by default → `Expired`;
   - a closed-won lease without a later renewal is not automatically ongoing.
8. Check alliance only when no active direct relationship remains. A latest closed-won OEM
   royalty created within six months is `Customer by alliance / Ongoing`; an older latest royalty
   is `Customer by alliance / Expired`.
9. If there is no software or alliance relationship, classify service/training-only accounts,
   potential customers, and legacy MA-only histories through 2016. Unresolved accounts remain
   blank and may be sent to AI.

## AI arbitration

AI is not used for every account. It is called only for deterministic candidates marked ambiguous,
edge-case, or unclassified. Typical cases include:

- unclear leasing versus cloud-subscription history;
- ambiguous RTO term or payment sequence;
- buyout and upgrade names whose lineage is unclear;
- transitions between PPU, leasing, RTO, buyout/MA, and alliance;
- several competing direct histories that require interpretation of opportunity names.

AI receives the complete chronological opportunity history and must return one allowed customer type
and one allowed maintenance status. It must obey the direct-relationship precedence rule: active
MA/buyout, RTO, leasing, or PPU beats alliance. It must not invent products, stages, dates, or
opportunities, and deterministic expiry protections remain authoritative.

The API pass uses concurrent workers, per-request retries, JSON response validation, and periodic
CSV writes. `gpt-5.6-luna` is the default model.

## Files and run output

| Module | Responsibility |
|---|---|
| `main.py` | CLI and dependency wiring. |
| `model_config.py` | API, model, and run configuration. |
| `csv_store.py` | UTF-8 CSV loading and atomic saving. |
| `deterministic_checker.py` | Product qualification, RTO/MA rules, direct precedence, transitions, and status. |
| `ai_checker.py` | Validated OpenAI-compatible classification calls. |
| `coordinator.py` | Deterministic pass, AI candidates, concurrency, retries, and output. |
| `checkpoint_store.py` | Atomic progress snapshots. |
| `run_logger.py` | Thread-safe JSONL lifecycle events. |
| `ai_rules.md` | Detailed AI classification contract. |

Without an explicit output path, each run creates:

```text
module_account_check/runs/YYYYMMDD_HHMM/
├── account_target_check.csv
├── account_target_check.json
├── account_target_check.checkpoint.json
└── account_target_check.events.jsonl
```

The checkpoint JSON records the current phase, completed accounts, errors, and AI round. It is a
progress and troubleshooting snapshot; it is not loaded to resume a later run. Restarting the
command processes the accounts again. The final JSON contains summary counts, AI results, and
errors. Use `--no-ai` for a deterministic-only run and `--as-of-date YYYY-MM-DD` for reproducible
date-sensitive results.

## Run

From the repository root:

```powershell
python -m module_account_check.main `
  --account-csv .\module_account_check\salesforce_data\account_target_check.csv `
  --opty-csv .\module_account_check\salesforce_data\opty_check.csv `
  --model gpt-5.6-luna `
  --workers 16 `
  --max-retries 2 `
  --max-error-rounds 2
```

The default API endpoint is `http://ai.moldex3d.com:4000/v1`, and the default key file is
`analyzer\openai-api.txt`. Explicit `--output-csv` and `--output-json` paths are supported.
