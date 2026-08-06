# GPT-5 prospect analysis

`analyze-apify-ai.ps1` is separate from the Apify fetch script. It reads the structured CSV, analyzes blank AI rows with GPT-5, and updates the same file in place. Existing nonblank AI rows are preserved unless `-ReanalyzeAll` is supplied.

Create `openai-api.txt` containing only an OpenAI API key. The file is ignored by Git.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\analyze-apify-ai.ps1 `
  -InputPath .\Apify-raw-structured.csv `
  -OutputPath .\Apify-raw-structured.csv
```

Priority 4 scoring is exclusive: other sections = `0.05`; Skills only = `0.025`; no competitor keyword = `0`.

To re-run every profile:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\analyze-apify-ai.ps1 -ReanalyzeAll
```

The script saves after each batch so an interrupted run keeps completed work. API keys and generated CSV files must not be committed to a public repository.

## Analysis task description

You are a prospect qualification specialist for injection-molding manufacturers and professionals.

For every prospect, evaluate all five priorities below. Do not stop after finding a positive match. Use the complete profile, including the current role, previous roles, descriptions, tenure, biography, skills, headline, and company. Translate non-English text internally before analyzing it. Do not invent facts; distinguish explicit evidence from reasonable inference.

### Priority 1 — Company analysis

Analyze `Current_Company` and determine whether the company participates in the injection-molding lifecycle.

Consider these categories:

- Service provider: designs or builds injection molds, produces molded parts for other companies, or manufactures molding equipment.
- Product manufacturer/OEM: produces physical products that substantially use plastic components, such as automotive parts, medical devices, consumer electronics, appliances, toys, or industrial equipment.
- Simulation and engineering provider: provides plastic-part engineering or simulation using tools such as Moldflow, Cadmould, or Moldex3D.

Use company-specific evidence where available. Company involvement alone is not enough to prove that the individual personally performs injection-molding work.

Return whether Priority 1 is satisfied and explain the company category, evidence, and any uncertainty.

### Priority 2 — Current-position analysis

Analyze:

- `Current_Position`
- `Current_Position_Description`
- `headline`
- `Current_Tenure`

Determine whether the prospect’s current role involves injection molding, mold design, plastic-part design, tooling, mold trials, injection-process work, Moldflow, or Cadmould.

Inference rules:

- For a service provider or simulation/engineering company, apply high inference: a technical or design role may reasonably be involved in the molding process.
- For an OEM, do not assume involvement from a generic engineering title. Require plastic-specific evidence such as plastic-part design, lightweight components, enclosures, tooling, injection molding, mold trials, Moldflow, or Cadmould.

Explain the exact evidence or explain why the evidence is insufficient.

### Priority 3 — Previous experience and background

Analyze all three previous positions, their descriptions and tenures, plus `about`, `Skills`, and `top_skills`.

Determine whether the prospect has any previous experience with injection molding, injection-mold design, plastic processing, tooling, mold trials, or plastic-part development.

The explanation should identify the relevant company, role, time period, description, biography, or skill. If no evidence exists, explicitly state that the available background was checked and what it contained instead.

### Priority 4 — Competitor or alternative software

Search case-insensitively for:

- `Moldflow`
- `Cadmould`
- `Solidworks plastic`

Check `Skills` separately from every other section. Other sections include `about`, `headline`, `top_skills`, current-position fields, and all previous-position fields.

Set the location flags as follows:

- `p4_in_skills_only = true` only when a keyword appears in `Skills` and does not appear anywhere else.
- `p4_in_other_sections = true` when a keyword appears outside `Skills`, whether or not it also appears in `Skills`.

Priority 4 weighting is exclusive:

- Keyword in another section: `0.05`
- Keyword only in `Skills`: `0.025`
- No keyword: `0`

Do not add `0.05` and `0.025` together. Priority 4 affects weighting only; it does not affect the final judgement.

### Priority 5 — Moldex3D false-positive avoidance

Search every section for `Moldex3D` and `Moldex`.

- `Moldex3D` is injection-molding simulation software and satisfies Priority 5.
- If only `Moldex` appears, inspect the context. It satisfies Priority 5 only when it refers to molding simulation software, CoreTech System, CAE, or plastic simulation.
- An unrelated Moldex company, respirator, hearing-protection product, or other non-molding reference does not satisfy Priority 5.

Explain the context, not just the keyword match.

### Final judgement and weighting

The final `AI_Judgement` is `Yes` when any of Priorities 1, 2, 3, or 5 is satisfied. It is `No` only when all four are false. Priority 4 is excluded from this Yes/No decision.

Use these weighting values:

| Priority | Weight |
|---|---:|
| Priority 1 satisfied | 2.0 |
| Priority 2 satisfied | 2.5 |
| Priority 3 satisfied, and Priority 1 or 2 is satisfied | 1.0 |
| Priority 4 keyword in another section | 0.05 |
| Priority 4 keyword only in Skills | 0.025 |
| Priority 5 satisfied | 5.0 |

Sum the applicable values, using only one Priority 4 value.

### Required response

Return one valid JSON object with these fields:

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

The explanation must be evidence-based and substantially detailed—ideally at least 700 characters. Each priority must explicitly state `True` or `False`, cite the relevant fields, explain the reasoning, and mention important missing evidence. Do not return markdown, commentary, or text outside the JSON object.
