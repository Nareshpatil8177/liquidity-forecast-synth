import json
import os
import re
import sqlite3
from collections import Counter

from liquidity import schema as S
from liquidity.cli import build
from liquidity.config import STARTER
from liquidity.export import load_tables


def test_row_counts_match_scale(starter):
    c = starter["manifest"]["row_counts"]
    assert c["legal_entity"] == STARTER.entities
    assert c["bank_account"] == STARTER.entities * STARTER.accounts_per_entity
    assert c["ledger_entry"] == STARTER.ledger
    assert c["cash_flow_forecast"] == STARTER.forecast_items
    assert c["receivable"] + c["payable"] == STARTER.forecast_items


def test_five_currencies_present(starter):
    T = starter["T"]
    assert {a["currency"] for a in T["bank_account"]} == {"USD", "EUR", "GBP", "INR", "SGD"}
    assert {c["currency"] for c in T["cash_flow_forecast"]} == {"USD", "EUR", "GBP", "INR", "SGD"}


def test_id_conventions(starter):
    T = starter["T"]
    assert re.match(r"^ENT-\d{6}$", T["legal_entity"][0]["entity_id"])
    assert T["legal_entity"][0]["entity_id"] == "ENT-000001"
    assert T["bank_account"][0]["account_id"] == "BANKACC-ENT-000001-001"
    assert T["ledger_entry"][0]["ledger_id"] == "LED-2026-00000001"
    assert T["cash_flow_forecast"][0]["cf_id"] == "CF-2026-000001"
    assert T["forecast_run"][0]["run_id"] == "FCAST-2026-01-01-001"
    ledger_ids = [l["ledger_id"] for l in T["ledger_entry"]]
    assert ledger_ids == sorted(ledger_ids)
    assert ledger_ids[-1] == f"LED-2026-{STARTER.ledger:08d}"           # contiguous counter


def test_ledger_ids_chronological(starter):
    d = [l["entry_date"] for l in starter["T"]["ledger_entry"]]
    assert d == sorted(d)


def test_all_validation_checks_pass_or_expected(starter):
    s = starter["validation"]["summary"]
    assert s["failed"] == 0, [c for c in starter["validation"]["checks"] if c["status"] == "FAIL"]
    assert s["total_checks"] >= 20


def test_all_five_anomaly_types_labelled(starter):
    kinds = Counter(g["issue_type"] for g in starter["GT"])
    assert set(kinds) == {"BALANCE_MISMATCH", "FX_RATE_MISSING", "CASH_FLOW_COUNTED_TWICE",
                          "FORECAST_USES_ACTUAL_AFTER_CUTOFF", "CURRENCY_MIXED_WITHOUT_CONVERSION"}


def test_ground_truth_is_separate_and_not_leaked(starter):
    d = starter["dir"]
    assert os.path.exists(os.path.join(d, "ground_truth", "ground_truth.csv"))
    for name in S.TABLE_ORDER:
        header = open(os.path.join(d, "csv", f"{name}.csv")).readline().strip().split(",")
        assert not [h for h in header if re.search(r"ground_truth|issue_type|anomaly|label", h)]


def test_detectors_match_ground_truth(starter):
    det = starter["report"]["detection"]
    assert det["overall"]["precision"] == 1.0 and det["overall"]["recall"] == 1.0
    for it, m in det["per_issue_type"].items():
        assert m["decision_accuracy"] == 1.0, it


def test_run_decisions_follow_documented_rule(starter):
    assert starter["report"]["run_decision_accuracy"] == 1.0
    runs = {r["run_id"]: r for r in starter["T"]["forecast_run"]}
    rejected = [r for r in runs.values() if r["review_decision"] == "REJECTED"]
    assert len(rejected) == 2
    for r in rejected:                                    # rejected runs are superseded by a v2 re-run, history kept
        assert r["status"] == "SUPERSEDED"
        assert any(x["supersedes_run_id"] == r["run_id"] and x["status"] == "APPROVED" for x in runs.values())


def test_scenarios_differ_only_by_documented_assumptions(starter):
    T = starter["T"]
    sc = {s["scenario_id"]: s for s in T["liquidity_scenario"]}
    runs = {r["run_id"]: r for r in T["forecast_run"]}
    lines = {}
    for l in T["forecast_run_item"]:
        if l["amount_basis"] == "SCHEDULED":
            lines.setdefault(l["run_id"], {}).setdefault(l["cf_id"], l)
    base, delayed = lines["FCAST-2026-02-01-001"], lines["FCAST-2026-02-01-002"]
    common = set(base) & set(delayed)
    assert common
    for cf in common:                                      # same source facts, differ only by delay parameter
        b, d = base[cf], delayed[cf]
        assert b["scheduled_amount_minor"] == d["scheduled_amount_minor"] and b["base_date"] == d["base_date"]
        if b["direction"] == "OUTFLOW":
            assert b["adjusted_amount_minor"] == d["adjusted_amount_minor"]
    assert sc["SCN-STRESS"]["receivable_haircut_pct"] == 0.10 and sc["SCN-BASE"]["receivable_haircut_pct"] == 0.0


def test_daily_balances_reconcile(starter):
    T = starter["T"]
    for p in T["daily_cash_position"]:
        assert p["opening_minor"] + p["inflow_minor"] - p["outflow_minor"] == p["closing_minor"]


def test_variance_is_explainable(starter):
    for c in starter["T"]["forecast_vs_actual"]:
        eff = sum(c[k] for k in c if k.endswith("_effect_usd_minor"))
        assert c["variance_usd_minor"] - eff == c["rounding_residual_usd_minor"]
        assert abs(c["rounding_residual_usd_minor"]) <= 5


def test_no_history_overwritten_event_chain(starter):
    ev = {}
    for e in starter["T"]["state_event"]:
        ev.setdefault((e["object_type"], e["object_id"]), []).append(e)
    for k, es in ev.items():
        assert [e["sequence_no"] for e in es] == list(range(1, len(es) + 1))
        assert es[0]["from_state"] is None
        for a, b in zip(es, es[1:]):
            assert b["from_state"] == a["to_state"]


def test_domain_coverage(starter):
    rep = starter["report"]["coverage"]
    assert rep["large_one_off_payables"] > 0 and rep["delayed_receivables_paid_late"] > 0
    assert "OVERDUE" in rep["receivable_status"] and rep["runs_by_status"].get("SUPERSEDED") == 2


def test_sqlite_load_and_fk_check(starter, tmp_path):
    con = sqlite3.connect(":memory:")
    con.executescript(open(os.path.join(starter["dir"], "sql", "schema.sql")).read())
    con.executescript(open(os.path.join(starter["dir"], "sql", "seed.sql")).read())
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("SELECT COUNT(*) FROM ledger_entry").fetchone()[0] == STARTER.ledger


def test_json_export_matches_csv(starter):
    rows = json.load(open(os.path.join(starter["dir"], "json", "legal_entity.json")))
    assert len(rows) == STARTER.entities and rows[0]["entity_id"] == "ENT-000001"


def test_reproducible_same_seed(starter, tmp_path):
    out = str(tmp_path / "again")
    _, _, _, man, _ = build(out, STARTER, 20261022, ["csv", "json", "sql"], False, "pytest")
    assert man["row_counts"] == starter["manifest"]["row_counts"]
    assert man["file_sha256"] == starter["manifest"]["file_sha256"]


def test_different_seed_changes_data(tmp_path):
    out = str(tmp_path / "other")
    _, _, _, man, _ = build(out, STARTER, 1, ["csv"], False, "pytest")
    assert man["file_sha256"]["csv/ledger_entry.csv"] != build(str(tmp_path / "o2"), STARTER, 2, ["csv"], False, "x")[3]["file_sha256"]["csv/ledger_entry.csv"]


def test_scale_is_parameterised(tiny_dir):
    T = load_tables(tiny_dir)
    assert len(T["legal_entity"]) == 4 and len(T["ledger_entry"]) == 2500 and len(T["cash_flow_forecast"]) == 400


def test_validator_catches_unlabelled_corruption(starter):
    """Negative test: corrupting a clean row without a label must FAIL validation."""
    import copy
    from liquidity.validate import validate
    T = copy.deepcopy(starter["T"])
    T["receivable"][0]["settled_amount_minor"] += 1
    T["ledger_entry"][5]["balance_after_minor"] += 1
    res = validate(T, starter["GT"])
    failed = {c["id"] for c in res["checks"] if c["status"] == "FAIL"}
    assert {"V08", "V13"} <= failed
