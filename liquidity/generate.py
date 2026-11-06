"""Step 2-4 / 6: generate VALID baseline master + transaction + event data.

Everything here is anomaly-free. Labelled edge cases are injected later (inject.py).
Derived values (settled amounts, statuses, balances, buffers) are computed from source records.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
import random
from collections import defaultdict
from typing import Dict, List

from . import ids
from .config import (CLOSE_DATE, CURRENCIES, DATA_CUTOFF, DORMANT_DATE, FX_END, FX_SHOCKS, FX_START,
                     FX_START_RATES, FX_VOL, HISTORY_START, OPENING_DATE, PLAN_END, SCENARIOS, Scale)
from .util import bdays, daterange, last_bd_of_month, next_bd, prev_bd, td

DT = dt.datetime


def rng_for(seed: int, name: str) -> random.Random:
    return random.Random(f"{seed}:{name}")


# ============================================================================ FX
def gen_fx(rng):
    days = daterange(FX_START, FX_END)
    paths = {}
    for ccy in CURRENCIES:
        r0 = FX_START_RATES[ccy]
        r = r0
        series = []
        for d in days:
            if ccy != "USD":
                r *= math.exp(rng.gauss(0, FX_VOL[ccy]) + 0.02 * math.log(r0 / r))
                for (c, s, e, tot) in FX_SHOCKS:          # documented FX movement events
                    if c == ccy and s <= d <= e:
                        r *= (1 + tot) ** (1.0 / ((e - s).days + 1))
            series.append(round(r, 8))
        paths[ccy] = series
    rows, i = [], 0
    for di, d in enumerate(days):
        for ccy in CURRENCIES:
            i += 1
            rows.append(dict(rate_id=ids.rate_id(i), rate_date=d, from_currency=ccy, to_currency="USD",
                             rate=paths[ccy][di], rate_type="SPOT_CLOSE", source="SYNTHETIC_RANDOM_WALK"))
    return rows


# ============================================================================ entities / accounts
ADJ = ["Aurora", "Bluepeak", "Cedar", "Delta", "Ember", "Fjord", "Granite", "Harbor", "Iris", "Juniper", "Kestrel",
       "Lumen", "Meridian", "Nimbus", "Orchid", "Pinnacle", "Quartz", "Redwood", "Summit", "Tidal", "Umber",
       "Vertex", "Willow", "Xenon", "Yarrow", "Zephyr"]
IND = ["Textiles", "Logistics", "Foods", "Components", "Energy", "Retail", "Pharma", "Marine", "Software", "Materials"]
SUFFIX = {"US": "Inc", "DE": "GmbH", "FR": "SAS", "NL": "B.V.", "GB": "Ltd", "IN": "Pvt Ltd", "SG": "Pte Ltd"}
BANKS = ["Northbridge Bank", "Eastport Trust", "Southgate Bank", "Westfield Bank", "Crown Savings", "Lakeshore Bank"]


def gen_entities(rng, scale: Scale):
    n = scale.entities
    assert n >= 4, "need at least 4 entities (holding, active, dormant, closed)"
    base = [CURRENCIES[i % 5] for i in range(min(5, n))]
    while len(base) < n:
        base.append(rng.choices(CURRENCIES, weights=[.26, .24, .16, .18, .16])[0])
    dormant = {n - 1, n - 2} if n >= 10 else {n - 1}
    rows, meta = [], {}
    for i in range(1, n + 1):
        eid, ccy = ids.entity_id(i), base[i - 1]
        country = {"USD": "US", "GBP": "GB", "INR": "IN", "SGD": "SG"}.get(ccy) or rng.choice(["DE", "FR", "NL"])
        inc = dt.date(2006, 1, 1) + td(rng.randint(0, 365 * 18))
        size = min(3.0, max(0.4, math.exp(rng.gauss(0, 0.55))))
        status = "CLOSED" if i == n else ("DORMANT" if i in dormant else "ACTIVE")
        etype = "HOLDING" if i == 1 else "TREASURY_CENTRE" if i == 2 else "SPV" if i % 10 == 0 else "OPERATING"
        act_end = CLOSE_DATE if status == "CLOSED" else DORMANT_DATE if status == "DORMANT" else None
        window_end = min(act_end or PLAN_END, PLAN_END)
        rows.append(dict(
            entity_id=eid, legal_name=f"{ADJ[i % 26]} {IND[(i * 7 + i // 26) % 10]} {SUFFIX[country]}",
            entity_type=etype, country_code=country, functional_currency=ccy,
            parent_entity_id=None if i == 1 else ids.entity_id(rng.randint(1, min(i - 1, 5))),
            size_tier="SMALL" if size < 0.8 else "MEDIUM" if size < 1.5 else "LARGE",
            status=status,
            status_since=CLOSE_DATE if status == "CLOSED" else DORMANT_DATE if status == "DORMANT" else inc,
            incorporation_date=inc, effective_from=inc,
            effective_to=CLOSE_DATE if status == "CLOSED" else None,
            min_liquidity_buffer_usd_minor=0))
        meta[eid] = dict(size=size, act_end=act_end,
                         window_days=(window_end - dt.date(2026, 1, 5)).days + 1, status=status)
    return rows, meta


ACCT_TYPE_ORDER = ["OPERATING", "COLLECTION", "PAYROLL", "RESERVE", "FX"]


def gen_accounts(rng, ents, emeta, scale: Scale):
    rows = []
    for e in ents:
        eid, base = e["entity_id"], e["functional_currency"]
        others = [c for c in CURRENCIES if c != base]
        for n in range(1, scale.accounts_per_entity + 1):
            typ = ACCT_TYPE_ORDER[(n - 1) % 5]
            ccy = base if typ in ("OPERATING", "COLLECTION", "PAYROLL") else (
                ("USD" if base != "USD" else "EUR") if typ == "RESERVE" else rng.choice(others))
            hi = min(365 * 3, (dt.date(2025, 11, 30) - e["incorporation_date"]).days)
            opened = e["incorporation_date"] + td(rng.randint(0, max(0, hi)))
            closed = CLOSE_DATE if e["status"] == "CLOSED" else None
            rows.append(dict(
                account_id=ids.account_id(eid, n), entity_id=eid, bank_name=rng.choice(BANKS), account_type=typ,
                currency=ccy, status="CLOSED" if closed else "OPEN", opened_date=opened, closed_date=closed,
                opening_balance_date=OPENING_DATE, opening_balance_minor=0, overdraft_limit_minor=0,
                statement_date=closed or DATA_CUTOFF, statement_closing_balance_minor=0))
    return rows


def gen_blocks(rng, accts, emeta):
    """Compliance freezes: windows in which an account has no postings. Returns {account_id: [(start, end|None)]}."""
    eligible = [a["account_id"] for a in accts if emeta[a["entity_id"]]["status"] == "ACTIVE"
                and a["account_type"] in ("OPERATING", "COLLECTION", "PAYROLL")]
    blocks: Dict[str, list] = defaultdict(list)
    n_temp = max(1, len(accts) // 50)
    pick = rng.sample(eligible, min(len(eligible), n_temp + 1))
    pool = bdays(dt.date(2026, 2, 2), dt.date(2026, 8, 31))
    for aid in pick[:n_temp]:
        s = rng.choice(pool)
        blocks[aid].append((s, s + td(rng.randint(7, 21))))
    if len(pick) > n_temp:
        blocks[pick[n_temp]].append((dt.date(2026, 9, 8), None))      # still frozen at cutoff
    return blocks


def shift_for_block(aid, d, blocks):
    for (s, e) in blocks.get(aid, []):
        if e is None and d >= s:
            return None
        if e is not None and s <= d <= e:
            d = next_bd(e + td(1))
    return d


# ============================================================================ items (receivables / payables)
R_DELAY = {"LOW": (1, 2.0), "MEDIUM": (8, 5.0), "HIGH": (22, 12.0)}
R_OUT = {"LOW": (0.96, 0.04), "MEDIUM": (0.86, 0.12), "HIGH": (0.70, 0.20)}   # remaining prob = WRITE_OFF
R_REV = {"LOW": .03, "MEDIUM": .10, "HIGH": .25}
P_DELAY = {"CRITICAL": (0.0, 0.7), "STANDARD": (3.0, 2.0), "DEFERRABLE": (9.0, 4.0)}
CONF_R = {"LOW": .95, "MEDIUM": .80, "HIGH": .55}
CONF_P = {"CRITICAL": .98, "STANDARD": .92, "DEFERRABLE": .85}
P_CATS = ["SUPPLIER_PAYMENT", "PAYROLL", "TAX_PAYMENT", "LOAN_REPAYMENT", "CAPEX_ONE_OFF"]
P_CAT_W = [.66, .18, .06, .035, .025]
CAT_MEDIAN = {"CUSTOMER_RECEIPT": (20500, 1.0), "SUPPLIER_PAYMENT": (11000, 1.0), "PAYROLL": (60000, .4),
              "TAX_PAYMENT": (40000, .6), "LOAN_REPAYMENT": (55000, .3), "CAPEX_ONE_OFF": (200000, .6)}
BD_ALL = bdays(dt.date(2026, 1, 5), PLAN_END)


def _finalize_date(d, aid, blocks, act_end):
    d = shift_for_block(aid, d, blocks)
    if d is None:
        return None
    if act_end and d > act_end:
        d = prev_bd(act_end)
    return d if d <= DATA_CUTOFF else None


def gen_items(rng, ents, emeta, accts, scale, fx0, blocks):
    by_ent = defaultdict(dict)
    for a in accts:
        by_ent[a["entity_id"]].setdefault(a["account_type"], a)
    ent_ids = [e["entity_id"] for e in ents]
    weights = [emeta[e]["size"] * max(.05, emeta[e]["window_days"] / 365) for e in ent_ids]
    cust = [("CUST-%04d" % i, rng.choices(["LOW", "MEDIUM", "HIGH"], weights=[.55, .33, .12])[0]) for i in range(1, 401)]
    supp = [("SUPP-%04d" % i, rng.choices(["CRITICAL", "STANDARD", "DEFERRABLE"], weights=[.3, .5, .2])[0]) for i in range(1, 301)]
    n_r = scale.forecast_items // 2
    n_p = scale.forecast_items - n_r
    items = []
    seq = 0
    for kind, n in (("R", n_r), ("P", n_p)):
        for eid in rng.choices(ent_ids, weights, k=n):
            seq += 1
            em = emeta[eid]
            end = min(PLAN_END, em["act_end"] or PLAN_END)
            accs = by_ent[eid]
            if kind == "R":
                acct = accs["FX"] if rng.random() < .25 else accs["COLLECTION"]
                cat, (cp, tier) = "CUSTOMER_RECEIPT", rng.choice(cust)
                terms = rng.choices([30, 45, 60], weights=[.5, .3, .2])[0]
            else:
                cat = rng.choices(P_CATS, weights=P_CAT_W)[0]
                if cat == "SUPPLIER_PAYMENT":
                    acct = accs["FX"] if rng.random() < .3 else accs["OPERATING"]
                    cp, tier = rng.choice(supp)
                    terms = rng.choices([30, 45, 60], weights=[.5, .3, .2])[0]
                elif cat == "PAYROLL":
                    acct, cp, tier, terms = accs["PAYROLL"], "INTERNAL-PAYROLL", "CRITICAL", 7
                elif cat == "TAX_PAYMENT":
                    acct, cp, tier, terms = accs["OPERATING"], "TAXAUTH-" + _country(ents, eid), "CRITICAL", 30
                elif cat == "LOAN_REPAYMENT":
                    acct, cp, tier, terms = accs["OPERATING"], "LENDER-" + _country(ents, eid), "CRITICAL", 30
                else:
                    acct, cp, tier, terms = accs["OPERATING"], "SUPP-%04d" % rng.randint(1, 300), "STANDARD", 45
            # due date (business day) inside the entity's active window
            hi = bisect.bisect_right(BD_ALL, end)
            if cat == "PAYROLL":
                months = sorted({(d.year, d.month) for d in BD_ALL[:hi]})
                y, m = rng.choice(months)
                due = last_bd_of_month(y, m)
                if due > end:
                    due = BD_ALL[hi - 1]
            else:
                due = BD_ALL[rng.randrange(hi)]
            invoice = due - td(terms)
            if invoice > DATA_CUTOFF:           # every item must be booked by the data cutoff
                invoice = DATA_CUTOFF - td(rng.randint(0, 20))
                terms = (due - invoice).days
            med, sig = CAT_MEDIAN[cat]
            usd = math.exp(rng.gauss(math.log(med), sig)) * em["size"]
            amount = max(100, int(round(usd / fx0[acct["currency"]] * 100)))
            it = dict(kind=kind, seq=seq, entity_id=eid, account_id=acct["account_id"], currency=acct["currency"],
                      amount=amount, due=due, invoice=invoice, terms=terms, cp_ref=cp, tier=tier, category=cat,
                      large=(cat == "CAPEX_ONE_OFF"), revised_at=None, revised_date=None, cancel=None, wo=None,
                      pays=[], act_end=em["act_end"])
            _plan_outcome(rng, it, blocks)
            items.append(it)
    return items


def _country(ents, eid):
    for e in ents:
        if e["entity_id"] == eid:
            return e["country_code"]


def _plan_outcome(rng, it, blocks):
    """Outcome rules: counterparty tier -> delay, partial/split and write-off behaviour."""
    due, inv, aid, amt = it["due"], it["invoice"], it["account_id"], it["amount"]
    tier, kind = it["tier"], it["kind"]
    if rng.random() < (.015 if kind == "R" else .01):                      # cancelled before due
        c = inv + td(rng.randint(1, max(1, it["terms"] - 3)))
        if c <= DATA_CUTOFF:
            it["cancel"] = c
        return
    outcome = "FULL"
    if kind == "R":
        pf, ps = R_OUT[tier]
        u = rng.random()
        outcome = "FULL" if u < pf else "SPLIT" if u < pf + ps else "WRITE_OFF"
        mu, sd = R_DELAY[tier]
        if rng.random() < R_REV[tier]:                                      # customer announced a later date
            shift = max(3, int(round(mu * rng.uniform(.7, 1.3))))
            ra = max(inv, due - td(rng.randint(2, 15)))
            it["revised_at"], it["revised_date"] = ra, next_bd(due + td(shift))
            delay = shift + int(round(rng.gauss(0, 2)))
        else:
            delay = int(round(rng.gauss(mu, sd)))
            delay = max(-2, delay) if tier == "LOW" else max(0, delay)
    else:
        outcome = "SPLIT" if rng.random() < .04 else "FULL"
        if it["category"] in ("PAYROLL", "TAX_PAYMENT", "LOAN_REPAYMENT"):
            delay = 0
        elif it["category"] == "CAPEX_ONE_OFF":
            delay = int(round(rng.gauss(1, 1)))
            delay = max(0, delay)
        else:
            mu, sd = P_DELAY[tier]
            delay = max(0, int(round(rng.gauss(mu, sd))))
        if it["category"] == "SUPPLIER_PAYMENT" and rng.random() < .04:      # extension negotiated
            shift = rng.randint(5, 15)
            it["revised_at"] = max(inv, due - td(rng.randint(2, 10)))
            it["revised_date"] = next_bd(due + td(shift))
            delay = shift
    if outcome == "WRITE_OFF":
        wo = next_bd(due + td(90))
        if it["act_end"] and wo > it["act_end"]:
            wo = prev_bd(it["act_end"])
        if wo <= DATA_CUTOFF:
            it["wo"] = wo
        return
    p1 = next_bd(due + td(delay))
    if p1 <= inv:
        p1 = next_bd(inv + td(1))
    if outcome == "SPLIT":
        f = rng.uniform(.3, .7)
        a1 = max(1, int(round(amt * f)))
        a1 = min(a1, amt - 1) if amt > 1 else amt
        p2 = next_bd(p1 + td(rng.randint(10, 45)))
        plan = [(p1, a1), (p2, amt - a1)]
    else:
        plan = [(p1, amt)]
    pays = []
    for (d, a) in plan:
        fd = _finalize_date(d, aid, blocks, it["act_end"])
        if fd is None:
            break
        if pays and fd < pays[-1][0]:
            fd = pays[-1][0]
        pays.append((fd, a))
    it["pays"] = pays


# ============================================================================ lifecycle walker
DOC_NAMES = dict(OPEN="OPEN", OVERDUE="OVERDUE", PART="PARTIALLY_PAID", PAID="PAID", WO="WRITTEN_OFF", CANC="CANCELLED")
CF_NAMES = dict(OPEN="SCHEDULED", OVERDUE="DELAYED", PART="PARTIALLY_REALIZED", PAID="REALIZED",
                WO="WRITTEN_OFF", CANC="CANCELLED")


def walk(it, names, with_revision: bool):
    """Derive state events for a document / forecast item from its dated facts (<= data cutoff)."""
    cands = [(DT.combine(it["invoice"], dt.time(9, 0)), 0, "CREATE", 0)]
    for (d, a) in it["pays"]:
        cands.append((DT.combine(d, dt.time(15, 0)), 3, "PAY", a))
    cands.append((DT.combine(it["due"] + td(1), dt.time(0, 5)), 1, "OVERDUE", 0))
    if with_revision and it["revised_at"]:
        cands.append((DT.combine(it["revised_at"], dt.time(8, 0)), 2, "REVISE", 0))
    if it["wo"]:
        cands.append((DT.combine(it["wo"], dt.time(17, 0)), 4, "WO", 0))
    if it["cancel"]:
        cands.append((DT.combine(it["cancel"], dt.time(12, 0)), 4, "CANCEL", 0))
    cands.sort(key=lambda c: (c[0], c[1]))
    state, cum, out = None, 0, []

    def emit(ts, to, reason, actor):
        nonlocal state
        out.append((ts, state and names[state], names[to], reason, actor))
        state = to

    for ts, _, kind, a in cands:
        if ts.date() > DATA_CUTOFF:
            continue
        if kind == "CREATE":
            emit(ts, "OPEN", "INVOICE_RECORDED" if names is DOC_NAMES else "FORECAST_ITEM_CREATED", "OPERATIONS_ANALYST")
        elif state in ("PAID", "WO", "CANC"):
            continue
        elif kind == "OVERDUE":
            if state in ("OPEN", "PART") and cum < it["amount"]:
                emit(ts, "OVERDUE", "PAST_DUE", "SYSTEM")
        elif kind == "REVISE":
            if state == "OPEN" and cum == 0:
                emit(ts, "OVERDUE", "RESCHEDULED", "OPERATIONS_ANALYST")
        elif kind == "PAY":
            cum += a
            new = "PAID" if cum >= it["amount"] else "PART"
            if new != state:
                emit(ts, new, "PAYMENT_RECEIVED" if it["kind"] == "R" else "PAYMENT_MADE", "SYSTEM")
        elif kind == "WO":
            if state in ("OPEN", "OVERDUE", "PART"):
                emit(ts, "WO", "CREDIT_LOSS", "RISK_COMPLIANCE_REVIEWER")
        elif kind == "CANCEL":
            if state == "OPEN" and cum == 0:
                emit(ts, "CANC", "CANCELLED_BY_REQUEST", "OPERATIONS_ANALYST")
    return out


# ============================================================================ ledger
OPS_TYPE_W = {"COLLECTION": 1.5, "OPERATING": 1.5, "PAYROLL": .5, "RESERVE": .3, "FX": 1.0}
OPS_CREDIT_P = {"COLLECTION": .78, "OPERATING": .45, "PAYROLL": .25, "RESERVE": .70, "FX": .50}
OPS_CREDIT_TYPES = {"COLLECTION": ["CARD_SETTLEMENT", "MISC_RECEIPT"], "OPERATING": ["MISC_RECEIPT"],
                    "PAYROLL": ["MISC_RECEIPT"], "RESERVE": ["INTEREST_CREDIT"], "FX": ["MISC_RECEIPT"]}
OPS_DEBIT_TYPES = ["BANK_FEE", "MISC_PAYMENT"]
SETTLE_TYPE = {"CUSTOMER_RECEIPT": "CUSTOMER_RECEIPT", "SUPPLIER_PAYMENT": "SUPPLIER_PAYMENT", "PAYROLL": "PAYROLL",
               "TAX_PAYMENT": "TAX_PAYMENT", "LOAN_REPAYMENT": "LOAN_REPAYMENT", "CAPEX_ONE_OFF": "CAPEX_PAYMENT"}


def build_ledger(rng, scale, ents, emeta, accts, items, blocks, fx0):
    acct_by_id = {a["account_id"]: a for a in accts}
    temp, k = [], 0
    for it in items:                                        # settlements of scheduled items
        for (d, a) in it["pays"]:
            k += 1
            acc = acct_by_id[it["account_id"]]
            temp.append(dict(account_id=acc["account_id"], entity_id=acc["entity_id"], entry_date=d,
                             currency=acc["currency"], direction="CREDIT" if it["kind"] == "R" else "DEBIT",
                             amount_minor=a, entry_type=SETTLE_TYPE[it["category"]], item=it, prio=1, seq=k,
                             counterparty_ref=it["cp_ref"], description="settlement"))
    n_closed = sum(1 for a in accts if a["status"] == "CLOSED")
    n_ops = scale.ledger - len(temp) - n_closed
    assert n_ops > 0, "ledger volume too small for the number of scheduled items"

    # operating (unscheduled) activity per account
    allowed = {}
    wts = []
    for a in accts:
        em = emeta[a["entity_id"]]
        start = max(HISTORY_START, a["opened_date"])
        end = min(em["act_end"] or DATA_CUTOFF, DATA_CUTOFF)
        days = bdays(start, end)
        bl = blocks.get(a["account_id"], [])
        if bl:
            days = [d for d in days if not any(s <= d and (e is None or d <= e) for s, e in bl)]
        allowed[a["account_id"]] = days
        wts.append(em["size"] * OPS_TYPE_W[a["account_type"]] * max(.02, len(days) / 273))
    picks = rng.choices(accts, wts, k=n_ops)
    for a in picks:
        k += 1
        em = emeta[a["entity_id"]]
        d = rng.choice(allowed[a["account_id"]])
        credit = rng.random() < OPS_CREDIT_P[a["account_type"]]
        usd = math.exp(rng.gauss(math.log(900), 1.0)) * em["size"]
        amt = max(100, int(round(usd / fx0[a["currency"]] * 100)))
        et = rng.choice(OPS_CREDIT_TYPES[a["account_type"]]) if credit else rng.choice(OPS_DEBIT_TYPES)
        temp.append(dict(account_id=a["account_id"], entity_id=a["entity_id"], entry_date=d, currency=a["currency"],
                         direction="CREDIT" if credit else "DEBIT", amount_minor=amt, entry_type=et, item=None,
                         prio=1, seq=k, counterparty_ref=None, description="operating activity"))

    # opening balances derived so that history never produces an undocumented overdraft
    by_acct = defaultdict(list)
    for e in temp:
        by_acct[e["account_id"]].append(e)
    for a in accts:
        es = sorted(by_acct[a["account_id"]], key=lambda e: (e["entry_date"], 0 if e["direction"] == "CREDIT" else 1, e["seq"]))
        cum = mn = gross = 0
        for e in es:
            cum += e["amount_minor"] if e["direction"] == "CREDIT" else -e["amount_minor"]
            mn = min(mn, cum)
            gross += e["amount_minor"]
        days = max(1, len(allowed[a["account_id"]]))
        daily = gross / days if gross else 10000
        od = int(round(daily * 4)) if a["account_type"] == "OPERATING" else 0
        thin = rng.random() < .12
        if thin and od:
            opening = max(0, int(math.ceil(-mn - 0.5 * od)))
        elif thin:
            opening = max(0, -mn) + int(daily * rng.uniform(0, .3))
        else:
            opening = max(0, -mn) + int(daily * rng.uniform(1, 8))
        a["opening_balance_minor"], a["overdraft_limit_minor"] = opening, od
        a["_final"] = opening + cum

    for a in accts:                                          # closure sweeps for the closed entity
        if a["status"] == "CLOSED":
            bal = a["_final"]
            assert bal != 0, "zero-balance sweep not supported; adjust seed"
            k += 1
            temp.append(dict(account_id=a["account_id"], entity_id=a["entity_id"], entry_date=a["closed_date"],
                             currency=a["currency"], direction="DEBIT" if bal > 0 else "CREDIT", amount_minor=abs(bal),
                             entry_type="ACCOUNT_CLOSURE_SWEEP", item=None, prio=2, seq=k, counterparty_ref=None,
                             description="closing balance swept on account closure"))

    temp.sort(key=lambda e: (e["entry_date"], e["account_id"], e["prio"], 0 if e["direction"] == "CREDIT" else 1, e["seq"]))
    running = {a["account_id"]: a["opening_balance_minor"] for a in accts}
    rows = []
    for i, e in enumerate(temp, 1):
        sgn = e["amount_minor"] if e["direction"] == "CREDIT" else -e["amount_minor"]
        running[e["account_id"]] += sgn
        lid = ids.ledger_id(i)
        e["ledger_id"] = lid
        rows.append(dict(ledger_id=lid, account_id=e["account_id"], entity_id=e["entity_id"], entry_date=e["entry_date"],
                         currency=e["currency"], direction=e["direction"], amount_minor=e["amount_minor"],
                         signed_amount_minor=sgn, balance_after_minor=running[e["account_id"]],
                         entry_type=e["entry_type"], cf_id=None, source_ref_id=None, counterparty_ref=e["counterparty_ref"],
                         description=e["description"], posting_status="POSTED"))
        if e["item"] is not None:
            e["item"].setdefault("ledger", []).append(i - 1)
    for a in accts:
        a["statement_closing_balance_minor"] = running[a["account_id"]]    # bank truth = valid ledger result
        a.pop("_final", None)
    return rows


# ============================================================================ documents / forecast items / events
def build_documents(items, ledger_rows):
    items.sort(key=lambda it: (it["due"], it["kind"], it["seq"]))
    rn = pn = cn = 0
    rcv, pay, cf, ev = [], [], [], []
    for it in items:
        cn += 1
        it["cf_id"] = ids.cf_id(cn)
        if it["kind"] == "R":
            rn += 1
            it["doc_id"] = ids.receivable_id(rn)
        else:
            pn += 1
            it["doc_id"] = ids.payable_id(pn)
    for it in items:
        for li in it.get("ledger", []):
            ledger_rows[li]["cf_id"] = it["cf_id"]
            ledger_rows[li]["source_ref_id"] = it["doc_id"]
            ledger_rows[li]["description"] = ("Customer receipt " if it["kind"] == "R" else "Payment ") + it["doc_id"]
        pays = sorted(it["pays"])
        settled = sum(a for _, a in pays)
        last_pay = pays[-1][0] if pays else None
        dev = walk(it, DOC_NAMES, False)
        cev = walk(it, CF_NAMES, True)
        dstate, cstate = dev[-1][2], cev[-1][2]
        term = {"PAID", "WRITTEN_OFF", "CANCELLED"}
        dterm = next((e[0].date() for e in dev if e[2] in term), None)
        cterm = next((e[0].date() for e in cev if e[2] in {"REALIZED", "WRITTEN_OFF", "CANCELLED"}), None)
        outstanding = it["amount"] - settled if dstate in ("OPEN", "OVERDUE", "PARTIALLY_PAID") else 0
        dpd = (DATA_CUTOFF - it["due"]).days if outstanding > 0 and it["due"] < DATA_CUTOFF else 0
        common = dict(entity_id=it["entity_id"], account_id=it["account_id"])
        if it["kind"] == "R":
            rcv.append(dict(receivable_id=it["doc_id"], **common, counterparty_ref=it["cp_ref"],
                            counterparty_risk_tier=it["tier"], invoice_date=it["invoice"], due_date=it["due"],
                            payment_terms_days=it["terms"], currency=it["currency"], invoice_amount_minor=it["amount"],
                            settled_amount_minor=settled, outstanding_minor=outstanding, last_payment_date=last_pay,
                            days_past_due_at_cutoff=dpd, status=dstate, terminal_date=dterm, status_as_of_date=DATA_CUTOFF))
            ot = "RECEIVABLE"
        else:
            pay.append(dict(payable_id=it["doc_id"], **common, supplier_ref=it["cp_ref"], supplier_tier=it["tier"],
                            category=it["category"], is_large_one_off=it["large"], invoice_date=it["invoice"],
                            due_date=it["due"], payment_terms_days=it["terms"], currency=it["currency"],
                            invoice_amount_minor=it["amount"], settled_amount_minor=settled, outstanding_minor=outstanding,
                            last_payment_date=last_pay, days_past_due_at_cutoff=dpd, status=dstate, terminal_date=dterm,
                            status_as_of_date=DATA_CUTOFF))
            ot = "PAYABLE"
        conf = (CONF_R[it["tier"]] if it["kind"] == "R" else CONF_P[it["tier"]]) * (0.9 if it["revised_at"] else 1.0)
        if it["large"]:
            conf = min(conf, 0.9)
        cf.append(dict(cf_id=it["cf_id"], **common, receivable_id=it["doc_id"] if it["kind"] == "R" else None,
                       payable_id=it["doc_id"] if it["kind"] == "P" else None,
                       direction="INFLOW" if it["kind"] == "R" else "OUTFLOW", category=it["category"],
                       currency=it["currency"], scheduled_amount_minor=it["amount"], expected_date=it["due"],
                       revised_expected_date=it["revised_date"] if it["revised_at"] else None,
                       revised_at=it["revised_at"], created_date=it["invoice"], confidence_score=round(conf, 4),
                       is_large_one_off=it["large"], status=cstate, realized_amount_minor=settled, realized_date=last_pay,
                       terminal_date=cterm))
        for obj_type, oid, evs in ((ot, it["doc_id"], dev), ("CASH_FLOW_FORECAST", it["cf_id"], cev)):
            for n, (ts, fr, to, reason, actor) in enumerate(evs, 1):
                ev.append(dict(object_type=obj_type, object_id=oid, sequence_no=n, from_state=fr, to_state=to,
                               event_ts=ts, actor_role=actor, reason_code=reason))
    return rcv, pay, cf, ev


def build_master_events(ents, accts, blocks):
    ev = []

    def add(ot, oid, n, fr, to, ts, actor, reason):
        ev.append(dict(object_type=ot, object_id=oid, sequence_no=n, from_state=fr, to_state=to, event_ts=ts,
                       actor_role=actor, reason_code=reason))

    for e in ents:
        add("LEGAL_ENTITY", e["entity_id"], 1, None, "ACTIVE", DT.combine(e["incorporation_date"], dt.time(9, 0)),
            "SYSTEM_ADMIN", "ONBOARDING")
        if e["status"] == "DORMANT":
            add("LEGAL_ENTITY", e["entity_id"], 2, "ACTIVE", "DORMANT", DT.combine(DORMANT_DATE, dt.time(10, 0)),
                "ACCOUNT_HOLDER", "DORMANCY_REQUEST")
        if e["status"] == "CLOSED":
            add("LEGAL_ENTITY", e["entity_id"], 2, "ACTIVE", "CLOSED", DT.combine(CLOSE_DATE, dt.time(16, 0)),
                "ACCOUNT_HOLDER", "ENTITY_CLOSURE")
    for a in accts:
        aid = a["account_id"]
        add("BANK_ACCOUNT", aid, 1, None, "OPEN", DT.combine(a["opened_date"], dt.time(9, 0)), "SYSTEM_ADMIN", "ACCOUNT_OPENED")
        n = 1
        state = "OPEN"
        for (s, e) in blocks.get(aid, []):
            n += 1
            add("BANK_ACCOUNT", aid, n, "OPEN", "FROZEN", DT.combine(s, dt.time(0, 30)), "RISK_COMPLIANCE_REVIEWER", "COMPLIANCE_HOLD")
            state = "FROZEN"
            if e is not None:
                n += 1
                add("BANK_ACCOUNT", aid, n, "FROZEN", "OPEN", DT.combine(next_bd(e + td(1)), dt.time(8, 0)),
                    "RISK_COMPLIANCE_REVIEWER", "HOLD_RELEASED")
                state = "OPEN"
        if a["status"] == "CLOSED":
            n += 1
            add("BANK_ACCOUNT", aid, n, state, "CLOSED", DT.combine(CLOSE_DATE, dt.time(17, 0)), "SYSTEM_ADMIN", "ENTITY_CLOSURE")
        elif state == "FROZEN":
            a["status"] = "FROZEN"
    return ev


def build_scenarios():
    rows, asm = [], []
    n = 0
    for s in SCENARIOS:
        rows.append(dict(s, effective_from=dt.date(2026, 1, 1), effective_to=None, status="ACTIVE",
                         created_by_role="SYSTEM_ADMIN"))
        for p, unit, why in (
                ("receipt_delay_days", "days", "customer payment delay assumption"),
                ("payable_acceleration_days", "days", "supplier early-payment pressure"),
                ("receivable_haircut_pct", "fraction", "expected credit loss on receipts"),
                ("one_off_outflow_multiplier", "x", "cost overrun on large one-off payments"),
                ("fx_shock_pct", "fraction", "non-USD depreciation vs USD at plan rate"),
                ("overdue_rollover_days", "days", "days after run date at which overdue items clear")):
            n += 1
            asm.append(dict(assumption_id=ids.assumption_id(n), scenario_id=s["scenario_id"], parameter_name=p,
                            parameter_value=float(s[p]), unit=unit, rationale=why))
    return rows, asm


def build_baseline(scale: Scale, seed: int) -> Dict[str, list]:
    fx = gen_fx(rng_for(seed, "fx"))
    fx0 = {r["from_currency"]: r["rate"] for r in fx if r["rate_date"] == OPENING_DATE}
    ents, emeta = gen_entities(rng_for(seed, "entities"), scale)
    accts = gen_accounts(rng_for(seed, "accounts"), ents, emeta, scale)
    blocks = gen_blocks(rng_for(seed, "blocks"), accts, emeta)
    items = gen_items(rng_for(seed, "items"), ents, emeta, accts, scale, fx0, blocks)
    ledger = build_ledger(rng_for(seed, "ledger"), scale, ents, emeta, accts, items, blocks, fx0)
    rcv, pay, cf, ev = build_documents(items, ledger)
    ev += build_master_events(ents, accts, blocks)
    sc, asm = build_scenarios()
    # derived entity buffer: 2.0x mean monthly payables, USD-equivalent at opening FX (policy: ~2 months of outflows)
    tot = defaultdict(float)
    for p in pay:
        tot[p["entity_id"]] += p["invoice_amount_minor"] * fx0[p["currency"]]
    for e in ents:
        e["min_liquidity_buffer_usd_minor"] = int(round(2.0 * tot[e["entity_id"]] / 12.0))
    return dict(legal_entity=ents, bank_account=accts, currency_rate=fx, liquidity_scenario=sc, scenario_assumption=asm,
                receivable=rcv, payable=pay, cash_flow_forecast=cf, ledger_entry=ledger, state_event=ev)
