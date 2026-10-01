from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .models import Classification

TYPES = {"Existing buyout software customer", "RTO customer", "Leasing customer", "PPU customer", "Service/Training customer", "Potential customer", "Customer by alliance", ""}
STATUSES = {"Ongoing", "Expired", ""}
ACTIVE = ("A:", "B:", "C:", "D:", "E:")
BUYOUT_PREFIXES = ("edb", "ed", "pro", "expert", "adv", "aep", "ic")


def clean(v): return re.sub(r"\s+", " ", str(v or "").strip())
def fold(v): return clean(v).casefold()
def product(r): return fold(r.get("Product Type", ""))
def opname(r): return fold(r.get("Opportunity Name", ""))
def stage(r): return fold(r.get("Stage", ""))
def won(r): return stage(r) in {"closed won", "closed pending"}
def closed_won(r): return stage(r) == "closed won"
def lost(r): return stage(r) == "closed lost"
def active(r): return clean(r.get("Stage", "")).upper().startswith(ACTIVE)


def parse_date(v):
    v = clean(v)
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y"):
        try: return datetime.strptime(v, fmt).date()
        except ValueError: pass
    return None


def event_date(r): return parse_date(r.get("Close Date")) or parse_date(r.get("Created Date"))
def sort_key(r): return (event_date(r) or date.min, parse_date(r.get("Created Date")) or date.min)
def token(text, value): return bool(re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", text))


def noise(r):
    name, ptype = opname(r), product(r)
    if "islm" in name or "islm" in ptype: return True
    if ptype.startswith("service") or ptype == "moldex3d software - upgrade": return False
    return ptype == "others" or any(token(name, x) for x in ("add", "fea", "other"))


def extreme_lease(r):
    return product(r) == "moldex3d software - subscription" and token(opname(r), "extreme") and not noise(r)


def legacy_lease(r):
    if noise(r): return False
    p, n = product(r), opname(r)
    return (p == "moldex3d software - leasing" or p == "moldex3d software") and any(token(n, x) for x in ("lease", "leasing", "rental"))


def ppu(r): return product(r) == "moldex3d software - ppu" and not noise(r)
def rto(r): return product(r) == "moldex3d software - rto" and not noise(r)
def royalty(r): return product(r) == "moldex3d software - oem royalty" and not noise(r)


def rto_term(r):
    m = re.search(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", opname(r))
    if m: return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?<![a-z0-9])(\d+)(?:st|nd|rd|th)(?![a-z0-9])", opname(r))
    return (int(m.group(1)), 0) if m else None


def rto_state(rows):
    rto_rows = [r for r in rows if rto(r)]
    # Ordinals are attached only when there is a won RTO anchor. This prevents
    # an unrelated 1/2 or 2nd software package from becoming an RTO sequence.
    if any(won(r) for r in rto_rows):
        rto_rows += [r for r in rows if rto_term(r) and r not in rto_rows]
    won_rows = [r for r in rto_rows if won(r)]
    if not won_rows: return None
    terms = [rto_term(r) for r in won_rows if rto_term(r)]
    complete = any(a >= b for a, b in terms if b)
    ordinals = [a for a, b in terms if not b]
    if not complete and ordinals:
        complete = len(terms) >= 3 and sorted(set(ordinals)) == list(range(1, max(ordinals) + 1))
    if complete: return None
    latest = max(rto_rows, key=sort_key)
    latest_won = max(won_rows, key=sort_key)
    return Classification("RTO customer", "Expired" if lost(latest) and sort_key(latest) >= sort_key(latest_won) else "Ongoing", {"rule": "incomplete RTO sequence"})


def buyout_prefix(r):
    if noise(r) or product(r) in {"moldex3d software - rto", "moldex3d software - ppu", "moldex3d software - subscription", "moldex3d software - oem royalty"}: return None
    if product(r) == "moldex3d software - upgrade": return "upgrade"
    if "moldex3d software" not in product(r): return None
    m = re.match(r"([a-z0-9]+)", opname(r))
    if not m: return None
    return next((p for p in BUYOUT_PREFIXES if m.group(1) == p or m.group(1).startswith(p)), None)


def valid_ma(r):
    return product(r) == "moldex3d maintenance" or (token(opname(r), "ma") and not token(opname(r), "mat"))


def ppu_days(r):
    m = re.search(r"(\d+)\s*(month|months|year|years|yr|yrs)", opname(r))
    if not m: return 365
    return int(m.group(1)) * (30 if m.group(2).startswith("month") else 365)


def classify(account_name: str, rows: list[dict], as_of: date) -> Classification:
    ordered = sorted(rows, key=sort_key)
    types = {clean(r.get("Customer Type Auto")) for r in rows}
    if "Partner" in types or "Reseller" in types: return Classification("", "", {"rule": "Partner/Reseller"})
    usable = [r for r in ordered if not (noise(r) and product(r) != "moldex3d software - upgrade")]
    rto_result = rto_state(usable)
    if rto_result: return rto_result

    base_buyouts = [r for r in usable if won(r) and buyout_prefix(r) not in {None, "upgrade"}]
    direct = []
    for r in usable:
        if not won(r): continue
        prefix = buyout_prefix(r)
        if rto(r) or ppu(r) or extreme_lease(r) or legacy_lease(r) or prefix not in {None, "upgrade"}: direct.append(r)
        elif prefix == "upgrade" and any(sort_key(old) <= sort_key(r) for old in base_buyouts): direct.append(r)
    ma_rows = [r for r in ordered if valid_ma(r)]

    supporting = [r for r in ordered if won(r) and "moldex3d software" in product(r) and product(r) not in {"moldex3d software - rto", "moldex3d software - ppu", "moldex3d software - subscription", "moldex3d software - oem royalty", "moldex3d software - upgrade"}]
    if not direct and supporting and ma_rows: direct = supporting

    leases = [r for r in ordered if (extreme_lease(r) or legacy_lease(r)) and (won(r) or lost(r) or active(r))]
    royalties = [r for r in usable if royalty(r) and closed_won(r)]

    # Customer transitions are chronological across product channels. A newer
    # alliance royalty can therefore supersede an older direct-software/MA
    # relationship instead of losing to a fixed product-type precedence rule.
    if royalties:
        latest_royalty = max(royalties, key=lambda r: parse_date(r.get("Created Date")) or event_date(r) or date.min)
        royalty_date = parse_date(latest_royalty.get("Created Date")) or event_date(latest_royalty)
        direct_history = direct + leases + ma_rows
        latest_direct = max(direct_history, key=sort_key) if direct_history else None
        if royalty_date and (latest_direct is None or royalty_date > (event_date(latest_direct) or date.min)):
            return Classification("Customer by alliance", "Ongoing" if as_of - royalty_date <= timedelta(days=183) else "Expired", {"rule": "latest commercial transition to OEM royalty"})

    if direct:
        latest = max(direct + [r for r in leases if r not in direct], key=sort_key)
        if ppu(latest):
            wins = [r for r in direct if ppu(r) and closed_won(r)]
            latest_ppu = max(wins, key=sort_key) if wins else latest
            start = event_date(latest_ppu)
            return Classification("PPU customer", "Ongoing" if start and as_of <= start + timedelta(days=ppu_days(latest_ppu)) else "Expired", {"rule": "latest PPU"})
        if extreme_lease(latest) or legacy_lease(latest):
            latest_lease = max(leases, key=sort_key)
            return Classification("Leasing customer", "Expired" if lost(latest_lease) else "Ongoing", {"rule": "latest lease"})

        latest_ma = max(ma_rows, key=sort_key) if ma_rows else None
        if latest_ma is None: return Classification("Existing buyout software customer", "Expired", {"rule": "completed software purchase without following MA"})
        latest_lost = max((r for r in ma_rows if lost(r)), key=sort_key, default=None)
        if latest_lost:
            loss = sort_key(latest_lost)
            if not any(closed_won(r) and sort_key(r) > loss for r in ma_rows) and not any(closed_won(r) and sort_key(r) > loss for r in direct):
                return Classification("Existing buyout software customer", "Expired", {"rule": "latest MA lost without later closed-won event"})
        d = event_date(latest_ma)
        ongoing = active(latest_ma) or (closed_won(latest_ma) and d and as_of <= d + timedelta(days=365))
        return Classification("Existing buyout software customer", "Ongoing" if ongoing else "Expired", {"rule": "buyout/RTO lineage" if ongoing else "historical MA without continuation"})

    if royalties:
        latest = max(royalties, key=lambda r: parse_date(r.get("Created Date")) or event_date(r) or date.min)
        created = parse_date(latest.get("Created Date")) or event_date(latest)
        return Classification("Customer by alliance", "Ongoing" if created and as_of - created <= timedelta(days=183) else "Expired", {"rule": "latest OEM royalty"})
    if any(product(r).startswith("service") and closed_won(r) for r in usable): return Classification("Service/Training customer", "", {"rule": "service-only"})
    if "Potential Customer" in types: return Classification("Potential customer", "", {"rule": "Customer Type Auto"})

    if ma_rows:
        years = [(event_date(r) or date.min).year for r in ma_rows]
        if years and min(years) <= 2016:
            latest = max(ma_rows, key=sort_key); d = event_date(latest)
            ongoing = active(latest) or (closed_won(latest) and d and as_of <= d + timedelta(days=365))
            return Classification("Existing buyout software customer", "Ongoing" if ongoing else "Expired", {"rule": "legacy MA-only history through 2016"})
    return Classification("", "", {"rule": "unclassified", "ambiguous": any("moldex3d software" in product(r) and won(r) for r in ordered)})
