# Apify LinkedIn CLI export

This reproduces the n8n mapping from the LinkedIn scraper into the same structure as `Apify.csv`. It includes the three blank AI fields required by the qualification workflow: `AI_Judgement`, `AI_Weighting`, and `AI_Explanation`.

## Run

You can store the token in a local `apify-api.txt` file containing only the token. The file is ignored by Git:

```text
apify_api_your_token_here
```

Prepare an input file based on [apify-input.example.json](apify-input.example.json), replacing the example URL with the LinkedIn URLs to scrape.

Run the Python fetcher. Existing output is preserved by default; new profiles are appended, duplicate LinkedIn URLs are skipped, and new AI fields are left blank for the analysis step to populate:

```text
python .\fetch-apify-linkedin.py `
  --input .\apify-input.json `
  --output .\Apify-raw-structured.csv
```

To intentionally replace the output with only the current scrape, add `-Replace`.

The Python fetcher starts the Actor asynchronously, polls its status, and downloads the dataset only after the run reaches `SUCCEEDED`. It safely handles profiles with fewer than four experience entries and writes empty values where fields are absent.

### More than 500 URLs

Apify accepts at most 500 LinkedIn URLs per Actor run. The fetcher automatically splits a larger `usernames` list into batches of 500, waits for each run to finish, and merges every completed batch into the same output CSV. You only need one command:

```text
python .\fetch-apify-linkedin.py `
  --input .\apify-input.json `
  --output .\Apify-raw-structured.csv `
  --poll-interval 100 `
  --run-timeout 900
```

Use `--batch-size` to choose a smaller batch size when needed; it cannot exceed 500. Each completed batch is saved immediately, so earlier batches remain in the CSV if a later Apify run fails.

### Fetch the latest existing Apify run

Use `--last-run` when you do not want to start a new Actor run or provide LinkedIn URLs. The fetcher retrieves the latest run, checks its status, waits if necessary, and then appends its dataset:

```text
python .\fetch-apify-linkedin.py `
  --last-run `
  --output .\Apify-raw-structured.csv
```

This mode preserves existing rows and skips duplicate LinkedIn URLs. It does not start a new scrape.

Polling and timeout options:

```text
python .\fetch-apify-linkedin.py `
  --last-run `
  --output .\Apify-raw-structured.csv `
  --poll-interval 10 `
  --run-timeout 1800
```

`--poll-interval` is measured in seconds and defaults to `10`. `--run-timeout` is measured in seconds and defaults to `1800` (30 minutes).

Do not commit an Apify token or raw personal data to a public repository. The token previously visible in the n8n export should be revoked and replaced.

The Python fetcher also supports `--replace`, `--poll-interval`, and `--run-timeout`.
