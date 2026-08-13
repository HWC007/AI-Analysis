# Universal company matching

`universal-matching.py` matches prospect companies to Salesforce accounts while
keeping the matching conservative. It supports CSV and XLSX input, country-aware
normalization, exact matching, optional AI adjudication, concurrent AI calls,
and a separate output file.

## Matching chain

Every prospect follows this order:

1. Filter Salesforce accounts to the prospect's country.
2. Normalize company names using legal-form, country, generic-term, accent, and
   punctuation rules from `country_term_profiles.json`.
3. Accept an exact normalized match.
4. If no exact match exists, build a small candidate list using shared
   normalized tokens only.
5. If `--ai-review` is enabled, ask the AI model to adjudicate those candidates.
6. Copy Salesforce fields only for exact or AI-confirmed
   matches.

The script does not use general fuzzy or character-similarity matching. Shared
generic words alone do not establish company identity. Unmatched and ambiguous
rows remain available for review.

## Files

- `universal-matching.py` — complete executable matching workflow.
- `country_term_profiles.json` — global and country-specific legal/generic
  terms. The Polish profile handles forms such as `Sp. z o.o.`, `S.A.`, `Sp. J.`,
  `Polska`, and related variants.
- Input account table — must contain `Billing Country`, `Account Short Name`,
  `Customer Type Auto`, and `Custom` by default.
- Input prospect table — must contain `Country` and `Company Name` by default.
  Use `--company-column Current_Company` for the Apify export.

## Output fields

The prospect columns are preserved and these fields are added or updated:

| Field | Meaning |
|---|---|
| `Matched Name` | Salesforce account selected by exact or AI-confirmed match. |
| `Score` | `1.0` for exact and AI-confirmed matches; `0.0` otherwise. |
| `Type` | `1 - Exact`, `3 - AI Confirmed`, `4 - AI No Match`, `AI Review`, or `None`. |
| `Customer Type Auto` | Copied from Salesforce only for accepted matches. |
| `Target` | Salesforce `Custom` value, copied only for accepted matches. |

If duplicate Salesforce rows agree on customer type and target flag, those two
status fields may still be copied while the account name remains ambiguous.
If the duplicate rows disagree, the status fields stay blank.

## Local installation

```text
pip install pandas openpyxl
```

Run interactively:

```text
python universal-matching.py
```

The prompts request the account comparison table, prospect table, output path,
and term-profile JSON. Inputs are never modified; output is written separately.

Run with CSV files:

```text
python universal-matching.py \
  --target Account_Target_Check.csv \
  --prospects prospects.csv \
  --output prospects-matched.csv \
  --company-column Current_Company \
  --prospect-country country
```

Run with workbook sheets:

```text
python universal-matching.py \
  --target accounts.xlsx --target-sheet Account_Target_Check \
  --prospects prospects.xlsx --prospect-sheet WENE_Prospect \
  --output prospects-matched.xlsx
```

Use `python universal-matching.py --help` to see all column and file options.

## AI-assisted review

AI review is opt-in. It uses the existing OpenAI-compatible LiteLLM endpoint
and key file, and sends only the prospect company, country, and a short list of
candidate account names. It does not send full prospect profiles.

```text
python universal-matching.py \
  --target Account_Target_Check.csv \
  --prospects prospects.csv \
  --output prospects-ai-reviewed.csv \
  --company-column Current_Company \
  --prospect-country country \
  --ai-review \
  --workers 4 \
  --ai-chunk-size 50
```

The model must return only one of `match`, `no_match`, or `ambiguous`, plus a
candidate index. A match is accepted only when the candidate index is valid.
AI rejection, ambiguity, and failed requests do not receive Salesforce status
fields. The response is intentionally minimal to reduce token usage.

### Concurrent processing

AI jobs are submitted in bounded chunks using `ThreadPoolExecutor`, following
the same pattern as `analyzer/analyzer.py`:

- `--workers 4` controls concurrent requests.
- `--ai-chunk-size 50` limits the number of in-flight jobs per batch.
- `--ai-retries 3` retries failed requests with backoff.
- `--ai-limit 20` is useful for a small, inexpensive test; `0` means all
  eligible candidates.
- `--resume` reads the existing output checkpoint and skips rows already
  marked `1 - Exact`, `3 - AI Confirmed`, `4 - AI No Match`, or `AI Review`.

Increase workers cautiously because the API gateway may rate-limit requests.
Start with:

```text
python universal-matching.py --ai-review --ai-limit 20 --workers 4
```

For a long run, use a separate output file and resume it after an interruption:

```text
python universal-matching.py \
  --target Account_Target_Check.csv \
  --prospects prospects.csv \
  --output prospects-ai-reviewed.csv \
  --ai-review --workers 8 --ai-chunk-size 25

# After a stop, failure, or machine restart:
python universal-matching.py \
  --target Account_Target_Check.csv \
  --prospects prospects.csv \
  --output prospects-ai-reviewed.csv \
  --ai-review --resume --workers 8 --ai-chunk-size 25
```

The output file is saved after each AI chunk. No timestamp or decision cache is
required: `Type` is the checkpoint marker. AI no-match results are written as
`4 - AI No Match`, so they are not sent to the model again after resuming.
Rows with no `Type`, or rows left in an error state, remain eligible for retry.

### AI configuration

Defaults:

```text
--base-url http://ai.moldex3d.com:4000/v1
--ai-model gpt-5.6-luna
--api-key-file ..\analyzer\openai-api.txt
```

Override these with `--base-url`, `--ai-model`, `--api-key-file`, or
`--api-key`. Never commit API keys, generated CSV files, or Salesforce data.

## Safety and review rules

- Country mismatch prevents a candidate from being considered.
- Exact normalized matches do not consume AI calls.
- AI is an identity adjudicator, not a broad account search engine.
- Generic overlap such as `akcesoria`, `plastics`, `engineering`, or
  `packaging` is insufficient by itself.
- Ambiguous duplicate Salesforce accounts remain visible for review.
- Keep the output separate from the source files and review AI-confirmed rows
  before acting on them.
