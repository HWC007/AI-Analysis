# Apify LinkedIn CLI export

This reproduces the n8n mapping from the LinkedIn scraper into the same structure as `Apify.csv`. It includes the three blank AI fields required by the qualification workflow: `AI_Judgement`, `AI_Weighting`, and `AI_Explanation`.

## Run on Windows

You can store the token in a local `apify-api.txt` file containing only the token. The file is ignored by Git:

```text
apify_api_your_token_here
```

Alternatively, set the token for the current PowerShell session:

```powershell
$env:APIFY_TOKEN = 'paste-a-new-apify-token-here'
```

Prepare an input file based on [apify-input.example.json](apify-input.example.json), replacing the example URL with the LinkedIn URLs to scrape.

Run the export. Existing output is preserved by default; new profiles are appended, duplicate LinkedIn URLs are skipped, and new AI fields are left blank for n8n to populate:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\fetch-apify-linkedin.ps1 `
  -InputPath .\apify-input.json `
  -OutputPath .\Apify-raw-structured.csv
```

To intentionally replace the output with only the current scrape, add `-Replace`.

The script uses Apify's synchronous dataset endpoint, so it waits for the Actor to finish. It safely handles profiles with fewer than four experience entries and writes empty values where fields are absent.

Do not commit an Apify token or raw personal data to a public repository. The token previously visible in the n8n export should be revoked and replaced.
