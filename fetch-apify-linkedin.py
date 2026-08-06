#!/usr/bin/env python3
"""Fetch LinkedIn profiles from Apify into the project's structured CSV format."""

import argparse
import csv
import json
import os
import sys
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


def fetch(token, payload):
    query = urllib.parse.urlencode({"token": token})
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items?{query}"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result if isinstance(result, list) else [result]


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
    parser.add_argument("--input", dest="input_path", required=True)
    parser.add_argument("--output", dest="output_path", default=".\\Apify-raw-structured.csv")
    parser.add_argument("--token", default="")
    parser.add_argument("--token-file", default=".\\apify-api.txt")
    parser.add_argument("--starting-id", type=int, default=1)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    input_path, output_path = Path(args.input), Path(args.output)
    if not input_path.is_file(): raise RuntimeError(f"Input file not found: {input_path}")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not payload.get("usernames"): raise RuntimeError("Input JSON must contain a non-empty usernames array.")
    raw = fetch(read_token(args.token, Path(args.token_file)), payload)
    new_rows = structured(raw, args.starting_id)
    existing = []
    if not args.replace and output_path.is_file():
        with output_path.open(newline="", encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
    for row in existing:
        for field in FIELDS: row.setdefault(field, "")
    numeric_ids = [int(r["id"]) for r in existing if str(r.get("id", "")).isdigit()]
    next_id = max(numeric_ids, default=args.starting_id - 1) + 1
    seen = {str(r.get("LinkedIn_URL", "")).strip().rstrip("/").lower() for r in existing if r.get("LinkedIn_URL")}
    added = []
    for row in new_rows:
        url = str(row["LinkedIn_URL"]).strip().rstrip("/").lower()
        if url and url in seen: continue
        row["id"] = next_id; next_id += 1; added.append(row)
        if url: seen.add(url)
    rows = existing + added
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    print(f"Saved {len(rows)} total profiles to {output_path}; added {len(added)}; skipped {len(new_rows)-len(added)} duplicates.")


if __name__ == "__main__":
    try: main()
    except Exception as exc: print(f"Error: {exc}", file=sys.stderr); sys.exit(1)
