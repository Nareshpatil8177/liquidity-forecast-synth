"""Step 5 / 7: inject LABELLED edge cases into otherwise valid data and record ground truth.

Anomalies never silently corrupt unrelated rows: each one touches exactly the field named in ground_truth.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import ids
from .config import (ANOMALY_BASE_COUNTS, CURRENCIES, DATA_CUTOFF, FX_END, HORIZON_DAYS, OPENING_DATE, RUN_DATES, Scale)
from .generate import rng_for
from .rules import fx_decision
from .util import td

DUP_RUN = ids.run_id(dt.date(2026, 4, 1), 1)      # BASE   run, April  -> double counted lines
LEAK_RUN = ids.run_id(dt.date(2026, 6, 1), 2)     # DELAYED run, June  -> look-ahead on actuals
FX_SINGLE = ("INR", dt.date(2026, 4, 30))          # cutoff day of the 2026-05-01 runs
FX_GAP = ("GBP", dt.date(2026, 7, 14), dt.date(2026, 7, 18))   # 5 consecutive missing days

GT_FIELDS = ["anomaly_id", "issue_type", "severity", "table_name", "record_key", "field_name", "injected_value",
             "correct_value", "related_keys", "expected_detection_rule", "expected_decision", "notes"]


def _cnt(scale: Scale, key: str) -> int:
    return max(2, round(ANOMALY_BASE_COUNTS[key] * scale.factor))


def _gt(gt, issue, sev, table, key, field, inj, cor, related, rule, decision, notes=""):
    gt.append(dict(anomaly_id=ids.anomaly_id(len(gt) + 1), issue_type=issue, severity=sev, table_name=table,
                   record_key=key, field_name=field, injected_value=inj, correct_value=cor, related_keys=related,
                   expected_detection_rule=rule, expected_decision=decision, notes=notes))


def inject_pre_forecast(t, seed, scale, gt):
    rng = rng_for(seed, "inject")
    # ------------------------------------------------------------ FX rate missing
    fx = t["currency_rate"]
    by_key = {(r["from_currency"], r["rate_date"]): r for r in fx}
    cdates = {d - td(1) for d in RUN_DATES}
    delete = [FX_SINGLE] + [(FX_GAP[0], FX_GAP[1] + td(i)) for i in range((FX_GAP[2] - FX_GAP[1]).days + 1)]
    taken = set(delete)
    n_rand = _cnt(scale, "fx_missing_random")
    cand = [r for r in fx if r["from_currency"] != "USD" and r["rate_date"] not in cdates
            and r["rate_date"] not in (OPENING_DATE, FX_END)]
    while n_rand > 0:
        r = rng.choice(cand)
        k = (r["from_currency"], r["rate_date"])
        near = {(k[0], k[1] + td(i)) for i in (-1, 0, 1)}
        if near & taken:
            continue
        taken.add(k)
        delete.append(k)
        n_rand -= 1
    removed = {k: by_key[k] for k in delete}
    t["currency_rate"] = [r for r in fx if (r["from_currency"], r["rate_date"]) not in removed]
    per = defaultdict(list)
    for (c, d) in removed:
        per[c].append(d)
    for c, ds in sorted(per.items()):
        ds.sort()
        pos = 0
        prev = None
        for d in ds:
            pos = pos + 1 if prev is not None and d == prev + td(1) else 1
            prev = d
            _gt(gt, "FX_RATE_MISSING", "HIGH" if pos > 3 else "MEDIUM", "currency_rate", f"{c}|{d.isoformat()}", "rate",
                "", f"{removed[(c, d)]['rate']:.8f}", removed[(c, d)]["rate_id"],
                "no rate row for (currency, date) inside the covered calendar", fx_decision(pos),
                f"position {pos} in consecutive gap")
    # ------------------------------------------------------------ currency mixed without conversion
    led = t["ledger_entry"]
    acct = {a["account_id"]: a for a in t["bank_account"]}
    for i in sorted(rng.sample(range(len(led)), _cnt(scale, "mixed_currency"))):
        r = led[i]
        true = acct[r["account_id"]]["currency"]
        r["currency"] = rng.choice([c for c in CURRENCIES if c != true])
        _gt(gt, "CURRENCY_MIXED_WITHOUT_CONVERSION", "HIGH", "ledger_entry", r["ledger_id"], "currency", r["currency"], true,
            r["account_id"], "ledger_entry.currency != bank_account.currency (no conversion row/rate applied)",
            "QUARANTINE_AND_CONVERT_AT_ENTRY_DATE_RATE", "amount posted raw into account balance")
    # ------------------------------------------------------------ opening + ledger != closing
    mags = [1, 100, 2500, 10000, 87500, 250000]
    accts = t["bank_account"]
    for j, i in enumerate(sorted(rng.sample(range(len(accts)), _cnt(scale, "balance_mismatch")))):
        a = accts[i]
        delta = mags[j % len(mags)] * rng.choice([-1, 1])
        true = a["statement_closing_balance_minor"]
        a["statement_closing_balance_minor"] = true + delta
        _gt(gt, "BALANCE_MISMATCH", "HIGH" if abs(delta) >= 10000 else "LOW", "bank_account", a["account_id"],
            "statement_closing_balance_minor", str(true + delta), str(true), f"delta_minor={delta}",
            "opening_balance + sum(signed ledger) != statement_closing_balance", "INVESTIGATE_AND_ADJUST_BEFORE_CLOSE",
            "includes 1-minor-unit boundary case" if abs(delta) == 1 else "")


def inject_lines(ctx, lines_by_run, specs, counter, gt, seed, scale):
    """Forecast-side anomalies: double counted cash flow and use of actuals after cutoff."""
    rng = rng_for(seed, "inject-lines")
    # ------------------------------------------------ cash flow counted twice
    L = lines_by_run[DUP_RUN]
    for idx in sorted(rng.sample(range(len(L)), min(len(L), _cnt(scale, "double_count")))):
        o = L[idx]
        counter[0] += 1
        d = dict(o, line_id=ids.run_item_id(counter[0]))
        L.append(d)
        _gt(gt, "CASH_FLOW_COUNTED_TWICE", "HIGH", "forecast_run_item", d["line_id"], "cf_id", o["cf_id"], "(row should not exist)",
            f"{DUP_RUN}|{o['line_id']}", "more than one forecast_run_item per (run_id, cf_id)", "REJECT_RUN_AND_RERUN",
            "duplicate of an earlier line in the same run")
    # ------------------------------------------------ forecast uses actual after cutoff
    spec = next(s for s in specs if s["run_id"] == LEAK_RUN)
    C, hend = spec["run_date"] - td(1), spec["run_date"] + td(HORIZON_DAYS - 1)
    L = lines_by_run[LEAK_RUN]
    cands = []
    for i, ln in enumerate(L):
        for (d, a, lid) in ctx.pays.get(ln["cf_id"], ()):
            if C < d <= min(hend, DATA_CUTOFF):
                cands.append((i, d, a, lid))
                break
    n = min(len(cands), _cnt(scale, "leak"))
    for (i, d, a, lid) in sorted(rng.sample(cands, n)):
        ln = L[i]
        ln.update(amount_basis="ACTUAL", actual_ledger_id=lid, effective_date=d, adjusted_amount_minor=a,
                  adjusted_amount_usd_minor=int(round(a * ln["fx_rate_to_usd"])))
        _gt(gt, "FORECAST_USES_ACTUAL_AFTER_CUTOFF", "HIGH", "forecast_run_item", ln["line_id"], "amount_basis", "ACTUAL",
            "SCHEDULED", f"{LEAK_RUN}|{ln['cf_id']}|{lid}",
            "amount_basis=ACTUAL and ledger entry_date > run.data_cutoff_date", "REJECT_RUN_AND_RERUN",
            f"actual posted {d.isoformat()} after cutoff {C.isoformat()}")
