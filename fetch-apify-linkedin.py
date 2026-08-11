#!/usr/bin/env python3
"""Fetch LinkedIn profiles from Apify into the project's structured CSV format."""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ACTOR_ID = "apimaestro~linkedin-profile-full-sections-scraper"
FIELDS = [
    "id", "fullname", "first_name", "last_name", "headline", "LinkedIn_URL",
    "location", "country", "city", "follower_count", "connection_count", "about",
    "Skills", "top_skills", "Current_Company", "Current_Position",
    "Current_Position_Description", "Current_Tenure", "Past_Company_1",
    "Past_Position_1", "Past_Position_1_Description", "Past_Position_1_Tenure",
    "Past_Company_2", "Past_Position_2", "Past_Position_2_Description",
    "Past_Position_2_Tenure", "Past_Company_3", "Past_Position_3",
    "Past_Position_3_Description", "Past_Position_3_Tenure", "AI_Judgement",
    "AI_Weighting", "AI_Explanation", "createdAt", "updatedAt",
]


def value(obj, key, default=""):
    return obj.get(key, default) if isinstance(obj, dict) and obj.get(key) is not None else default


def item(items, index):
    return items[index] if isinstance(items, list) and index < len(items) else {}


def read_token(explicit, token_path):
    token = explicit or os.environ.get("APIFY_TOKEN", "")
    if not token and token_path.is_file():
        token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"No Apify token supplied. Set APIFY_TOKEN or create {token_path}.")
    return token


def request_json(url, method="GET", payload=None, timeout=60):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Apify API HTTP {exc.code}: {detail}") from exc


def wait_for_run(token, run_id, poll_interval, run_timeout):
    query = urllib.parse.urlencode({"token": token})
    status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?{query}"
    dataset_url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items?{query}"
    terminal_success = {"SUCCEEDED"}
    terminal_failure = {"FAILED", "ABORTED", "TIMED-OUT"}
    deadline = time.monotonic() + run_timeout
    print(f"Waiting for Apify run {run_id}...")
    while True:
        status_data = request_json(status_url)
        status = status_data.get("data", status_data).get("status")
        print(f"Apify status: {status}")
        if status in terminal_success:
            break
        if status in terminal_failure:
            raise RuntimeError(f"Apify run {run_id} ended with status {status}: {status_data}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Apify run {run_id} did not finish within {run_timeout} seconds.")
        time.sleep(poll_interval)
    result = request_json(dataset_url, timeout=120)
    return result if isinstance(result, list) else [result]


def fetch(token, payload, poll_interval, run_timeout):
    query = urllib.parse.urlencode({"token": token})
    start_url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs?{query}"
    started = request_json(start_url, method="POST", payload=payload, timeout=60)
    run = started.get("data", started)
    run_id = run.get("id")
    if not run_id:
        raise RuntimeError(f"Apify did not return a run ID: {started}")

    print(f"Started Apify run {run_id}.")
    return wait_for_run(token, run_id, poll_interval, run_timeout)


def fetch_last_run(token, poll_interval, run_timeout):
    """Download the most recent Actor run without starting a new run."""
    query = urllib.parse.urlencode({"token": token})
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs/last?{query}"
    latest = request_json(url)
    run = latest.get("data", latest)
    run_id = run.get("id")
    if not run_id:
        raise RuntimeError(f"Apify did not return a last-run ID: {latest}")
    print(f"Using last Apify run {run_id}.")
    return wait_for_run(token, run_id, poll_interval, run_timeout)


def structured(raw, start_id):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = []
    for offset, profile in enumerate(raw):
        basic = value(profile, "basic_info", {})
        location = value(basic, "location", {})
        experience = value(profile, "experience", [])
        current, past1, past2, past3 = (item(experience, i) for i in range(4))
        skills = value(profile, "skills", [])
        row = {
            "id": start_id + offset,
            "fullname": value(basic, "fullname"), "first_name": value(basic, "first_name"),
            "last_name": value(basic, "last_name"), "headline": value(basic, "headline"),
            "LinkedIn_URL": value(basic, "profile_url"), "location": value(location, "full"),
            "country": value(location, "country"), "city": value(location, "city"),
            "follower_count": value(basic, "follower_count"),
            "connection_count": value(basic, "connection_count"), "about": value(basic, "about"),
            "Skills": ", ".join(str(value(s, "name")) for s in skills if value(s, "name")),
            "top_skills": ", ".join(str(s) for s in value(basic, "top_skills", [])),
            "Current_Company": value(current, "company"), "Current_Position": value(current, "title"),
            "Current_Position_Description": value(current, "description"),
            "Current_Tenure": value(current, "duration"),
            "Past_Company_1": value(past1, "company"), "Past_Position_1": value(past1, "title"),
            "Past_Position_1_Description": value(past1, "description"),
            "Past_Position_1_Tenure": value(past1, "duration"),
            "Past_Company_2": value(past2, "company"), "Past_Position_2": value(past2, "title"),
            "Past_Position_2_Description": value(past2, "description"),
            "Past_Position_2_Tenure": value(past2, "duration"),
            "Past_Company_3": value(past3, "company"), "Past_Position_3": value(past3, "title"),
            "Past_Position_3_Description": value(past3, "description"),
            "Past_Position_3_Tenure": value(past3, "duration"),
            "AI_Judgement": "", "AI_Weighting": "", "AI_Explanation": "",
            "createdAt": now, "updatedAt": now,
        }
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", dest="input_path", default="")
    parser.add_argument("--output", dest="output_path", default=".\\Apify-raw-structured.csv")
    parser.add_argument("--token", default="")
    parser.add_argument("--token-file", default=".\\apify-api.txt")
    parser.add_argument("--starting-id", type=int, default=1)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--poll-interval", type=int, default=10, help="Seconds between Apify status checks")
    parser.add_argument("--run-timeout", type=int, default=1800, help="Maximum seconds to wait for the Actor")
    parser.add_argument("--batch-size", type=int, default=500, help="Maximum URLs submitted per Apify run")
    parser.add_argument("--last-run", action="store_true", help="Fetch the latest completed Actor run without starting a new run")
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 500:
        raise RuntimeError("--batch-size must be between 1 and 500 because Apify accepts at most 500 URLs per run.")
    output_path = Path(args.output_path)
    token = read_token(args.token, Path(args.token_file))

    existing = []
    if not args.replace and output_path.is_file():
        with output_path.open(newline="", encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
    for row in existing:
        for field in FIELDS: row.setdefault(field, "")
    numeric_ids = [int(r["id"]) for r in existing if str(r.get("id", "")).isdigit()]
    next_id = max(numeric_ids, default=args.starting_id - 1) + 1
    seen = {str(r.get("LinkedIn_URL", "")).strip().rstrip("/").lower() for r in existing if r.get("LinkedIn_URL")}
    total_added = 0
    total_skipped = 0

    def merge_and_save(raw):
        nonlocal next_id, total_added, total_skipped
        new_rows = structured(raw, next_id)
        added = []
        for row in new_rows:
            url = str(row["LinkedIn_URL"]).strip().rstrip("/").lower()
            if not url or url in seen:
                total_skipped += 1
                continue
            row["id"] = next_id
            next_id += 1
            added.append(row)
            seen.add(url)
        existing.extend(added)
        total_added += len(added)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing)
        print(f"Saved {len(existing)} total profiles; added {len(added)} in this batch; skipped {total_skipped} cumulative.")

    if args.last_run:
        merge_and_save(fetch_last_run(token, args.poll_interval, args.run_timeout))
    else:
        if not args.input_path: raise RuntimeError("Provide --input or use --last-run.")
        input_path = Path(args.input_path)
        if not input_path.is_file(): raise RuntimeError(f"Input file not found: {input_path}")
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        usernames = payload.get("usernames")
        if not usernames: raise RuntimeError("Input JSON must contain a non-empty usernames array.")
        batches = [usernames[i:i + args.batch_size] for i in range(0, len(usernames), args.batch_size)]
        print(f"Submitting {len(usernames)} URLs in {len(batches)} Apify batch(es) of at most {args.batch_size}.")
        for index, batch in enumerate(batches, start=1):
            batch_payload = dict(payload)
            batch_payload["usernames"] = batch
            print(f"Starting batch {index}/{len(batches)} ({len(batch)} URLs).")
            merge_and_save(fetch(token, batch_payload, args.poll_interval, args.run_timeout))
    print(f"Completed: {len(existing)} total profiles in {output_path}; added {total_added}; skipped {total_skipped}.")


if __name__ == "__main__":
    try: main()
    except Exception as exc: print(f"Error: {exc}", file=sys.stderr); sys.exit(1)
