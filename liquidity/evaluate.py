"""Measurable outputs: detector quality vs ground truth, forecast accuracy, breach alerts, decision accuracy."""
from __future__ import annotations

from collections import Counter, defaultdict

from .config import DATA_CUTOFF
from .detect import detect_all


def evaluate(T, gt, run_dec):
    det = detect_all(T)
    G = {(g["issue_type"], g["record_key"]): g for g in gt}
    D = {(d["issue_type"], d["record_key"]): d for d in det}
    per = {}
    for it in sorted({k[0] for k in G} | {k[0] for k in D}):
        g = {k for k in G if k[0] == it}
        d = {k for k in D if k[0] == it}
        tp, fp, fn = len(g & d), len(d - g), len(g - d)
        dec_ok = sum(1 for k in g & d if D[k]["recommended_decision"] == G[k]["expected_decision"])
        per[it] = dict(labelled=len(g), detected=len(d), true_positive=tp, false_positive=fp, false_negative=fn,
                       precision=round(tp / (tp + fp), 4) if tp + fp else None,
                       recall=round(tp / (tp + fn), 4) if tp + fn else None,
                       decision_accuracy=round(dec_ok / tp, 4) if tp else None)
    TP = sum(p["true_positive"] for p in per.values())
    FP = sum(p["false_positive"] for p in per.values())
    FN = sum(p["false_negative"] for p in per.values())
    overall = dict(precision=round(TP / (TP + FP), 4) if TP + FP else None, recall=round(TP / (TP + FN), 4) if TP + FN else None)

    # forecast accuracy on current (not rejected / superseded) runs
    runs = {r["run_id"]: r for r in T["forecast_run"]}
    cur = {k for k, r in runs.items() if r["status"] == "APPROVED"}
    acc = defaultdict(lambda: [0, 0, 0, 0])
    for c in T["forecast_vs_actual"]:
        if c["run_id"] not in cur:
            continue
        b = "d1-14" if c["horizon_day"] <= 14 else "d15-45" if c["horizon_day"] <= 45 else "d46-91"
        a = acc[(runs[c["run_id"]]["scenario_id"], b)]
        a[0] += abs(c["variance_usd_minor"])
        a[1] += abs(c["actual_closing_usd_minor"])
        a[2] += c["variance_usd_minor"]
        a[3] += 1
    forecast_acc = {f"{s}|{b}": dict(rows=v[3], wape=round(v[0] / v[1], 4) if v[1] else None,
                                       bias_pct=round(v[2] / v[1], 4) if v[1] else None) for (s, b), v in sorted(acc.items())}
    drv = Counter()
    for c in T["forecast_vs_actual"]:
        drv[c["primary_driver"]] += 1
    # breach alert precision / recall
    buf = {e["entity_id"]: e["min_liquidity_buffer_usd_minor"] for e in T["legal_entity"]}
    act = defaultdict(lambda: defaultdict(int))
    miss = set()
    for p in T["daily_cash_position"]:
        if p["closing_usd_minor"] is None:
            miss.add((p["entity_id"], p["position_date"]))
        else:
            act[p["entity_id"]][p["position_date"]] += p["closing_usd_minor"]
    fd = defaultdict(list)
    for p in T["forecast_daily_position"]:
        if p["run_id"] in cur and p["position_date"] <= DATA_CUTOFF:
            fd[(p["run_id"], p["entity_id"])].append(p)
    conf = defaultdict(lambda: Counter())
    for (rid, e), ps in fd.items():
        pred = any(p["below_buffer"] for p in ps)
        actual = any(act[e].get(p["position_date"], buf[e]) < buf[e] and (e, p["position_date"]) not in miss for p in ps)
        conf[runs[rid]["scenario_id"]][("TP" if pred and actual else "FP" if pred else "FN" if actual else "TN")] += 1
    breach = {}
    for s, c in sorted(conf.items()):
        breach[s] = dict(c, precision=round(c["TP"] / (c["TP"] + c["FP"]), 4) if c["TP"] + c["FP"] else None,
                         recall=round(c["TP"] / (c["TP"] + c["FN"]), 4) if c["TP"] + c["FN"] else None)
    gd = {r["run_id"]: r["expected_review_decision"] for r in run_dec}
    dec_ok = sum(1 for r in T["forecast_run"] if gd[r["run_id"]] == r["review_decision"])
    pos = T["daily_cash_position"]
    cov = dict(
        accounts_by_currency=dict(Counter(a["currency"] for a in T["bank_account"])),
        forecast_items_by_currency=dict(Counter(c["currency"] for c in T["cash_flow_forecast"])),
        receivable_status=dict(Counter(r["status"] for r in T["receivable"])),
        payable_status=dict(Counter(r["status"] for r in T["payable"])),
        runs_by_status=dict(Counter(r["status"] for r in T["forecast_run"])),
        large_one_off_payables=sum(1 for p in T["payable"] if p["is_large_one_off"]),
        delayed_receivables_paid_late=sum(1 for r in T["receivable"] if r["last_payment_date"] and r["last_payment_date"] > r["due_date"]),
        overdrawn_account_days=sum(1 for p in pos if p["is_overdrawn"]),
        account_days_fx_status=dict(Counter(p["fx_status"] for p in pos)))
    last = max(r["run_date"] for r in T["forecast_run"])
    latest = {r["scenario_id"]: dict(run_id=r["run_id"], min_position_usd_minor=r["min_position_usd_minor"],
                                     min_position_date=r["min_position_date"].isoformat(),
                                     entities_breaching_buffer=r["entities_breaching_buffer"],
                                     breach_entity_days=r["breach_entity_days"])
              for r in T["forecast_run"] if r["run_date"] == last and r["status"] == "APPROVED"}
    return dict(
        latest_run_outlook_by_scenario=latest,
        detection=dict(per_issue_type=per, overall=overall, detected_total=len(det)),
        run_decision_accuracy=round(dec_ok / len(T["forecast_run"]), 4),
        forecast_accuracy_wape_by_scenario_and_horizon=forecast_acc,
        variance_primary_driver_counts=dict(drv),
        breach_alert_quality_by_scenario=breach,
        variance_explained_pct=round(100.0 * sum(c["explanation_status"] == "EXPLAINED" for c in T["forecast_vs_actual"])
                                     / max(1, len(T["forecast_vs_actual"])), 2),
        coverage=cov), det
