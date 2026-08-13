import json
import re
import unicodedata
import argparse
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

# =========================
# 1. CONFIGURATION
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_JSON = str(SCRIPT_DIR / 'country_term_profiles.json')
DEFAULT_API_KEY_FILE = str(SCRIPT_DIR.parent / 'analyzer' / 'openai-api.txt')
DEFAULT_BASE_URL = 'http://ai.moldex3d.com:4000/v1'
DEFAULT_AI_MODEL = 'gpt-5.6-luna'

COL_ACCOUNT = "Account Short Name"
COL_BILLING_COUNTRY = "Billing Country"
COL_COMPANY = "Company Name"
COL_COUNTRY = "Country"
COL_CUSTOMER_TYPE = "Customer Type Auto"
COL_TARGET = "Custom"


# =========================
# 2. COUNTRY-AWARE TERMS
# =========================
def remove_accents(text):
    """Convert accented Unicode text to comparable ASCII text."""
    text = unicodedata.normalize('NFKD', str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Some European letters, especially Polish ł, do not decompose under
    # Unicode normalization and would otherwise disappear entirely.
    return text.translate(str.maketrans({
        'ł': 'l', 'Ł': 'L', 'đ': 'd', 'Đ': 'D',
        'ð': 'd', 'Ð': 'D', 'þ': 'th', 'Þ': 'Th',
        'ı': 'i', 'ĸ': 'k', 'ŧ': 't', 'Ŧ': 'T',
    }))


def _term_tokens(terms):
    """Return normalized full terms and their individual tokens."""
    result = set()
    for term in terms:
        cleaned = remove_accents(term).lower().replace('&', ' and ')
        cleaned = re.sub(r'[^a-z0-9]+', ' ', cleaned).strip()
        if cleaned:
            result.add(cleaned)
            result.update(cleaned.split())
    return result


def load_term_profiles(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return {
        name: {
            'legal': _term_tokens(profile.get('legal_words', [])),
            'generic': _term_tokens(profile.get('generic_terms', [])),
        }
        for name, profile in data.items()
    }


# Salesforce uses country names. Profiles use short keys where practical.
COUNTRY_PROFILE = {
    'poland': 'pl',
    'polska': 'pl',
    'germany': 'de',
    'deutschland': 'de',
    'italy': 'it',
    'spain': 'es',
    'france': 'fr',
    'turkey': 'tr',
    'czech republic': 'cz',
    'czechia': 'cz',
}


def profile_for_country(country):
    key = str(country or '').strip().lower()
    profile_name = COUNTRY_PROFILE.get(key)
    return TERM_PROFILES.get(profile_name, {'legal': set(), 'generic': set()})


def _strip_legal_suffix(tokens, legal_terms):
    """Strip legal-form tokens only when they occur at the end of a name.

    This handles ``Sp. z o.o.`` after punctuation has become spaces, while
    avoiding removal of meaningful words in the middle of a company name.
    """
    legal_words = {term for term in legal_terms if ' ' not in term}
    while tokens and tokens[-1] in legal_words:
        tokens.pop()
    return tokens


def normalize_name(name, country=None):
    if not isinstance(name, str):
        return ''

    name = remove_accents(name).replace('\u00a0', ' ').lower()
    name = re.sub(r'[_./\\-]', ' ', name)
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    tokens = name.split()

    global_profile = TERM_PROFILES.get('global', {'legal': set(), 'generic': set()})
    local_profile = profile_for_country(country)
    legal = global_profile['legal'] | local_profile['legal']
    generic = global_profile['generic'] | local_profile['generic']

    clean_tokens = _strip_legal_suffix(tokens, legal)
    informative = [token for token in clean_tokens if token not in generic]
    return ' '.join(informative or clean_tokens)


# =========================
# 3. MATCHING ENGINE
# =========================
def get_match(
    q_norm,
    q_country,
    target_df,
    billing_country_col=COL_BILLING_COUNTRY,
    account_col=COL_ACCOUNT,
):
    country = str(q_country or '').strip().lower()
    subset = target_df[
        target_df[billing_country_col].fillna('').astype(str).str.strip().str.lower() == country
    ]
    if subset.empty:
        return 'no similar account', 0.0, 'None'

    exact = subset[subset['__target_norm'] == q_norm]
    if not exact.empty:
        names = exact[account_col].dropna().astype(str).unique().tolist()
        if len(names) == 1:
            return names[0], 1.0, '1 - Exact'
        return 'ambiguous account', 0.0, 'Ambiguous'

    # Do not use fuzzy or semantic matching for automatic account assignment.
    # A similar-looking company name is not evidence that two Salesforce
    # records represent the same account.
    return 'no similar account', 0.0, 'None'


def candidate_matches(q_norm, q_country, target_df, billing_country_col, account_col, limit=5):
    """Return token-blocked candidates for AI review, never an automatic match."""
    country = str(q_country or '').strip().lower()
    subset = target_df[
        target_df[billing_country_col].fillna('').astype(str).str.strip().str.lower() == country
    ]
    query_tokens = set(q_norm.split())
    scored = []
    for _, row in subset.iterrows():
        account_norm = str(row['__target_norm'])
        account_tokens = set(account_norm.split())
        shared = query_tokens & account_tokens
        distinctive_shared = {token for token in shared if len(token) >= 3}
        if distinctive_shared:
            # Rank only by shared normalized tokens. There is deliberately no
            # fuzzy or character-similarity score in the candidate stage.
            score = (len(distinctive_shared), max(map(len, distinctive_shared)))
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    candidates = []
    seen = set()
    for score, row in scored:
        name = str(row[account_col])
        if name in seen:
            continue
        seen.add(name)
        candidates.append({
            'account_name': name,
        })
        if len(candidates) >= limit:
            break
    return candidates


def load_api_key(path, explicit=''):
    key = explicit or os.getenv('OPENAI_API_KEY', '')
    if not key and path and Path(path).is_file():
        key = Path(path).read_text(encoding='utf-8').strip()
    if not key:
        raise RuntimeError(f'No API key found. Use --api-key, OPENAI_API_KEY, or {path}.')
    return key


def ai_review(company, country, candidates, base_url, model, api_key, retries=3, timeout=180):
    system = (
        'You adjudicate company identity for Salesforce account matching. '
        'Return only valid JSON: {"decision":"match|no_match|ambiguous", '
        '"candidate_index":number|null}. '
        'Match only when the distinctive company identity is the same. '
        'Reject shared generic words such as plastics, engineering, packaging, '
        'accessories, systems, or technical. Country and legal suffix differences '
        'are acceptable. If evidence is insufficient, use ambiguous or no_match.'
    )
    user = json.dumps({
        'prospect_company': company,
        'country': country,
        'candidates': [{'index': i, 'account_name': candidate['account_name']}
                       for i, candidate in enumerate(candidates)],
    }, ensure_ascii=False)
    body = {
        'model': model,
        'temperature': 0,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }
    for attempt in range(max(1, retries)):
        request = urllib.request.Request(
            base_url.rstrip('/') + '/chat/completions',
            data=json.dumps(body).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
            content = payload['choices'][0]['message']['content'].strip()
            content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content, flags=re.IGNORECASE).strip()
            result = json.loads(content)
            decision = str(result.get('decision', '')).lower()
            index = result.get('candidate_index')
            if decision not in {'match', 'no_match', 'ambiguous'}:
                raise ValueError('AI returned an invalid decision')
            if index is not None:
                index = int(index)
            return decision, index
        except Exception:
            if attempt == max(1, retries) - 1:
                raise
            time.sleep(min(30, 2 ** (attempt + 1)))


# =========================
# 4. LOCAL FILE EXECUTION
# =========================
def read_table(path, sheet_name=None):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    if path.suffix.lower() in {'.xlsx', '.xls'}:
        return pd.read_excel(path, sheet_name=sheet_name, dtype=str).fillna('')
    raise ValueError(f'Unsupported input format: {path.suffix}. Use CSV or XLSX.')


def write_table(df, path):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        df.to_csv(path, index=False, encoding='utf-8-sig')
    elif path.suffix.lower() in {'.xlsx', '.xls'}:
        df.to_excel(path, index=False)
    else:
        raise ValueError(f'Unsupported output format: {path.suffix}. Use CSV or XLSX.')


def parse_args():
    parser = argparse.ArgumentParser(
        description='Match prospect companies to Salesforce accounts by country.'
    )
    parser.add_argument('--target', default=None,
                        help='Salesforce account CSV/XLSX file. If omitted, prompt.')
    parser.add_argument('--prospects', default=None,
                        help='Prospect CSV/XLSX file. If omitted, prompt.')
    parser.add_argument('--output', default=None,
                        help='New CSV/XLSX file to create. If omitted, prompt.')
    parser.add_argument('--terms', default=None,
                        help='Country term profile JSON file. If omitted, prompt.')
    parser.add_argument('--target-sheet', default='Account_Target_Check',
                        help='Account sheet name when --target is XLSX.')
    parser.add_argument('--prospect-sheet', default='WENE_Prospect',
                        help='Prospect sheet name when --prospects is XLSX.')
    parser.add_argument('--target-country', default=COL_BILLING_COUNTRY,
                        help='Account country column.')
    parser.add_argument('--prospect-country', default=COL_COUNTRY,
                        help='Prospect country column.')
    parser.add_argument('--account-column', default=COL_ACCOUNT,
                        help='Salesforce account-name column.')
    parser.add_argument('--company-column', default=COL_COMPANY,
                        help='Prospect company-name column.')
    parser.add_argument('--customer-type-column', default=COL_CUSTOMER_TYPE,
                        help='Salesforce customer-type column.')
    parser.add_argument('--target-column', default=COL_TARGET,
                        help='Salesforce target-flag column, usually Custom.')
    parser.add_argument('--ai-review', action='store_true',
                        help='Use the configured AI model to adjudicate non-exact candidates.')
    parser.add_argument('--api-key-file', default=DEFAULT_API_KEY_FILE,
                        help='File containing the AI API key.')
    parser.add_argument('--api-key', default='', help='AI API key; otherwise use the key file.')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL,
                        help='OpenAI-compatible API base URL.')
    parser.add_argument('--ai-model', default=DEFAULT_AI_MODEL,
                        help='AI adjudication model.')
    parser.add_argument('--ai-candidates', type=int, default=5,
                        help='Maximum candidates sent to AI per prospect.')
    parser.add_argument('--ai-limit', type=int, default=0,
                        help='Maximum AI calls; 0 means all eligible rows.')
    parser.add_argument('--workers', type=int, default=4,
                        help='Concurrent AI workers.')
    parser.add_argument('--ai-chunk-size', type=int, default=50,
                        help='Maximum AI jobs submitted at once.')
    parser.add_argument('--ai-retries', type=int, default=3,
                        help='Retries per AI request.')
    parser.add_argument('--resume', action='store_true',
                        help='Resume from an existing output checkpoint.')
    return parser.parse_args()


def prompt_path(label, default=None):
    suffix = f' [{default}]' if default else ''
    value = input(f'{label}{suffix}: ').strip().strip('"')
    return value or default


def main():
    args = parse_args()
    interactive = not args.target or not args.prospects or not args.output
    if not args.target:
        args.target = prompt_path('Comparison/account table path')
    if not args.prospects:
        args.prospects = prompt_path('Prospect table path')
    if not args.output:
        args.output = prompt_path('Output path', 'matched-output.csv')
    if not args.terms:
        args.terms = prompt_path('Term profile JSON path', DEFAULT_JSON) if interactive else DEFAULT_JSON
    if not args.target or not args.prospects or not args.output:
        raise ValueError('Target, prospect, and output paths are required.')
    if args.workers < 1 or args.ai_chunk_size < 1 or args.ai_retries < 1:
        raise ValueError('--workers, --ai-chunk-size, and --ai-retries must be at least 1.')

    global TERM_PROFILES
    TERM_PROFILES = load_term_profiles(args.terms)

    api_key = None
    if args.ai_review:
        api_key = load_api_key(args.api_key_file, args.api_key)

    target = read_table(args.target, args.target_sheet)
    output_exists = Path(args.output).is_file()
    if args.resume and output_exists:
        prospects = read_table(args.output, args.prospect_sheet)
        print(f'Resuming from checkpoint: {args.output}')
    else:
        prospects = read_table(args.prospects, args.prospect_sheet)

    required_target = {args.account_column, args.target_country}
    required_target.update({args.customer_type_column, args.target_column})
    required_prospect = {args.company_column, args.prospect_country}
    missing_target = required_target - set(target.columns)
    missing_prospect = required_prospect - set(prospects.columns)
    if missing_target or missing_prospect:
        raise KeyError(
            f'Missing target columns: {sorted(missing_target)}; '
            f'missing prospect columns: {sorted(missing_prospect)}'
        )

    target['__target_norm'] = target.apply(
        lambda row: normalize_name(row[args.account_column], row[args.target_country]), axis=1
    )
    prospects['__query_norm'] = prospects.apply(
        lambda row: normalize_name(row[args.company_column], row[args.prospect_country]), axis=1
    )

    if args.resume and {'Matched Name', 'Score', 'Type'}.issubset(prospects.columns):
        results = [
            (str(row['Matched Name']), float(row['Score'] or 0), str(row['Type']))
            for _, row in prospects.iterrows()
        ]
    else:
        results = [
            get_match(
                row['__query_norm'], row[args.prospect_country], target,
                args.target_country, args.account_column
            )
            for _, row in prospects.iterrows()
        ]
    prospects['Matched Name'], prospects['Score'], prospects['Type'] = zip(*results)

    ai_calls = 0
    if args.ai_review:
        jobs = []
        for position, (_, row) in enumerate(prospects.iterrows()):
            if args.ai_limit and len(jobs) >= args.ai_limit:
                break
            if results[position][2] in {'1 - Exact', '3 - AI Confirmed', '4 - AI No Match', 'AI Review'}:
                continue
            candidates = candidate_matches(
                row['__query_norm'], row[args.prospect_country], target,
                args.target_country, args.account_column, args.ai_candidates
            )
            if not candidates:
                continue
            jobs.append((position, row[args.company_column], row[args.prospect_country], candidates))

        def run_ai_job(job):
            position, company, country, candidates = job
            return position, candidates, ai_review(
                company, country, candidates, args.base_url, args.ai_model,
                api_key, args.ai_retries
            )

        for start in range(0, len(jobs), args.ai_chunk_size):
            chunk = jobs[start:start + args.ai_chunk_size]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(run_ai_job, job): job[0] for job in chunk}
                for future in as_completed(futures):
                    position = futures[future]
                    try:
                        _, candidates, decision_result = future.result()
                        decision, candidate_index = decision_result
                        if decision == 'match' and candidate_index is not None and 0 <= candidate_index < len(candidates):
                            chosen = candidates[candidate_index]
                            results[position] = (chosen['account_name'], 1.0, '3 - AI Confirmed')
                        elif decision == 'ambiguous':
                            results[position] = ('ambiguous account', 0.0, 'AI Review')
                        elif decision == 'no_match':
                            results[position] = ('no similar account', 0.0, '4 - AI No Match')
                    except Exception:
                        pass
                    ai_calls += 1

        prospects['Matched Name'], prospects['Score'], prospects['Type'] = zip(*results)
        checkpoint = prospects.drop(columns=['__query_norm'], errors='ignore').copy()
        write_table(checkpoint, args.output)
        print(f'Checkpoint saved after {min(start + len(chunk), len(jobs))} AI jobs: {args.output}')

    # Carry Salesforce status fields only for accepted matches. If multiple
    # Salesforce rows share a matched name but disagree on status, leave the
    # fields blank rather than choosing an arbitrary account row.
    account_metadata = {}
    normalized_metadata = {}
    for _, account in target.iterrows():
        key = (
            str(account[args.target_country]).strip().lower(),
            str(account[args.account_column]),
        )
        values = (
            str(account[args.customer_type_column]),
            str(account[args.target_column]),
        )
        account_metadata.setdefault(key, set()).add(values)
        normalized_key = (
            str(account[args.target_country]).strip().lower(),
            str(account['__target_norm']),
        )
        normalized_metadata.setdefault(normalized_key, set()).add(values)

    customer_types = []
    target_flags = []
    for (_, prospect), result in zip(prospects.iterrows(), results):
        matched_name, _, match_type = result
        key = (
            str(prospect[args.prospect_country]).strip().lower(),
            str(matched_name),
        )
        if match_type in {'1 - Exact', '3 - AI Confirmed'}:
            values = account_metadata.get(key, set())
        elif match_type == 'Ambiguous':
            values = normalized_metadata.get(
                (str(prospect[args.prospect_country]).strip().lower(), str(prospect['__query_norm'])),
                set(),
            )
        else:
            values = set()
        if len(values) == 1:
            customer_type, target_flag = next(iter(values))
        else:
            customer_type, target_flag = '', ''
        customer_types.append(customer_type)
        target_flags.append(target_flag)
    prospects[COL_CUSTOMER_TYPE] = customer_types
    prospects['Target'] = target_flags
    prospects.drop(columns=['__query_norm'], errors='ignore', inplace=True)
    write_table(prospects, args.output)

    counts = pd.Series([result[2] for result in results]).value_counts().to_dict()
    print(f'Wrote {len(prospects):,} prospects to {args.output}')
    print(f'Match types: {counts}')
    if args.ai_review:
        print(f'AI calls: {ai_calls} with {args.workers} workers')


if __name__ == '__main__':
    main()
