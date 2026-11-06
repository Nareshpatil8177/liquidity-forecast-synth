"""Command line interface:  python -m liquidity <generate|validate|evaluate|repro|sqlite|docs> ..."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

from . import schema as S
from .config import DEFAULT_SEED, PRESETS, Scale
from .detect import DET_FIELDS
from .evaluate import evaluate
from .export import (finalize_manifest, load_ground_truth, load_run_decisions, load_tables, write_dataset)
from .pipeline import generate_tables
from .validate import validate


def _scale(a) -> Scale:
    base = PRESETS[a.scale]
    return Scale(a.scale if not (a.entities or a.ledger or a.items) else "custom", a.entities or base.entities,
                 base.accounts_per_entity, a.ledger or base.ledger, a.items or base.forecast_items)


def build(out, scale: Scale, seed: int, formats, gzip_sql=False, command="", json_max_rows=50000):
    t0 = time.time()
    t, gt, rd = generate_tables(scale, seed)
    write_dataset(out, t, gt, rd, scale, seed, formats, json_max_rows, gzip_sql, command)
    T = load_tables(out)                                  # validate what was actually written
    G, RD = load_ground_truth(out), load_run_decisions(out)
    v = validate(T, G)
    rep, det = evaluate(T, G, RD)
    with open(os.path.join(out, "validation_summary.json"), "w") as f:
        json.dump(v, f, indent=1)
    with open(os.path.join(out, "evaluation_report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    with open(os.path.join(out, "exceptions_detected.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, DET_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(det)
    man = finalize_manifest(out, t, scale, seed, command)
    return t, v, rep, man, round(time.time() - t0, 1)


def cmd_generate(a):
    scale = _scale(a)
    out = a.out or os.path.join("data", scale.name)
    cmdline = f"python -m liquidity generate --scale {a.scale} --seed {a.seed} --out {out} --formats {a.formats}" + \
              (f" --entities {a.entities}" if a.entities else "") + (f" --ledger {a.ledger}" if a.ledger else "") + \
              (f" --items {a.items}" if a.items else "") + (" --gzip-sql" if a.gzip_sql else "")
    if os.path.isdir(out):
        shutil.rmtree(out)
    _, v, rep, man, secs = build(out, scale, a.seed, a.formats.split(","), a.gzip_sql, cmdline)
    s = v["summary"]
    print(f"[ok] {scale.name} dataset -> {out}  ({secs}s)")
    print("     rows:", man["row_counts"])
    print(f"     validation: {s['passed']} pass, {s['passed_with_expected_exceptions']} pass-with-labelled-exceptions, {s['failed']} FAIL")
    print("     detector overall:", rep["detection"]["overall"], " run-decision accuracy:", rep["run_decision_accuracy"])
    return 1 if s["failed"] else 0


def cmd_validate(a):
    T = load_tables(a.data)
    v = validate(T, load_ground_truth(a.data))
    for c in v["checks"]:
        print(f"{c['id']} {c['status']:<26} viol={c['violations_found']:<5} labelled={c['labelled_expected']:<4} {c['name']}")
    print(v["summary"]["failed"], "failed checks")
    return 1 if v["summary"]["failed"] else 0


def cmd_evaluate(a):
    rep, _ = evaluate(load_tables(a.data), load_ground_truth(a.data), load_run_decisions(a.data))
    print(json.dumps(rep, indent=1))
    return 0


def _checksums(out):
    with open(os.path.join(out, "manifest.json")) as f:
        m = json.load(f)
    return m["row_counts"], m["file_sha256"]


def cmd_repro(a):
    scale = _scale(a)
    cmdline = f"python -m liquidity generate --scale {a.scale} --seed {a.seed}"
    runs = []
    tmp = tempfile.mkdtemp()
    for i in (1, 2):
        out = os.path.join(tmp, f"run{i}")
        build(out, scale, a.seed, ["csv", "json", "sql"], False, cmdline)
        runs.append(_checksums(out))
    same_rows = runs[0][0] == runs[1][0]
    same_files = runs[0][1] == runs[1][1]
    rep = dict(seed=a.seed, scale=scale.name, runs=2, row_counts_identical=same_rows, all_file_checksums_identical=same_files,
               files_compared=len(runs[0][1]), row_counts=runs[0][0],
               combined_sha256=hashlib.sha256(json.dumps(runs[0][1], sort_keys=True).encode()).hexdigest())
    shutil.rmtree(tmp)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(rep, f, indent=1)
    print(json.dumps(rep, indent=1))
    return 0 if same_rows and same_files else 1


def cmd_sqlite(a):
    db = a.db or os.path.join(a.data, "liquidity.db")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.executescript(open(os.path.join(a.data, "sql", "schema.sql")).read())
    sp = os.path.join(a.data, "sql", "seed.sql")
    con.executescript(open(sp).read() if os.path.exists(sp) else gzip.open(sp + ".gz", "rt").read())
    con.commit()
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    print(f"[ok] SQLite database {db}; foreign_key_check violations: {len(bad)}")
    return 1 if bad else 0


def cmd_docs(a):
    os.makedirs("docs", exist_ok=True)
    open("docs/DATA_DICTIONARY.md", "w").write(S.render_dictionary_md())
    print("[ok] docs/DATA_DICTIONARY.md regenerated")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="liquidity", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("generate", cmd_generate), ("repro", cmd_repro)):
        s = sub.add_parser(name)
        s.add_argument("--scale", choices=list(PRESETS), default="starter")
        s.add_argument("--seed", type=int, default=DEFAULT_SEED)
        s.add_argument("--entities", type=int)
        s.add_argument("--ledger", type=int)
        s.add_argument("--items", type=int)
        s.add_argument("--out")
        if name == "generate":
            s.add_argument("--formats", default="csv,json,sql")
            s.add_argument("--gzip-sql", action="store_true")
        s.set_defaults(fn=fn)
    for name, fn in (("validate", cmd_validate), ("evaluate", cmd_evaluate)):
        s = sub.add_parser(name)
        s.add_argument("--data", required=True)
        s.set_defaults(fn=fn)
    s = sub.add_parser("sqlite")
    s.add_argument("--data", required=True)
    s.add_argument("--db")
    s.set_defaults(fn=cmd_sqlite)
    s = sub.add_parser("docs")
    s.set_defaults(fn=cmd_docs)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
