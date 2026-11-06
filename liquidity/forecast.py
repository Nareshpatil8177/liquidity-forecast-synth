"""Derived forecasting layer. Works ONLY from table rows (same inputs the validator sees).

Method (documented in docs/GENERATION_LOGIC.md):
  projected(entity, day d) = sum_ccy plan_rate(ccy) x ( balance_at_cutoff
                              + cumulative scenario-adjusted scheduled flows (effective_date <= d)
                              + run_rate_daily x days_since_cutoff )
"""
from __future__ import annotations

import datetime as dt
import hashlib
from collections import defaultdict
from typing import Dict, List

from . import ids
from .config import (COMPARISON_STEP_DAYS, CURRENCIES, DATA_CUTOFF, HORIZON_DAYS, OPENING_DATE, RECON_TOLERANCE_MINOR,
                     RUN_DATES)
from .rules import FxIndex, apply_scenario
from .util import td


class Ctx:
    """Indexed view of the tables used by every derived computation."""

    def __init__(self, t: Dict[str, list]):
        self.t = t
        self.ent = {r["entity_id"]: r for r in t["legal_entity"]}
        self.acct = {r["account_id"]: r for r in t["bank_account"]}
        self.cf_list = sorted(t["cash_flow_forecast"], key=lambda r: r["cf_id"])
        self.sc = {r["scenario_id"]: r for r in t["liquidity_scenario"]}
        self.fx = FxIndex(t["currency_rate"])
        self.N = (DATA_CUTOFF - OPENING_DATE).days + 1
        self.pays = defaultdict(list)                       # cf_id -> [(date, amount, ledger_id)]
        net = defaultdict(lambda: [0] * self.N)
        ops = defaultdict(lambda: [0] * self.N)
        self.flows = defaultdict(lambda: [[0, 0, 0] for _ in range(0)])
        self._in = defaultdict(int)
        self._out = defaultdict(int)
        self._cnt = defaultdict(int)
        for le in t["ledger_entry"]:
            idx = (le["entry_date"] - OPENING_DATE).days
            a = le["account_id"]
            acc = self.acct[a]
            net[a][idx] += le["signed_amount_minor"]
            if le["direction"] == "CREDIT":
                self._in[(a, idx)] += le["amount_minor"]
            else:
                self._out[(a, idx)] += le["amount_minor"]
            self._cnt[(a, idx)] += 1
            if le["cf_id"]:
                self.pays[le["cf_id"]].append((le["entry_date"], le["amount_minor"], le["ledger_id"]))
            elif le["entry_type"] != "ACCOUNT_CLOSURE_SWEEP":
                ops[(acc["entity_id"], acc["currency"])][idx] += le["signed_amount_minor"]
        self.acct_close = {}
        for aid, acc in self.acct.items():
            c = [acc["opening_balance_minor"]]
            n = net[aid] if aid in net else [0] * self.N
            for i in range(1, self.N):
                c.append(c[-1] + n[i])
            self.acct_close[aid] = c
        self.ent_ccys = defaultdict(list)
        self.ent_close = {}
        for aid, acc in sorted(self.acct.items()):
            key = (acc["entity_id"], acc["currency"])
            if acc["currency"] not in self.ent_ccys[acc["entity_id"]]:
                self.ent_ccys[acc["entity_id"]].append(acc["currency"])
            cur = self.ent_close.setdefault(key, [0] * self.N)
            for i, v in enumerate(self.acct_close[aid]):
                cur[i] += v
        for e in self.ent_ccys:
            self.ent_ccys[e].sort(key=CURRENCIES.index)
        self.ops_prefix = {}
        for key, arr in ops.items():
            p, s = [], 0
            for v in arr:
                s += v
                p.append(s)
            self.ops_prefix[key] = p

    # ------------------------------------------------------------------
    def in_scope(self, e: dict, C: dt.date):
        if e["status"] == "CLOSED" and C >= e["effective_to"]:
            return False, "ENTITY_CLOSED"
        if e["status"] == "DORMANT" and C >= e["status_since"]:
            return False, "ENTITY_DORMANT"
        return True, None

    def run_rate(self, e: str, ccy: str, idxC: int) -> float:
        """Trailing mean daily net of UNSCHEDULED operating flows over up to 90 days of 2026 history."""
        L = min(90, idxC)
        p = self.ops_prefix.get((e, ccy))
        if L <= 0 or p is None:
            return 0.0
        return (p[idxC] - p[idxC - L]) / L

    def plan_rates(self, C: dt.date, sc: dict):
        out = {}
        for ccy in CURRENCIES:
            r, rd, st = self.fx.lookup(ccy, C)
            if r is None:
                out[ccy] = (None, st)
            else:
                out[ccy] = (1.0 if ccy == "USD" else round(r * (1.0 + sc["fx_shock_pct"]), 8), st)
        return out


# ============================================================================ run specification
def run_specs(scenarios, rerun_targets):
    """Run list: monthly dates x scenarios (seq 001..003) plus re-runs (seq 004) of rejected runs."""
    specs = []
    for d in RUN_DATES:
        for i, sc in enumerate(scenarios, 1):
            specs.append(dict(run_id=ids.run_id(d, i), run_date=d, scenario_id=sc["scenario_id"], run_version=1,
                              supersedes_run_id=None))
    for rid in rerun_targets:
        base = next(s for s in specs if s["run_id"] == rid)
        specs.append(dict(run_id=ids.run_id(base["run_date"], 4), run_date=base["run_date"],
                          scenario_id=base["scenario_id"], run_version=2, supersedes_run_id=rid))
    specs.sort(key=lambda s: s["run_id"])
    return specs


# ============================================================================ lines
def build_lines(ctx: Ctx, spec: dict) -> List[dict]:
    R = spec["run_date"]
    C = R - td(1)
    hend = R + td(HORIZON_DAYS - 1)
    sc = ctx.sc[spec["scenario_id"]]
    plan = ctx.plan_rates(C, sc)
    out = []
    for cf in ctx.cf_list:
        ent = ctx.ent[cf["entity_id"]]
        if not ctx.in_scope(ent, C)[0] or cf["created_date"] > C:
            continue
        if cf["terminal_date"] is not None and cf["terminal_date"] <= C:
            continue
        paid = sum(a for (d, a, _) in ctx.pays.get(cf["cf_id"], ()) if d <= C)
        rem = cf["scheduled_amount_minor"] - paid
        if rem <= 0:
            continue
        known = cf["revised_expected_date"] if (cf["revised_at"] and cf["revised_at"] <= C) else cf["expected_date"]
        eff, adj = apply_scenario(sc, cf["direction"], cf["is_large_one_off"], known, R, rem)
        if eff > hend:
            continue
        rate = plan[cf["currency"]][0]
        out.append(dict(line_id=None, run_id=spec["run_id"], cf_id=cf["cf_id"], entity_id=cf["entity_id"],
                        base_date=known, effective_date=eff, scheduled_amount_minor=rem, adjusted_amount_minor=adj,
                        currency=cf["currency"], direction=cf["direction"], fx_rate_to_usd=rate,
                        adjusted_amount_usd_minor=int(round(adj * rate)), amount_basis="SCHEDULED", actual_ledger_id=None))
    return out


def line_checksum(lines) -> str:
    h = hashlib.sha256()
    for ln in sorted(lines, key=lambda x: x["line_id"]):
        h.update(("|".join(str(ln[k]) for k in ("cf_id", "base_date", "effective_date", "scheduled_amount_minor",
                                                 "adjusted_amount_minor", "fx_rate_to_usd", "amount_basis",
                                                 "actual_ledger_id")) + "\n").encode())
    return h.hexdigest()


# ============================================================================ run-level checks (no ground truth!)
def run_checks(ctx: Ctx, spec: dict, lines: List[dict], plan) -> dict:
    C = spec["run_date"] - td(1)
    seen, dup = set(), 0
    leak = 0
    led_date = {le["ledger_id"]: le["entry_date"] for le in ctx.t["ledger_entry"]} if any(
        ln["actual_ledger_id"] for ln in lines) else {}
    for ln in sorted(lines, key=lambda x: x["line_id"]):
        if ln["cf_id"] in seen:
            dup += 1
        seen.add(ln["cf_id"])
        if ln["amount_basis"] == "ACTUAL" and led_date.get(ln["actual_ledger_id"], dt.date.min) > C:
            leak += 1
    used = {c for e in ctx.ent_ccys for c in ctx.ent_ccys[e]} - {"USD"}
    stale = sum(1 for c in used if plan[c][1] == "STALE_CARRY")
    n = dup + leak + stale
    if dup or leak:
        decision = "REJECTED"
    elif stale:
        decision = "APPROVED_WITH_EXCEPTIONS"
    else:
        decision = "APPROVED"
    return dict(dup=dup, leak=leak, stale=stale, exception_count=n, decision=decision,
                fx_status="STALE_CARRY" if stale else "OK")


# ============================================================================ positions
def run_positions(ctx: Ctx, spec: dict, lines: List[dict], plan):
    R = spec["run_date"]
    C = R - td(1)
    idxC = (C - OPENING_DATE).days
    H = HORIZON_DAYS
    net = defaultdict(lambda: [0] * H)
    for ln in lines:
        k = (ln["effective_date"] - R).days
        net[(ln["entity_id"], ln["currency"])][k] += ln["adjusted_amount_minor"] if ln["direction"] == "INFLOW" else -ln["adjusted_amount_minor"]
    scope, excl = [], []
    for e in sorted(ctx.ent):
        ok, why = ctx.in_scope(ctx.ent[e], C)
        (scope if ok else excl).append((e, why))
    fdp, ent_rows, opening_tot = [], [], 0
    for e, _ in scope:
        series = [0.0] * H
        opening = 0.0
        for ccy in ctx.ent_ccys[e]:
            rate = plan[ccy][0]
            bal0 = ctx.ent_close[(e, ccy)][idxC]
            rr = ctx.run_rate(e, ccy, idxC)
            cum = 0
            arr = net.get((e, ccy), [0] * H)
            opening += rate * bal0
            for k in range(H):
                cum += arr[k]
                series[k] += rate * (bal0 + cum + rr * (k + 1))
        buf = ctx.ent[e]["min_liquidity_buffer_usd_minor"]
        for k in range(H):
            v = int(round(series[k]))
            fdp.append(dict(fdp_id=None, run_id=spec["run_id"], entity_id=e, position_date=R + td(k),
                            projected_closing_usd_minor=v, buffer_usd_minor=buf, below_buffer=v < buf,
                            shortfall_usd_minor=max(0, buf - v)))
        ent_rows.append(dict(run_id=spec["run_id"], entity_id=e, included=True, exclusion_reason=None,
                             opening_position_usd_minor=int(round(opening))))
        opening_tot += int(round(opening))
    for e, why in excl:
        ent_rows.append(dict(run_id=spec["run_id"], entity_id=e, included=False, exclusion_reason=why,
                             opening_position_usd_minor=None))
    return fdp, ent_rows, opening_tot, len(scope)


def run_metrics(spec, lines, fdp, opening_tot, n_scope, checks, checksum, status):
    R = spec["run_date"]
    byday = defaultdict(int)
    breach_ents, breach_days = set(), 0
    for r in fdp:
        byday[r["position_date"]] += r["projected_closing_usd_minor"]
        if r["below_buffer"]:
            breach_ents.add(r["entity_id"])
            breach_days += 1
    mn_date = min(byday, key=lambda d: (byday[d], d)) if byday else R
    inflow = sum(l["adjusted_amount_usd_minor"] for l in lines if l["direction"] == "INFLOW")
    outflow = sum(l["adjusted_amount_usd_minor"] for l in lines if l["direction"] == "OUTFLOW")
    return dict(run_id=spec["run_id"], run_date=R, data_cutoff_date=R - td(1), horizon_start=R,
                horizon_end=R + td(HORIZON_DAYS - 1), scenario_id=spec["scenario_id"], run_version=spec["run_version"],
                supersedes_run_id=spec["supersedes_run_id"], status=status,
                created_by_role="OPERATIONS_ANALYST", line_count=len(lines), entities_in_scope=n_scope,
                opening_position_usd_minor=opening_tot, total_inflow_usd_minor=inflow, total_outflow_usd_minor=outflow,
                closing_position_usd_minor=byday[R + td(HORIZON_DAYS - 1)] if byday else 0,
                min_position_usd_minor=byday[mn_date] if byday else 0, min_position_date=mn_date,
                entities_breaching_buffer=len(breach_ents), breach_entity_days=breach_days,
                fx_status=checks["fx_status"], exception_count=checks["exception_count"],
                review_decision=checks["decision"], input_checksum=checksum)


# ============================================================================ run lifecycle events
def run_events(spec, checks, superseded_by_ts):
    R = spec["run_date"]
    D = dt.datetime
    ev = []

    def add(n, fr, to, h, m, actor, reason, day=None):
        ev.append(dict(object_type="FORECAST_RUN", object_id=spec["run_id"], sequence_no=n, from_state=fr, to_state=to,
                       event_ts=D.combine(day or R, dt.time(h, m)), actor_role=actor, reason_code=reason))

    base_h = 13 if spec["run_version"] > 1 else 7
    add(1, None, "CREATED", base_h, 0, "OPERATIONS_ANALYST", "RUN_REQUESTED" if spec["run_version"] == 1 else "RERUN_AFTER_REJECTION")
    add(2, "CREATED", "CALCULATED", base_h, 10, "SYSTEM", "CALCULATION_COMPLETE")
    n, state = 2, "CALCULATED"
    rev_h = 15 if spec["run_version"] > 1 else 10
    if checks["exception_count"]:
        add(3, "CALCULATED", "EXCEPTIONS_FLAGGED", base_h, 11, "SYSTEM", "RUN_CHECKS_FAILED")
        n, state = 3, "EXCEPTIONS_FLAGGED"
    if checks["decision"] == "REJECTED":
        add(n + 1, state, "REJECTED", rev_h, 0, "RISK_COMPLIANCE_REVIEWER", "DOUBLE_COUNT_OR_LOOKAHEAD")
        n, state = n + 1, "REJECTED"
    else:
        add(n + 1, state, "APPROVED", rev_h, 0, "RISK_COMPLIANCE_REVIEWER",
            "APPROVED_WITH_EXCEPTIONS" if checks["exception_count"] else "APPROVED")
        n, state = n + 1, "APPROVED"
    if superseded_by_ts is not None:
        add(n + 1, state, "SUPERSEDED", superseded_by_ts[0], superseded_by_ts[1], "SYSTEM", "NEWER_VERSION_APPROVED")
        state = "SUPERSEDED"
    return ev, state


# ============================================================================ daily cash positions (actuals)
def daily_positions(ctx: Ctx):
    rows = []
    for aid in sorted(ctx.acct):
        acc = ctx.acct[aid]
        end = acc["closed_date"] if acc["closed_date"] else DATA_CUTOFF
        endi = (end - OPENING_DATE).days
        cl = ctx.acct_close[aid]
        for i in range(1, endi + 1):
            d = OPENING_DATE + td(i)
            rate, rd, st = ctx.fx.lookup(acc["currency"], d)
            rows.append(dict(position_id=None, account_id=aid, entity_id=acc["entity_id"], position_date=d,
                             currency=acc["currency"], opening_minor=cl[i - 1], inflow_minor=ctx._in.get((aid, i), 0),
                             outflow_minor=ctx._out.get((aid, i), 0), closing_minor=cl[i],
                             entry_count=ctx._cnt.get((aid, i), 0), fx_rate_to_usd=rate, fx_rate_date=rd, fx_status=st,
                             closing_usd_minor=int(round(cl[i] * rate)) if rate is not None else None,
                             is_overdrawn=cl[i] < 0))
    rows.sort(key=lambda r: (r["position_date"], r["account_id"]))
    for n, r in enumerate(rows, 1):
        r["position_id"] = ids.position_id(n)
    return rows


# ============================================================================ actual vs forecast
def comparisons(ctx: Ctx, spec: dict, lines: List[dict], fdp_map, plan, scope_entities):
    """Additive variance decomposition per (run, entity, weekly checkpoint).

    variance = actual_usd - forecast_usd
             = plan_rate x (timing + amount + unscheduled + double_count)   [local effects]
             + sum (actual_rate - plan_rate) x actual_local_balance          [fx effect]
    """
    R, C = spec["run_date"], spec["run_date"] - td(1)
    idxC = (C - OPENING_DATE).days
    seen = set()
    grouped = defaultdict(list)
    for ln in sorted(lines, key=lambda x: x["line_id"]):
        dup = ln["cf_id"] in seen
        seen.add(ln["cf_id"])
        sign = 1 if ln["direction"] == "INFLOW" else -1
        pays = [] if dup else [(d, sign * a) for (d, a, _) in ctx.pays.get(ln["cf_id"], ()) if d > C]
        grouped[(ln["entity_id"], ln["currency"])].append((ln["effective_date"], sign * ln["adjusted_amount_minor"], dup, pays))
    cps = [R + td(k - 1) for k in range(COMPARISON_STEP_DAYS, HORIZON_DAYS + 1, COMPARISON_STEP_DAYS)]
    cps = [d for d in cps if d <= DATA_CUTOFF]
    rows = []
    for e in scope_entities:
        for d in cps:
            idx = (d - OPENING_DATE).days
            k = (d - C).days
            comp = defaultdict(float)
            A = 0.0
            ok = True
            for ccy in ctx.ent_ccys[e]:
                fp = plan[ccy][0]
                fd, _, st = ctx.fx.lookup(ccy, d)
                if fd is None:
                    ok = False
                    break
                LA = ctx.ent_close[(e, ccy)][idx]
                bal0 = ctx.ent_close[(e, ccy)][idxC]
                timing = amount = dupe = act_nd = 0
                for (eff, s, dup, pays) in grouped.get((e, ccy), ()):
                    if dup:
                        if eff <= d:
                            dupe -= s
                        continue
                    a_d = sum(a for (pd, a) in pays if pd <= d)
                    t1 = pays[0][0] if pays else None
                    settled = 1 if (t1 is not None and t1 <= d) else 0
                    amount += a_d - s * settled
                    timing += s * (settled - (1 if eff <= d else 0))
                    act_nd += a_d
                unsched = (LA - bal0) - act_nd - ctx.run_rate(e, ccy, idxC) * k
                comp["timing"] += fp * timing
                comp["amount"] += fp * amount
                comp["unsched"] += fp * unsched
                comp["double"] += fp * dupe
                comp["fx"] += (fd - fp) * LA
                A += fd * LA
            if not ok:
                continue
            F = fdp_map[(e, d)]
            A_i = int(round(A))
            var = A_i - F
            t_, a_, u_, f_, x_ = (int(round(comp[k_])) for k_ in ("timing", "amount", "unsched", "fx", "double"))
            resid = var - (t_ + a_ + u_ + f_ + x_)
            effects = {"TIMING": t_, "AMOUNT": a_, "UNSCHEDULED_FLOWS": u_, "FX": f_, "DOUBLE_COUNT": x_}
            drv = max(effects, key=lambda n: abs(effects[n]))
            if abs(effects[drv]) == 0:
                drv = "NONE"
            rows.append(dict(comparison_id=None, run_id=spec["run_id"], entity_id=e, comparison_date=d, horizon_day=k,
                             forecast_closing_usd_minor=F, actual_closing_usd_minor=A_i, variance_usd_minor=var,
                             variance_pct=round(var / abs(F), 6) if F else None, timing_effect_usd_minor=t_,
                             amount_effect_usd_minor=a_, unscheduled_flow_effect_usd_minor=u_, fx_effect_usd_minor=f_,
                             double_count_effect_usd_minor=x_, rounding_residual_usd_minor=resid, primary_driver=drv,
                             explanation_status="EXPLAINED" if abs(resid) <= RECON_TOLERANCE_MINOR else "UNEXPLAINED"))
    return rows
