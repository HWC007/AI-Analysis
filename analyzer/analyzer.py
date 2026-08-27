#!/usr/bin/env python3
"""Analyze structured profiles through an OpenAI-compatible LiteLLM endpoint."""

import argparse, csv, json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SYSTEM_PROMPT = r'''You are a prospect qualification specialist for injection molding manufacturers and professionals.
Evaluate EVERY prospect against ALL FIVE priorities. Do not stop after finding a match. Translate non-English text internally. Use all supplied tenure fields. Do not invent facts.

PRIORITY 1 — COMPANY: Analyze Current_Company for service providers that design/build molds, produce molded parts, or make molding equipment; product manufacturers/OEMs with plastic-intensive products; or plastics simulation/engineering providers. MUST use web search whenever the profile is not 100% conclusive. Search the company with injection molding, plastic parts, tooling, mold design, products, manufacturing, and engineering. Prefer official and reliable industry sources. Do not guess from the name. State searched evidence and uncertainty.
TARGET DEFINITION: This workflow targets injection-molding manufacturers, mold/tooling builders, plastics engineering providers, and relevant technical stakeholders or decision-makers at those companies. Moldflow, Cadmould, or Moldex3D is NOT required for company or personal qualification. Do not mark a clearly qualifying company or relevant technical person false merely because those named software tools are absent. Include direct mold/tooling, molded-part, hot-runner, mold-cooling, and plastics-engineering businesses. Exclude injection-molding machine manufacturers, peripheral/auxiliary equipment providers, general factory automation unrelated to mold tooling, plastics-material suppliers without molding/tooling services, and companies providing only mold maintenance, repair, or servicing without broader tooling, design, trials, modifications, or molded-part production.
PRIORITY 2 SCOPE CLARIFICATION: Exclude general sales, machine setters/operators limited to machine operation or parameter setting, and technicians without mold tooling, trials, modifications, plastic-part development, or injection-molding engineering. Sales or technical-sales roles count only when they explicitly involve molds, tooling, hot runners, mold cooling, or injection-molding engineering. For a qualified tooling/molding service provider or simulation/engineering company, CEO, General Manager, CTO, technical director, engineering lead, construction/development lead, tooling lead, process engineer, automation lead, or comparable technical leader may qualify when connected to technical, production, tooling, or digitalization work. Pure mold-maintenance or mold-repair work does not qualify by itself.
PRIORITY 2 — CURRENT ROLE: Analyze Current_Position, description, headline, and tenure. Service providers/engineering firms permit high inference for technical/design roles. For a confirmed injection-molding or tooling provider, roles such as Geschäftsführer/Managing Director, technical director, engineering lead, construction/development lead, tooling lead, process engineer, or automation lead qualify when the profile connects them to the company's technical, production, tooling, or digitalization work. For OEMs, require plastic-specific evidence such as plastic-part design, lightweight components, enclosures, tooling, injection molding, mold trials, Moldflow, or Cadmould.
PRIORITY 3 — BACKGROUND: Analyze all three past roles/descriptions/tenures, About, Skills, and top_skills for any injection molding, mold design, plastics processing, tooling, mold trials, or plastic-part experience.
PRIORITY 4 — SOFTWARE: Search case-insensitively for Moldflow, Cadmould, and Solidworks plastic. Check Skills separately from all other sections. p4_in_skills_only is true only if found in Skills and nowhere else. p4_in_other_sections is true if found outside Skills. Priority 4 is informational only.
PRIORITY 5 — MOLDEX: Evaluate this priority ONLY from LinkedIn/profile fields: about, headline, Skills, top_skills, current-position fields, and previous-position fields. Ignore the GPT-5.2 web-research text completely for Priority 5. Moldex3D in LinkedIn content always satisfies Priority 5. If only Moldex appears, satisfy it only when the LinkedIn context refers to molding simulation, CoreTech, CAE, or plastic simulation; do not use web-research mentions or unrelated Moldex products/companies as evidence.

JUDGEMENT: Yes if any of P1, P2, P3, or P5 is true; No only if all four are false. Priority 4 never affects judgement. Before returning No, verify that the explanation does not itself cite qualifying injection molding, molded-plastic production, toolmaking, plastics engineering, or relevant technical leadership. If it does, the corresponding priority must be true. Never use absence of Moldflow/Cadmould/Moldex3D alone to make P1, P2, or P3 false.
Return only valid JSON. Provide concise but evidence-based explanations for every priority, with separate labeled sections. Target approximately 1,000–1,800 characters and do not exceed 2,500 characters. Include the strongest evidence and important missing evidence; do not repeat the entire profile.''' 


def token_value(explicit, path):
    token = explicit or os.getenv("OPENAI_API_KEY", "")
    if not token and Path(path).is_file(): token = Path(path).read_text(encoding="utf-8").strip()
    if not token: raise RuntimeError(f"No API key supplied; set OPENAI_API_KEY or create {path}.")
    return token


def normalize(result):
    aliases = {
        1: ["priority_1_company_analysis", "priority_1_company", "p1_company_analysis", "p1_company"],
        2: ["priority_2_current_position_analysis", "priority_2_current_role", "p2_current_position_analysis", "p2_current_role"],
        3: ["priority_3_previous_position_and_background", "priority_3_background", "p3_previous_position_and_background", "p3_background"],
        4: ["priority_4_competitor_alternative_software", "priority_4_software", "p4_competitor_alternative_software", "p4_software"],
        5: ["priority_5_moldex3d_false_positive_avoidance", "priority_5_moldex", "p5_moldex3d_false_positive_avoidance", "p5_moldex"],
    }

    def section(number):
        for name in aliases[number]:
            if isinstance(result.get(name), dict):
                return result[name]
        # Luna has used several casing/separator variants (for example
        # P1_company_analysis). Accept any object whose key identifies P1-P5.
        prefix = f"p{number}"
        for name, data in result.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(name).lower())
            if normalized.startswith(prefix) and isinstance(data, dict):
                return data
        return {}

    def flag(value):
        if isinstance(value, bool): return value
        if isinstance(value, (int, float)): return value != 0
        return str(value).strip().lower() in {"true", "yes", "y", "1", "match", "likely relevant", "relevant"}

    def section_flag(data):
        for key in ("satisfied", "qualified", "match", "result", "true"):
            if key in data: return flag(data[key])
        return False

    labels = {
        1: "Priority 1 — Company analysis",
        2: "Priority 2 — Current position analysis",
        3: "Priority 3 — Previous experience and background",
        4: "Priority 4 — Competitor/alternative software",
        5: "Priority 5 — Moldex3D/Moldex analysis",
    }
    sections = {n: section(n) for n in range(1, 6)}
    for n in range(1, 6):
        result[f"priority_{n}_satisfied"] = section_flag(sections[n])

    p4 = sections[4]
    result["p4_in_skills_only"] = flag(p4.get("p4_in_skills_only", False))
    result["p4_in_other_sections"] = flag(p4.get("p4_in_other_sections", False))

    paragraphs = []
    for n in range(1, 6):
        data = sections[n]
        evidence = data.get("explanation") or data.get("evidence") or data.get("reasoning") or data.get("details") or "No explanation supplied."
        paragraphs.append(f"{labels[n]}: {'True' if result[f'priority_{n}_satisfied'] else 'False'} — {evidence}")
    if result.get("evidence_limitations"):
        paragraphs.append(f"Evidence limitations: {result['evidence_limitations']}")
    if result.get("final_reasoning") or result.get("overall_explanation"):
        paragraphs.append(f"Overall assessment: {result.get('final_reasoning') or result.get('overall_explanation')}")
    result["explanation"] = "\n\n".join(paragraphs)
    result["judgement"] = "Yes" if any(result[f"priority_{n}_satisfied"] for n in (1, 2, 3, 5)) else "No"
    return result


def search_company(base_url, model, key, company, retries):
    prompt = (f"Research {company}. Find the official website and reliable sources describing its business activities, products, services, industries, and evidence of injection-mold design, injection-molded plastic production, mold-tooling engineering, mold trials, hot-runner systems, mold cooling or conformal cooling, plastics engineering, Moldflow, Cadmould, or Moldex3D. Explicitly distinguish these qualifying activities from injection-molding machine manufacturing, peripheral/auxiliary equipment, general factory automation, plastics-material supply, and pure mold maintenance or repair. Return a concise evidence-based report with source URLs. Distinguish confirmed facts from uncertainty.")
    body = {"model": model, "tools": [{"type": "web_search_preview"}], "input": prompt}
    request = urllib.request.Request(base_url.rstrip("/") + "/responses", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response: data = json.loads(response.read().decode())
            if data.get("output_text"): return data["output_text"]
            texts = [content.get("text", "") for output in data.get("output", []) for content in output.get("content", []) if content.get("type") == "output_text"]
            if texts: return "\n".join(texts)
            raise RuntimeError("GPT-5.2 web search returned no text")
        except Exception as exc:
            if attempt == retries - 1: raise RuntimeError(f"GPT-5.2 web search failed: {exc}")
            time.sleep(min(30, 2 ** (attempt + 1)))


def call(base_url, model, key, profile, research, retries):
    user_content = "GPT-5.2 WEB RESEARCH FOR PRIORITY 1:\n" + research + "\n\nPROSPECT DATA:\n" + json.dumps(profile, ensure_ascii=False)
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}]}
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response: data = json.loads(response.read().decode())
            content = data["choices"][0]["message"]["content"]
            return normalize(json.loads(content))
        except Exception as exc:
            if attempt == retries - 1: raise RuntimeError(f"LiteLLM request failed: {exc}")
            time.sleep(min(30, 2 ** (attempt + 1)))


def analyze_one(row, base_url, model, key, research, retries):
    profile = {k: (re.sub("\\u00b7", "-", str(v)) if k.endswith("Tenure") else str(v)) for k, v in row.items() if k not in {"AI_Judgement", "AI_Weighting", "AI_Explanation", "createdAt", "updatedAt"}}
    result = call(base_url, model, key, profile, research, retries)
    p1, p2, p3, p4, p5 = (bool(result.get(k)) for k in ["priority_1_satisfied", "priority_2_satisfied", "priority_3_satisfied", "priority_4_satisfied", "priority_5_satisfied"])
    p4_score = 0.05 if result.get("p4_in_other_sections") else 0.025 if result.get("p4_in_skills_only") else 0
    return {
        "AI_Judgement": "Yes" if p1 or p2 or p3 or p5 else "No",
        "AI_Weighting": round((2 if p1 else 0) + (2.5 if p2 else 0) + (1 if p3 and (p1 or p2) else 0) + p4_score + (5 if p5 else 0), 3),
        "AI_Explanation": result.get("explanation", ""),
    }


def load_research_cache(path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cache = {}
        for key, value in data.items():
            cache[key] = value.get("report", "") if isinstance(value, dict) else str(value)
        return cache
    except Exception as exc:
        print(f"Warning: could not load research cache {path}: {exc}", file=sys.stderr)
        return {}


def save_research_cache(path, cache, company_names):
    payload = {
        key: {
            "company": company_names.get(key, key),
            "researched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "report": report,
        }
        for key, report in sorted(cache.items())
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def show_progress(label, completed, total, started_at, workers, extra=""):
    if total <= 0:
        return
    elapsed = max(time.monotonic() - started_at, 0.001)
    rate = completed / elapsed
    remaining = max(total - completed, 0)
    eta = remaining / rate if rate else 0
    width = 30
    filled = int(width * completed / total)
    bar = "#" * filled + "." * (width - filled)
    percent = completed * 100 / total
    eta_text = "done" if completed >= total else f"ETA {eta/60:.1f}m"
    message = f"\r{label}: [{bar}] {percent:6.2f}% ({completed}/{total}) | {rate:.2f}/s | {eta_text} | workers={workers}"
    if extra:
        message += f" | {extra}"
    print(message, end="", flush=True)
    if completed >= total:
        print()


def chunks(items, size):
    """Yield fixed-size slices so only one group of analysis futures is active."""
    for start in range(0, len(items), size):
        yield items[start:start + size]


def main():
    parser = argparse.ArgumentParser()
    script_dir = Path(__file__).resolve().parent
    parser.add_argument("--input", default=".\\Apify-raw-structured.csv"); parser.add_argument("--output", default=".\\Apify-raw-structured.csv")
    parser.add_argument("--api-key-file", default=str(script_dir / "openai-api.txt")); parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="http://ai.moldex3d.com:4000/v1"); parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--research-model", default="gpt-5.2", help="Model used with /responses and web_search_preview")
    parser.add_argument("--no-web-search", action="store_true")
    parser.add_argument("--research-cache", default=".\\company-research-cache.json", help="Persistent JSON file for company research")
    parser.add_argument("--refresh-research", action="store_true", help="Ignore existing cached company research")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent web research/analysis workers")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of target profiles to process; 0 means all")
    parser.add_argument("--ids", default="", help="Comma-separated row IDs to reanalyze selectively")
    parser.add_argument("--chunk-size", type=int, default=100, help="Rows submitted to the analysis worker pool at one time")
    parser.add_argument("--batch-size", type=int, default=10); parser.add_argument("--max-retries", type=int, default=3); parser.add_argument("--reanalyze-all", action="store_true")
    args = parser.parse_args()
    if args.chunk_size < 1:
        raise RuntimeError("--chunk-size must be at least 1.")
    with open(args.input, newline="", encoding="utf-8-sig") as f: rows = list(csv.DictReader(f))
    if args.ids and args.reanalyze_all:
        raise RuntimeError("Use either --ids or --reanalyze-all, not both.")
    if args.ids:
        requested_ids = {part.strip() for part in args.ids.split(",") if part.strip()}
        if not requested_ids or not all(item.isdigit() for item in requested_ids):
            raise RuntimeError("--ids must be a comma-separated list of numeric row IDs.")
        targets = [r for r in rows if str(r.get("id", "")).strip() in requested_ids]
        found_ids = {str(r.get("id", "")).strip() for r in targets}
        missing_ids = sorted(requested_ids - found_ids, key=int)
        if missing_ids:
            raise RuntimeError("Requested ID(s) not found: " + ", ".join(missing_ids))
    else:
        targets = [r for r in rows if args.reanalyze_all or not r.get("AI_Judgement", "").strip() or r.get("AI_Judgement") == "Error" or not r.get("AI_Explanation", "").strip()]
    if args.limit > 0:
        targets = targets[:args.limit]
    key = token_value(args.api_key, args.api_key_file); print(f"Profiles to analyze: {len(targets)}")
    cache_path = Path(args.research_cache)
    research_cache = {} if args.refresh_research else load_research_cache(cache_path)
    companies = {str(row.get("Current_Company", "")).strip().casefold(): str(row.get("Current_Company", "")).strip() for row in targets if str(row.get("Current_Company", "")).strip()}
    if args.no_web_search:
        research_cache = {key_name: "Web search disabled by command-line option." for key_name in companies}
    else:
        missing = {key_name: company for key_name, company in companies.items() if key_name not in research_cache}
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(search_company, args.base_url, args.research_model, key, company, args.max_retries): key_name for key_name, company in missing.items()}
            for future in as_completed(futures):
                key_name = futures[future]
                try: research_cache[key_name] = future.result()
                except Exception as exc: research_cache[key_name] = f"Web research failed: {exc}"
                save_research_cache(cache_path, research_cache, companies)
        if not missing:
            save_research_cache(cache_path, research_cache, companies)

    def process(index, row):
        company_key = str(row.get("Current_Company", "")).strip().casefold()
        return index, analyze_one(row, args.base_url, args.model, key, research_cache.get(company_key, "No company research available."), args.max_retries)

    completed = 0
    started_at = time.monotonic()
    show_progress("AI analysis", 0, len(targets), started_at, args.workers)
    for index_chunk in chunks(range(len(targets)), args.chunk_size):
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(process, index, targets[index]): index for index in index_chunk}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    _, result = future.result()
                    targets[index].update(result)
                    targets[index]["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                except Exception as exc:
                    targets[index]["AI_Judgement"], targets[index]["AI_Weighting"], targets[index]["AI_Explanation"] = "Error", 0, str(exc)
                completed += 1
                show_progress("AI analysis", completed, len(targets), started_at, args.workers)
                if completed % args.batch_size == 0 or completed == len(targets):
                    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
                        writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
                    print(f"Processed {completed} / {len(targets)}")
    print(f"Saved analysis to {args.output}")


if __name__ == "__main__":
    try: main()
    except Exception as exc: print(f"Error: {exc}", file=sys.stderr); sys.exit(1)
