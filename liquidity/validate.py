"""Step 8: validation suite. Labelled anomalies are *expected* violations; anything unlabelled is a FAIL."""
from __future__ import annotations

import re
from collections import defaultdict

from . import schema as S
from .config import (DATA_CUTOFF, HISTORY_START, HORIZON_DAYS, OPENING_DATE, RECON_TOLERANCE_MINOR, SCENARIOS)
from .forecast import Ctx, build_lines, line_checksum
from .util import td

SC_COLS = ["receipt_delay_days", "payable_acceleration_days", "receivable_haircut_pct", "one_off_outflow_multiplier",
           "fx_shock_pct", "overdue_rollover_days"]


def _pk(t, r):
    return "|".join(str(r[c]) for c in t.pk)


def validate(tables, gt):
    gtk = defaultdict(set)
    for g in gt:
        gtk[g["issue_type"]].add(g["record_key"])
    res = []

    def check(cid, name, violations, expected=frozenset()):
        V, G = set(violations), set(expected)
        if V == G:
            status = "PASS" if not G else "PASS_EXPECTED_EXCEPTIONS"
        else:
            status = "FAIL"
        res.append(dict(id=cid, name=name, status=status, violations_found=len(V), labelled_expected=len(G),
                        unlabelled_violations=len(V - G), labelled_not_detected=len(G - V),
                        sample=sorted(V ^ G)[:5]))

    T = tables
    pks = {n: {_pk(S.TABLE_MAP[n], r) for r in T[n]} for n in S.TABLE_ORDER}
    # V01 primary keys
    v = []
    for n in S.TABLE_ORDER:
        t = S.TABLE_MAP[n]
        seen = set()
        for r in T[n]:
            k = _pk(t, r)
            if k in seen:
                v.append(f"{n}:{k}")
            seen.add(k)
        for u in t.unique_together:
            seen = set()
            for r in T[n]:
                k = tuple(r[c] for c in u)
                if k in seen:
                    v.append(f"{n}:uq:{k}")
                seen.add(k)
    # (run_id, cf_id) duplicates are a labelled anomaly -> handled by V15, remove here
    v = [x for x in v if not x.startswith("forecast_run_item:uq:")]
    check("V01", "primary-key and composite-uniqueness", v)
    # V02 foreign keys
    v = []
    for (tn, col, rt, rc) in S.foreign_keys():
        parent = {r[rc] for r in T[rt]}
        for r in T[tn]:
            if r[col] is not None and r[col] not in parent:
                v.append(f"{tn}.{col}:{_pk(S.TABLE_MAP[tn], r)}")
    check("V02", "foreign-key integrity (all declared FKs)", v)
    # V03 required, V04 enums, V05 id patterns
    v3, v4, v5 = [], [], []
    for n in S.TABLE_ORDER:
        t = S.TABLE_MAP[n]
        pat = re.compile(t.id_pattern)
        for r in T[n]:
            for f in t.fields:
                x = r[f.name]
                if x is None:
                    if f.required and not (n == "forecast_run_entity" and f.name in ("opening_position_usd_minor", "exclusion_reason")):
                        v3.append(f"{n}.{f.name}:{_pk(t, r)}")
                elif f.allowed and x not in f.allowed:
                    v4.append(f"{n}.{f.name}:{_pk(t, r)}")
            if not pat.match(_pk(t, r)):
                v5.append(f"{n}:{_pk(t, r)}")
    check("V03", "required fields populated", v3)
    check("V04", "allowed enum values", v4)
    check("V05", "ID format / zero-padding", v5)

    ent = {r["entity_id"]: r for r in T["legal_entity"]}
    acct = {r["account_id"]: r for r in T["bank_account"]}
    cf = {r["cf_id"]: r for r in T["cash_flow_forecast"]}
    # V06 date ordering and conditional rules
    v = []
    for e in T["legal_entity"]:
        if e["effective_from"] != e["incorporation_date"] or (e["status"] == "CLOSED") != (e["effective_to"] is not None):
            v.append(f"ent:{e['entity_id']}")
        if e["parent_entity_id"] and e["parent_entity_id"] >= e["entity_id"]:
            v.append(f"ent-parent:{e['entity_id']}")
    for a in T["bank_account"]:
        if a["opened_date"] > a["opening_balance_date"] or a["opened_date"] < ent[a["entity_id"]]["effective_from"] \
                or (a["status"] == "CLOSED") != (a["closed_date"] is not None) \
                or (a["closed_date"] and a["closed_date"] < a["opened_date"]):
            v.append(f"acct:{a['account_id']}")
    for tn, idc in (("receivable", "receivable_id"), ("payable", "payable_id")):
        for r in T[tn]:
            if not (r["invoice_date"] < r["due_date"]) or r["payment_terms_days"] != (r["due_date"] - r["invoice_date"]).days \
                    or r["due_date"].weekday() >= 5:
                v.append(f"{tn}:{r[idc]}")
    for c in T["cash_flow_forecast"]:
        if c["created_date"] >= c["expected_date"] or (c["revised_at"] is None) != (c["revised_expected_date"] is None):
            v.append(f"cf:{c['cf_id']}")
        elif c["revised_at"] and not (c["created_date"] <= c["revised_at"] < c["expected_date"] < c["revised_expected_date"]):
            v.append(f"cf-rev:{c['cf_id']}")
    for l in T["ledger_entry"]:
        if not (HISTORY_START <= l["entry_date"] <= DATA_CUTOFF) or l["entry_date"].weekday() >= 5:
            v.append(f"led:{l['ledger_id']}")
    for r in T["forecast_run"]:
        if r["data_cutoff_date"] != r["run_date"] - td(1) or r["horizon_end"] != r["run_date"] + td(HORIZON_DAYS - 1) \
                or r["horizon_start"] != r["run_date"]:
            v.append(f"run:{r['run_id']}")
        if not r["run_id"].startswith(f"FCAST-{r['run_date'].isoformat()}-"):
            v.append(f"run-id-date:{r['run_id']}")
    runs = {r["run_id"]: r for r in T["forecast_run"]}
    for ln in T["forecast_run_item"]:
        r = runs[ln["run_id"]]
        if not (r["run_date"] <= ln["effective_date"] <= r["horizon_end"]):
            v.append(f"line:{ln['line_id']}")
    check("V06", "date ordering / effective-date rules", v)
    # V07 cross-table consistency
    v = []
    for l in T["ledger_entry"]:
        if acct[l["account_id"]]["entity_id"] != l["entity_id"]:
            v.append(f"led:{l['ledger_id']}")
    for tn, idc in (("receivable", "receivable_id"), ("payable", "payable_id")):
        for r in T[tn]:
            a = acct[r["account_id"]]
            if a["entity_id"] != r["entity_id"] or a["currency"] != r["currency"]:
                v.append(f"{tn}:{r[idc]}")
    for c in T["cash_flow_forecast"]:
        a = acct[c["account_id"]]
        if a["entity_id"] != c["entity_id"] or a["currency"] != c["currency"] or ((c["receivable_id"] is None) == (c["payable_id"] is None)) \
                or (c["direction"] == "INFLOW") != (c["receivable_id"] is not None):
            v.append(f"cf:{c['cf_id']}")
    for ln in T["forecast_run_item"]:
        if cf[ln["cf_id"]]["entity_id"] != ln["entity_id"] or cf[ln["cf_id"]]["currency"] != ln["currency"] \
                or cf[ln["cf_id"]]["direction"] != ln["direction"]:
            v.append(f"line:{ln['line_id']}")
    check("V07", "parent/child attribute consistency (entity, currency, direction)", v)
    # V08 ledger arithmetic
    v = []
    run = {a: acct[a]["opening_balance_minor"] for a in acct}
    for l in sorted(T["ledger_entry"], key=lambda x: x["ledger_id"]):
        sg = l["amount_minor"] if l["direction"] == "CREDIT" else -l["amount_minor"]
        run[l["account_id"]] += sg
        if l["signed_amount_minor"] != sg or l["balance_after_minor"] != run[l["account_id"]] or l["amount_minor"] <= 0:
            v.append(l["ledger_id"])
    check("V08", "ledger sign + running-balance arithmetic", v)
    # V09 daily positions reconcile
    v = []
    prev = {}
    for p in sorted(T["daily_cash_position"], key=lambda x: (x["account_id"], x["position_date"])):
        a = p["account_id"]
        exp_open = prev.get(a, acct[a]["opening_balance_minor"])
        if p["opening_minor"] != exp_open or p["opening_minor"] + p["inflow_minor"] - p["outflow_minor"] != p["closing_minor"] \
                or p["is_overdrawn"] != (p["closing_minor"] < 0):
            v.append(p["position_id"])
        prev[a] = p["closing_minor"]
    last = {}
    for p in T["daily_cash_position"]:
        if p["account_id"] not in last or p["position_date"] > last[p["account_id"]][0]:
            last[p["account_id"]] = (p["position_date"], p["closing_minor"])
    for a, (d, c) in last.items():
        if c != run[a]:
            v.append(f"final:{a}")
    check("V09", "daily balances reconcile (open+in-out=close, chain, final=ledger)", v)
    # V10 bank statement vs ledger
    v = [a for a in acct if acct[a]["statement_closing_balance_minor"] != run[a]]
    check("V10", "opening + ledger == bank closing balance", v, gtk["BALANCE_MISMATCH"])
    # V11 currency consistency
    check("V11", "ledger currency == account currency (no mixed currency)",
          [l["ledger_id"] for l in T["ledger_entry"] if l["currency"] != acct[l["account_id"]]["currency"]],
          gtk["CURRENCY_MIXED_WITHOUT_CONVERSION"])
    # V12 FX completeness
    have = {(r["from_currency"], r["rate_date"]) for r in T["currency_rate"]}
    ds = [r["rate_date"] for r in T["currency_rate"]]
    miss = []
    for c in {r["from_currency"] for r in T["currency_rate"]} - {"USD"}:
        d = min(ds)
        while d <= max(ds):
            if (c, d) not in have:
                miss.append(f"{c}|{d.isoformat()}")
            d += td(1)
    check("V12", "FX rate present for every currency/day", miss, gtk["FX_RATE_MISSING"])
    # V13 documents / forecast items reconcile with ledger
    v = []
    by_ref = defaultdict(int)
    by_cf = defaultdict(int)
    for l in T["ledger_entry"]:
        if l["source_ref_id"]:
            by_ref[l["source_ref_id"]] += l["amount_minor"]
        if l["cf_id"]:
            by_cf[l["cf_id"]] += l["amount_minor"]
            c = cf[l["cf_id"]]
            if l["source_ref_id"] != (c["receivable_id"] or c["payable_id"]):
                v.append(f"ref:{l['ledger_id']}")
    m = {"OPEN": "SCHEDULED", "OVERDUE": "DELAYED", "PARTIALLY_PAID": "PARTIALLY_REALIZED", "PAID": "REALIZED",
         "WRITTEN_OFF": "WRITTEN_OFF", "CANCELLED": "CANCELLED"}
    doc_status = {}
    for tn, idc in (("receivable", "receivable_id"), ("payable", "payable_id")):
        for r in T[tn]:
            doc_status[r[idc]] = r["status"]
            s = by_ref.get(r[idc], 0)
            out = r["invoice_amount_minor"] - s if r["status"] in ("OPEN", "OVERDUE", "PARTIALLY_PAID") else 0
            if r["settled_amount_minor"] != s or r["outstanding_minor"] != out or (r["status"] == "PAID" and s != r["invoice_amount_minor"]) \
                    or s > r["invoice_amount_minor"]:
                v.append(f"{tn}:{r[idc]}")
    for c in T["cash_flow_forecast"]:
        did = c["receivable_id"] or c["payable_id"]
        if c["realized_amount_minor"] != by_cf.get(c["cf_id"], 0) or doc_status[did] and m[doc_status[did]] != c["status"] and \
                not (c["status"] in ("DELAYED",) and doc_status[did] == "OPEN"):
            v.append(f"cf:{c['cf_id']}")
    check("V13", "receivable/payable/CF amounts & statuses reconcile with ledger", v)
    # V14 lifecycle
    ev = defaultdict(list)
    for e in T["state_event"]:
        ev[(e["object_type"], e["object_id"])].append(e)
    cur = {}
    for tn, ot, idc in (("legal_entity", "LEGAL_ENTITY", "entity_id"), ("bank_account", "BANK_ACCOUNT", "account_id"),
                        ("receivable", "RECEIVABLE", "receivable_id"), ("payable", "PAYABLE", "payable_id"),
                        ("cash_flow_forecast", "CASH_FLOW_FORECAST", "cf_id"), ("forecast_run", "FORECAST_RUN", "run_id")):
        for r in T[tn]:
            cur[(ot, r[idc])] = r["status"]
    v = []
    for k, st in cur.items():
        es = sorted(ev.get(k, []), key=lambda x: x["sequence_no"])
        if not es:
            v.append(f"noevents:{k}")
            continue
        prev_state, prev_ts = None, None
        for n, e in enumerate(es, 1):
            ok = e["sequence_no"] == n and e["from_state"] == prev_state and \
                e["to_state"] in S.TRANSITIONS[k[0]].get(prev_state, ()) and (prev_ts is None or e["event_ts"] >= prev_ts)
            if not ok:
                v.append(f"{k}:{n}")
                break
            prev_state, prev_ts = e["to_state"], e["event_ts"]
        if prev_state != st:
            v.append(f"final:{k}")
    for k in ev:
        if k not in cur:
            v.append(f"orphan-events:{k}")
    check("V14", "lifecycle transitions, event chain, final state == current status", v)
    # V15 duplicates
    seen, dup = {}, []
    for ln in sorted(T["forecast_run_item"], key=lambda x: x["line_id"]):
        k = (ln["run_id"], ln["cf_id"])
        if k in seen:
            dup.append(ln["line_id"])
        seen[k] = 1
    check("V15", "duplicate forecast lines per (run, item)", dup, gtk["CASH_FLOW_COUNTED_TWICE"])
    nat, dd = set(), []
    for l in T["ledger_entry"]:
        if l["cf_id"]:
            k = (l["cf_id"], l["entry_date"], l["amount_minor"])
            if k in nat:
                dd.append(l["ledger_id"])
            nat.add(k)
    check("V16", "duplicate settlement postings (cf_id, date, amount)", dd)
    # V17 look-ahead
    cut = {r["run_id"]: r["data_cutoff_date"] for r in T["forecast_run"]}
    led = {l["ledger_id"]: l["entry_date"] for l in T["ledger_entry"]}
    v = [ln["line_id"] for ln in T["forecast_run_item"]
         if ln["amount_basis"] == "ACTUAL" and led[ln["actual_ledger_id"]] > cut[ln["run_id"]]]
    v += [f"basis:{ln['line_id']}" for ln in T["forecast_run_item"] if (ln["amount_basis"] == "ACTUAL") != (ln["actual_ledger_id"] is not None)]
    check("V17", "no actuals used after run cutoff", v, gtk["FORECAST_USES_ACTUAL_AFTER_CUTOFF"])
    # V18 scenarios documented / differ only by assumptions
    v = []
    asm = defaultdict(dict)
    for a in T["scenario_assumption"]:
        asm[a["scenario_id"]][a["parameter_name"]] = a["parameter_value"]
    for s in T["liquidity_scenario"]:
        for c in SC_COLS:
            if abs(asm[s["scenario_id"]].get(c, 1e9) - float(s[c])) > 1e-9:
                v.append(f"{s['scenario_id']}.{c}")
    ref = {s["scenario_id"]: s for s in SCENARIOS}
    for s in T["liquidity_scenario"]:
        if any(s[c] != ref[s["scenario_id"]][c] for c in SC_COLS):
            v.append(f"cfg:{s['scenario_id']}")
    check("V18", "scenario table == scenario_assumption rows == documented config", v)
    # V19 scenario fidelity: lines recomputed from rule + scenario parameters
    ctx = Ctx(T)
    lines_by = defaultdict(list)
    for ln in T["forecast_run_item"]:
        lines_by[ln["run_id"]].append(ln)
    v = []
    for r in T["forecast_run"]:
        spec = dict(run_id=r["run_id"], run_date=r["run_date"], scenario_id=r["scenario_id"])
        exp = {l["cf_id"]: l for l in build_lines(ctx, spec)}
        got = {}
        actual_cf = {l["cf_id"] for l in lines_by[r["run_id"]] if l["amount_basis"] == "ACTUAL"}
        for l in sorted(lines_by[r["run_id"]], key=lambda x: x["line_id"]):
            if l["amount_basis"] == "SCHEDULED" and l["cf_id"] not in got:
                got[l["cf_id"]] = l
        for k in set(exp) | set(got) | actual_cf:
            if k in actual_cf and k in exp:
                continue
            e_, g_ = exp.get(k), got.get(k)
            if e_ is None or g_ is None or any(e_[f] != g_[f] for f in (
                    "base_date", "effective_date", "scheduled_amount_minor", "adjusted_amount_minor", "fx_rate_to_usd",
                    "adjusted_amount_usd_minor")):
                v.append(f"{r['run_id']}|{k}")
    check("V19", "scenarios differ only by documented assumptions (lines recomputed independently)", v)
    # V20 run aggregates + checksum + reproducible
    v = []
    fdp = defaultdict(list)
    for p in T["forecast_daily_position"]:
        fdp[p["run_id"]].append(p)
    br = defaultdict(list)
    for b in T["forecast_run_entity"]:
        br[b["run_id"]].append(b)
    for r in T["forecast_run"]:
        L = lines_by[r["run_id"]]
        inc = [b for b in br[r["run_id"]] if b["included"]]
        byday = defaultdict(int)
        for p in fdp[r["run_id"]]:
            byday[p["position_date"]] += p["projected_closing_usd_minor"]
        bad = (r["line_count"] != len(L) or r["entities_in_scope"] != len(inc) or
               r["total_inflow_usd_minor"] != sum(l["adjusted_amount_usd_minor"] for l in L if l["direction"] == "INFLOW") or
               r["total_outflow_usd_minor"] != sum(l["adjusted_amount_usd_minor"] for l in L if l["direction"] == "OUTFLOW") or
               r["closing_position_usd_minor"] != byday[r["horizon_end"]] or r["min_position_usd_minor"] != min(byday.values()) or
               r["input_checksum"] != line_checksum(L) or len(fdp[r["run_id"]]) != len(inc) * HORIZON_DAYS or
               r["opening_position_usd_minor"] != sum(b["opening_position_usd_minor"] for b in inc))
        if bad:
            v.append(r["run_id"])
    check("V20", "run aggregates / checksum recompute from lines and projections", v)
    # V21 variance decomposition
    v = []
    for c in T["forecast_vs_actual"]:
        eff = sum(c[k] for k in ("timing_effect_usd_minor", "amount_effect_usd_minor", "unscheduled_flow_effect_usd_minor",
                                 "fx_effect_usd_minor", "double_count_effect_usd_minor"))
        if c["variance_usd_minor"] != c["actual_closing_usd_minor"] - c["forecast_closing_usd_minor"] or \
                c["rounding_residual_usd_minor"] != c["variance_usd_minor"] - eff or \
                abs(c["rounding_residual_usd_minor"]) > RECON_TOLERANCE_MINOR or c["explanation_status"] != "EXPLAINED" or \
                c["comparison_date"] > DATA_CUTOFF:
            v.append(c["comparison_id"])
    check("V21", "actual-vs-forecast variance fully explained by drivers (|residual|<=5 minor)", v)
    # V22 ground-truth integrity and separation
    v = []
    tbl_keys = {"ledger_entry": pks["ledger_entry"], "bank_account": pks["bank_account"],
                "forecast_run_item": pks["forecast_run_item"]}
    for g in gt:
        if g["table_name"] in tbl_keys and g["record_key"] not in tbl_keys[g["table_name"]]:
            v.append(g["anomaly_id"])
        if g["issue_type"] == "FX_RATE_MISSING" and g["record_key"].replace("|", "") and g["related_keys"] in pks["currency_rate"]:
            v.append(g["anomaly_id"])
    leak_cols = [f"{n}.{f.name}" for n in S.TABLE_ORDER for f in S.TABLE_MAP[n].fields
                 if re.search(r"ground_truth|issue_type|anomaly|label", f.name)]
    check("V22", "ground truth refers to real rows & is not leaked into input columns", v + leak_cols)
    summ = dict(total_checks=len(res), passed=sum(r["status"] == "PASS" for r in res),
                passed_with_expected_exceptions=sum(r["status"] == "PASS_EXPECTED_EXCEPTIONS" for r in res),
                failed=sum(r["status"] == "FAIL" for r in res), ground_truth_rows=len(gt),
                row_counts={k: len(v_) for k, v_ in T.items()})
    return dict(summary=summ, checks=res)
