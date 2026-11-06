"""Rule-based exception detectors. They read INPUT TABLES ONLY (never ground truth) and emit exception cases
with a recommended decision. evaluate.py then scores them against ground_truth."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .rules import fx_decision
from .util import td

DET_FIELDS = ["exception_id", "issue_type", "severity", "table_name", "record_key", "rule_id", "detected_value",
              "expected_value", "recommended_decision", "details"]


def detect_all(t):
    out = []
    acct = {a["account_id"]: a for a in t["bank_account"]}

    def add(issue, sev, table, key, rule, det, exp, dec, details=""):
        out.append(dict(exception_id=f"EXC-{len(out) + 1:05d}", issue_type=issue, severity=sev, table_name=table,
                        record_key=key, rule_id=rule, detected_value=det, expected_value=exp,
                        recommended_decision=dec, details=details))

    # D1 opening + ledger != bank closing
    sums = defaultdict(int)
    for le in t["ledger_entry"]:
        sums[le["account_id"]] += le["signed_amount_minor"]
    for a in t["bank_account"]:
        calc = a["opening_balance_minor"] + sums[a["account_id"]]
        if calc != a["statement_closing_balance_minor"]:
            d = a["statement_closing_balance_minor"] - calc
            add("BALANCE_MISMATCH", "HIGH" if abs(d) >= 10000 else "LOW", "bank_account", a["account_id"], "D1_RECON",
                a["statement_closing_balance_minor"], calc, "INVESTIGATE_AND_ADJUST_BEFORE_CLOSE", f"delta_minor={d}")
    # D2 missing FX rate rows inside the covered calendar
    have = {(r["from_currency"], r["rate_date"]) for r in t["currency_rate"]}
    dates = [r["rate_date"] for r in t["currency_rate"]]
    lo, hi = min(dates), max(dates)
    for ccy in sorted({r["from_currency"] for r in t["currency_rate"]} - {"USD"}):
        pos, d = 0, lo
        while d <= hi:
            if (ccy, d) not in have:
                pos += 1
                add("FX_RATE_MISSING", "HIGH" if pos > 3 else "MEDIUM", "currency_rate", f"{ccy}|{d.isoformat()}", "D2_FX_GAP",
                    "", "rate expected", fx_decision(pos), f"position {pos} in gap")
            else:
                pos = 0
            d += td(1)
    # D3 same forecast item twice in a run
    seen = {}
    for ln in sorted(t["forecast_run_item"], key=lambda x: x["line_id"]):
        k = (ln["run_id"], ln["cf_id"])
        if k in seen:
            add("CASH_FLOW_COUNTED_TWICE", "HIGH", "forecast_run_item", ln["line_id"], "D3_DUP_LINE", ln["cf_id"],
                "unique per run", "REJECT_RUN_AND_RERUN", f"duplicate of {seen[k]}")
        else:
            seen[k] = ln["line_id"]
    # D4 actuals used after cutoff
    cutoff = {r["run_id"]: r["data_cutoff_date"] for r in t["forecast_run"]}
    led = {le["ledger_id"]: le["entry_date"] for le in t["ledger_entry"]}
    for ln in t["forecast_run_item"]:
        if ln["amount_basis"] == "ACTUAL" and led.get(ln["actual_ledger_id"], dt.date.min) > cutoff[ln["run_id"]]:
            add("FORECAST_USES_ACTUAL_AFTER_CUTOFF", "HIGH", "forecast_run_item", ln["line_id"], "D4_LOOKAHEAD",
                led[ln["actual_ledger_id"]].isoformat(), f"<= {cutoff[ln['run_id']].isoformat()}", "REJECT_RUN_AND_RERUN")
    # D5 currency differs from account currency
    for le in t["ledger_entry"]:
        if le["currency"] != acct[le["account_id"]]["currency"]:
            add("CURRENCY_MIXED_WITHOUT_CONVERSION", "HIGH", "ledger_entry", le["ledger_id"], "D5_CCY_MIX", le["currency"],
                acct[le["account_id"]]["currency"], "QUARANTINE_AND_CONVERT_AT_ENTRY_DATE_RATE")
    return out
