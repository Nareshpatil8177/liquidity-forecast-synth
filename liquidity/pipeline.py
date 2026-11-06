"""Orchestrates the full end-to-end workflow (baseline -> inject -> derive -> ground truth)."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import ids
from .config import DATA_CUTOFF, Scale
from .forecast import (Ctx, build_lines, comparisons, daily_positions, line_checksum, run_checks, run_events,
                       run_metrics, run_positions, run_specs)
from .generate import build_baseline
from .inject import DUP_RUN, LEAK_RUN, inject_lines, inject_pre_forecast
from .util import td


def generate_tables(scale: Scale, seed: int):
    t = build_baseline(scale, seed)                       # 1. valid baseline
    gt = []
    inject_pre_forecast(t, seed, scale, gt)               # 2. labelled edge cases (FX, currency, balance)
    ctx = Ctx(t)                                          # 3. derived layer from post-injection tables
    specs = run_specs(t["liquidity_scenario"], [DUP_RUN, LEAK_RUN])
    lines_by_run, counter = {}, [0]
    for sp in specs:
        ls = build_lines(ctx, sp)
        for ln in ls:
            counter[0] += 1
            ln["line_id"] = ids.run_item_id(counter[0])
        lines_by_run[sp["run_id"]] = ls
    inject_lines(ctx, lines_by_run, specs, counter, gt, seed, scale)    # 4. forecast-side anomalies

    superseded = {sp["supersedes_run_id"]: (15, 1) for sp in specs if sp["supersedes_run_id"]}
    runs, bridge_e, fdp_all, cmp_all, ev, lines_all = [], [], [], [], [], []
    for sp in specs:
        lines = lines_by_run[sp["run_id"]]
        plan = ctx.plan_rates(sp["run_date"] - td(1), ctx.sc[sp["scenario_id"]])
        checks = run_checks(ctx, sp, lines, plan)
        fdp, ent_rows, opening, n_scope = run_positions(ctx, sp, lines, plan)
        evs, status = run_events(sp, checks, superseded.get(sp["run_id"]))
        runs.append(run_metrics(sp, lines, fdp, opening, n_scope, checks, line_checksum(lines), status))
        bridge_e += ent_rows
        fdp_all += fdp
        ev += evs
        lines_all += lines
        fmap = {(r["entity_id"], r["position_date"]): r["projected_closing_usd_minor"] for r in fdp}
        scope = [r["entity_id"] for r in ent_rows if r["included"]]
        cmp_all += comparisons(ctx, sp, lines, fmap, plan, scope)
    for n, r in enumerate(fdp_all, 1):
        r["fdp_id"] = ids.fdp_id(n)
    for n, r in enumerate(cmp_all, 1):
        r["comparison_id"] = ids.comparison_id(n)
    t["forecast_run"], t["forecast_run_entity"] = runs, bridge_e
    t["forecast_run_item"], t["forecast_daily_position"], t["forecast_vs_actual"] = lines_all, fdp_all, cmp_all
    t["daily_cash_position"] = daily_positions(ctx)
    t["state_event"] = t["state_event"] + ev
    t["state_event"].sort(key=lambda e: (e["event_ts"], e["object_type"], e["object_id"], e["sequence_no"]))
    for n, e in enumerate(t["state_event"], 1):
        e["event_id"] = ids.event_id(n)
    return t, gt, run_decisions(t, gt)


def run_decisions(t, gt):
    """Ground-truth expected decision per run, derived from the labelled anomalies and the documented rule."""
    bad, stale = set(), defaultdict(list)
    for g in gt:
        if g["issue_type"] in ("CASH_FLOW_COUNTED_TWICE", "FORECAST_USES_ACTUAL_AFTER_CUTOFF"):
            bad.add(g["related_keys"].split("|")[0])
        elif g["issue_type"] == "FX_RATE_MISSING":
            c, d = g["record_key"].split("|")
            stale[dt.date.fromisoformat(d)].append(c)
    out = []
    for r in t["forecast_run"]:
        C = r["data_cutoff_date"]
        if r["run_id"] in bad:
            dec, why = "REJECTED", "labelled double count / look-ahead lines present"
        elif stale.get(C):
            dec, why = "APPROVED_WITH_EXCEPTIONS", "FX rate missing on cutoff day for " + ",".join(sorted(stale[C]))
        else:
            dec, why = "APPROVED", "no labelled anomaly affects this run"
        out.append(dict(run_id=r["run_id"], expected_review_decision=dec, reason=why))
    return out
