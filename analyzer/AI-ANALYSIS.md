# GPT-5 prospect analysis

`analyzer\analyze-apify-ai.py` reads the root-level structured CSV, analyzes rows missing AI results through the configured OpenAI-compatible LiteLLM endpoint, and updates the CSV in place. Existing completed results are preserved unless `--reanalyze-all` is used.

Create `analyzer\openai-api.txt` containing only your LiteLLM virtual key. It is ignored by Git. The script saves after each batch. Do not commit API keys or generated CSV files to a public repository.

```text
python .\analyzer\analyze-apify-ai.py `
  --input .\Apify-raw-structured.csv `
  --output .\Apify-raw-structured.csv
```

The default endpoint is `http://ai.moldex3d.com:4000/v1` and the default analysis model is `gpt-5.6-luna`. The endpoint must expose an OpenAI-compatible `/chat/completions` route.

### Command-line options

| Option | Function | Default / notes |
|---|---|---|
| `--input PATH` | Input structured CSV. | `Apify-raw-structured.csv` |
| `--output PATH` | CSV to update. | Same input path by default. |
| `--api-key-file PATH` | File containing the LiteLLM key. | `analyzer\openai-api.txt` |
| `--base-url URL` | LiteLLM/OpenAI-compatible endpoint. | `http://ai.moldex3d.com:4000/v1` |
| `--model NAME` | Model for profile analysis. | `gpt-5.6-luna` |
| `--research-model NAME` | Model used for Priority 1 web research through `/responses` and `web_search_preview`. | `gpt-5.2` |
| `--no-web-search` | Disable company web research. Priority 1 then uses the supplied profile and a placeholder research note. | Web search enabled by default. |
| `--research-cache PATH` | Persistent JSON file for company research results. | `company-research-cache.json` |
| `--refresh-research` | Ignore cached company reports and research companies again. | Useful after changing `--research-model`. |
| `--workers N` | Number of concurrent research/profile workers. | `4`; use `8` cautiously. |
| `--limit N` | Process at most N target rows. | `0` means all pending rows. |
| `--ids ID,...` | Reanalyze only the specified existing row IDs, including rows that already have AI results. | Example: `--ids 721,907,1401`; cannot be combined with `--reanalyze-all`. |
| `--chunk-size N` | Submit at most N profile rows to the analysis worker pool at one time, then release that group before continuing. | `100` |
| `--batch-size N` | Save the CSV after every N completed rows. | `10` |
| `--max-retries N` | Retry failed API requests. | `3` |
| `--reanalyze-all` | Reprocess every row, including rows with existing AI results. | Off by default; omit it for pending rows only. |

Typical commands:

```text
# Analyze only rows without AI results, using GPT-5.2 web research
python .\analyzer\analyze-apify-ai.py --workers 8

# Reanalyze every row and refresh all cached company research
python .\analyzer\analyze-apify-ai.py --reanalyze-all --refresh-research --workers 8

# Analyze without web search
python .\analyzer\analyze-apify-ai.py --no-web-search --workers 8

# Reanalyze only selected rows
python .\analyzer\analyze-apify-ai.py --ids 721,907,1401 --workers 8

# Use 100-row analysis chunks explicitly
python .\analyzer\analyze-apify-ai.py --chunk-size 100 --workers 8
```

The Python analyzer uses two stages: `gpt-5.2` calls `/responses` with `web_search_preview` to research each unique company, then `gpt-5.6-luna` analyzes the profile using that research. Research is persisted in `company-research-cache.json`, which is ignored by Git, so later runs reuse existing results instead of searching the same company again. Use `--refresh-research` after changing the research model if you want existing cached companies researched again with the new model. Use `--research-model` to change the research model, `--research-cache` to choose another cache file, or `--no-web-search` to disable searching intentionally.

Research and profile analysis run concurrently. The default is 4 workers; lower it if the gateway rate-limits requests, or increase it cautiously:

```text
python .\analyzer\analyze-apify-ai.py --workers 4
```

Company research is performed once per normalized company name, so multiple profiles at the same company reuse the same research. Use `--refresh-research` to ignore and replace the existing cache. Console output is forced to UTF-8 for European names and accents.

### Progress display

While the analyzer is running, it displays one live terminal progress bar for profile-row AI analysis:

```text
AI analysis: [##############................] 46.00% (23/50) | 0.18/s | ETA 2.5m | workers=8
```

Company research runs before profile analysis and is cached silently in `company-research-cache.json`. Only the AI analysis bar is displayed, and it counts profile rows—not research batches—so 1,000 rows produce one bar from `0/1000` to `1000/1000`.

## Analysis task

You are a prospect qualification specialist for injection-molding manufacturers and professionals.

Evaluate every prospect against all five priorities. Do not stop after finding a match. Analyze the complete profile: company, current role, headline, descriptions, tenure, previous roles, biography, `Skills`, and `top_skills`. Translate non-English text internally. Do not invent facts; distinguish explicit evidence from reasonable inference.

### Priority 1 — Company analysis

Analyze `Current_Company` and determine whether it participates in the injection-molding lifecycle:

- **Service provider:** designs/builds injection molds, produces molded parts for other companies, or manufactures molding equipment.
- **Product manufacturer/OEM:** produces physical products that substantially use plastic components, such as automotive parts, medical devices, electronics, appliances, toys, or industrial equipment.
- **Simulation/engineering provider:** provides plastic-part engineering or simulation using Moldflow, Cadmould, Moldex3D, or similar tools.

If the profile is not conclusive, web research is required when the configured model or gateway provides web-search capability. Search the company name with relevant terms such as `injection molding`, `plastic parts`, `tooling`, `mold design`, `products`, `manufacturing`, and `engineering`. Prefer the official website and reliable industry sources. Do not guess from the company name alone. State what was searched, summarize the evidence, and explain any remaining uncertainty.

Company involvement alone does not prove that the individual personally performs injection-molding work.

### Priority 2 — Current-position analysis

Analyze `Current_Position`, `Current_Position_Description`, `headline`, and `Current_Tenure`. Determine whether the current role involves injection molding, mold design, plastic-part design, tooling, mold trials, injection-process work, Moldflow, or Cadmould.

- For a service provider or simulation/engineering company, apply high inference: a technical or design role may reasonably be involved in molding.
- For an OEM, do not infer involvement from a generic engineering title. Require plastic-specific evidence such as plastic-part design, lightweight components, enclosures, tooling, injection molding, mold trials, Moldflow, or Cadmould.

Explain the exact evidence or why it is insufficient.

### Priority 3 — Previous experience and background

Analyze all three previous positions, descriptions, tenures, `about`, `Skills`, and `top_skills`. Determine whether the prospect has any prior experience with injection molding, injection-mold design, plastic processing, tooling, mold trials, or plastic-part development.

Identify the relevant company, role, time period, description, biography, or skill. If there is no evidence, state what the background contained instead.

### Priority 4 — Competitor or alternative software

Search case-insensitively for `Moldflow`, `Cadmould`, and `Solidworks plastic`. Check `Skills` separately from all other sections: `about`, `headline`, `top_skills`, current-position fields, and previous-position fields.

- `p4_in_skills_only = true` only when a keyword appears in `Skills` and nowhere else.
- `p4_in_other_sections = true` when a keyword appears outside `Skills`, even if it also appears in `Skills`.

Priority 4 weighting is exclusive—never add both values:

- Keyword in another section: `0.05`
- Keyword only in `Skills`: `0.025`
- No keyword: `0`

Priority 4 affects weighting only, not the final judgement. Explain the keyword and section where it was found.

### Priority 5 — Moldex3D false-positive avoidance

Search only the LinkedIn/profile fields for `Moldex3D` and `Moldex`: `about`, `headline`, `Skills`, `top_skills`, current-position fields, and previous-position fields. Do not use GPT-5.2 web-research results as evidence for Priority 5. Web-research mentions must be ignored for this priority.

- `Moldex3D` in the LinkedIn/profile content always refers to injection-molding simulation software and satisfies Priority 5.
- If only `Moldex` appears in the LinkedIn/profile content, it satisfies Priority 5 only when the context refers to molding simulation software, CoreTech System, CAE, or plastic simulation.
- An unrelated Moldex company, respirator, hearing-protection product, or other non-molding reference does not satisfy Priority 5.

Explain the context, not just the keyword match.

### Final judgement and weighting

Set `AI_Judgement` to `Yes` if any of Priorities 1, 2, 3, or 5 is satisfied. Set it to `No` only if all four are false. Priority 4 is excluded from this decision.

Apply these values:

| Condition | Weight |
|---|---:|
| Priority 1 satisfied | 2.0 |
| Priority 2 satisfied | 2.5 |
| Priority 3 satisfied **and** Priority 1 or 2 satisfied | 1.0 |
| Priority 4 keyword in another section | 0.05 |
| Priority 4 keyword only in `Skills` | 0.025 |
| Priority 5 satisfied | 5.0 |

Sum applicable values, using only one Priority 4 value.

### Required response

Return only one valid JSON object, with no markdown or additional text:

```json
{
  "judgement": "Yes" or "No",
  "priority_1_satisfied": true or false,
  "priority_2_satisfied": true or false,
  "priority_3_satisfied": true or false,
  "priority_4_satisfied": true or false,
  "priority_5_satisfied": true or false,
  "p4_in_skills_only": true or false,
  "p4_in_other_sections": true or false,
  "explanation": "Detailed explanation with separate labeled sections for Priorities 1–5."
}
```

The explanation must be concise but evidence-based, targeting approximately 1,000–1,800 characters and never exceeding 2,500 characters. For each priority, explicitly state `True` or `False`, cite the strongest relevant fields or web research, explain the reasoning, and mention important missing evidence without repeating the entire profile.
