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
