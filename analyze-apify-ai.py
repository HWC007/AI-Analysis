#!/usr/bin/env python3
"""Analyze structured profiles through an OpenAI-compatible LiteLLM endpoint."""

import argparse, csv, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SYSTEM_PROMPT = r'''You are a prospect qualification specialist for injection molding manufacturers and professionals.
Evaluate EVERY prospect against ALL FIVE priorities. Do not stop after finding a match. Translate non-English text internally. Use all supplied tenure fields. Do not invent facts.

PRIORITY 1 — COMPANY: Analyze Current_Company for service providers that design/build molds, produce molded parts, or make molding equipment; product manufacturers/OEMs with plastic-intensive products; or plastics simulation/engineering providers. MUST use web search whenever the profile is not 100% conclusive. Search the company with injection molding, plastic parts, tooling, mold design, products, manufacturing, and engineering. Prefer official and reliable industry sources. Do not guess from the name. State searched evidence and uncertainty.
PRIORITY 2 — CURRENT ROLE: Analyze Current_Position, description, headline, and tenure. Service providers/engineering firms permit high inference for technical/design roles. For OEMs, require plastic-specific evidence such as plastic-part design, lightweight components, enclosures, tooling, injection molding, mold trials, Moldflow, or Cadmould.
PRIORITY 3 — BACKGROUND: Analyze all three past roles/descriptions/tenures, About, Skills, and top_skills for any injection molding, mold design, plastics processing, tooling, mold trials, or plastic-part experience.
PRIORITY 4 — SOFTWARE: Search case-insensitively for Moldflow, Cadmould, and Solidworks plastic. Check Skills separately from all other sections. p4_in_skills_only is true only if found in Skills and nowhere else. p4_in_other_sections is true if found outside Skills. Priority 4 is informational only.
PRIORITY 5 — MOLDEX: Moldex3D always satisfies Priority 5. If only Moldex appears, satisfy it only for molding simulation/CoreTech/CAE/plastic simulation, not unrelated Moldex products or companies.

JUDGEMENT: Yes if any of P1, P2, P3, or P5 is true; No only if all four are false. Priority 4 never affects judgement.
Return only valid JSON. Provide concise but evidence-based explanations for every priority, with separate labeled sections. Target approximately 1,000–1,800 characters and do not exceed 2,500 characters. Include the strongest evidence and important missing evidence; do not repeat the entire profile.''' 


def token_value(explicit, path):
    token = explicit or os.getenv("OPENAI_API_KEY", "")
    if not token and Path(path).is_file(): token = Path(path).read_text(encoding="utf-8").strip()
    if not token: raise RuntimeError(f"No API key supplied; set OPENAI_API_KEY or create {path}.")
    return token


def nested(obj, key): return obj.get(key) if isinstance(obj, dict) else None


def normalize(result):
    names = ["priority_1_company_analysis", "priority_2_current_position_analysis", "priority_3_previous_position_and_background", "priority_4_competitor_alternative_software", "priority_5_moldex3d_false_positive_avoidance"]
    if not result.get("explanation"):
        parts = []
        for name in names:
            section = result.get(name, {})
            if section.get("explanation"): parts.append(f"{name}: {section.get('true')}. {section['explanation']}")
        for name in ("evidence_limitations", "final_reasoning"):
            if result.get(name): parts.append(f"{name}: {result[name]}")
        result["explanation"] = "\n\n".join(parts) or json.dumps(result, ensure_ascii=False, indent=2)
    mapping = [("priority_1_satisfied", names[0]), ("priority_2_satisfied", names[1]), ("priority_3_satisfied", names[2]), ("priority_4_satisfied", names[3]), ("priority_5_satisfied", names[4])]
    for flat, nested_name in mapping:
        if flat not in result: result[flat] = bool(nested(result.get(nested_name, {}), "true"))
    p4 = result.get(names[3], {})
    result.setdefault("p4_in_skills_only", bool(p4.get("p4_in_skills_only", False)))
    result.setdefault("p4_in_other_sections", bool(p4.get("p4_in_other_sections", False)))
    return result


def call(base_url, model, key, profile, retries):
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Prospect data:\n" + json.dumps(profile, ensure_ascii=False)}]}
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response: data = json.loads(response.read().decode())
            content = data["choices"][0]["message"]["content"]
            return normalize(json.loads(content))
        except Exception as exc:
            if attempt == retries - 1: raise RuntimeError(f"LiteLLM request failed: {exc}")
            time.sleep(min(30, 2 ** (attempt + 1)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=".\\Apify-raw-structured.csv"); parser.add_argument("--output", default=".\\Apify-raw-structured.csv")
    parser.add_argument("--api-key-file", default=".\\openai-api.txt"); parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="http://ai.moldex3d.com:4000/v1"); parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--batch-size", type=int, default=10); parser.add_argument("--max-retries", type=int, default=3); parser.add_argument("--reanalyze-all", action="store_true")
    args = parser.parse_args()
    with open(args.input, newline="", encoding="utf-8-sig") as f: rows = list(csv.DictReader(f))
    targets = [r for r in rows if args.reanalyze_all or not r.get("AI_Judgement", "").strip() or r.get("AI_Judgement") == "Error"]
    key = token_value(args.api_key, args.api_key_file); print(f"Profiles to analyze: {len(targets)}")
    for index, row in enumerate(targets, 1):
        profile = {k: (re.sub("\\u00b7", "-", str(v)) if k.endswith("Tenure") else str(v)) for k, v in row.items() if k not in {"AI_Judgement", "AI_Weighting", "AI_Explanation", "createdAt", "updatedAt"}}
        try:
            result = call(args.base_url, args.model, key, profile, args.max_retries)
            p1, p2, p3, p4, p5 = (bool(result.get(k)) for k in ["priority_1_satisfied", "priority_2_satisfied", "priority_3_satisfied", "priority_4_satisfied", "priority_5_satisfied"])
            p4_score = 0.05 if result.get("p4_in_other_sections") else 0.025 if result.get("p4_in_skills_only") else 0
            row["AI_Judgement"] = "Yes" if p1 or p2 or p3 or p5 else "No"
            row["AI_Weighting"] = round((2 if p1 else 0) + (2.5 if p2 else 0) + (1 if p3 and (p1 or p2) else 0) + p4_score + (5 if p5 else 0), 3)
            row["AI_Explanation"] = result.get("explanation", "")
            row["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception as exc:
            row["AI_Judgement"], row["AI_Weighting"], row["AI_Explanation"] = "Error", 0, str(exc)
        if index % args.batch_size == 0 or index == len(targets):
            with open(args.output, "w", newline="", encoding="utf-8-sig") as f: csv.DictWriter(f, fieldnames=rows[0].keys()).writeheader(); csv.DictWriter(f, fieldnames=rows[0].keys()).writerows(rows)
            print(f"Processed {index} / {len(targets)}")
    print(f"Saved analysis to {args.output}")


if __name__ == "__main__":
    try: main()
    except Exception as exc: print(f"Error: {exc}", file=sys.stderr); sys.exit(1)
