"""Step 9: export CSV / JSON / SQL seed data, ground truth, manifests; plus a CSV loader used by validation."""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import os
from typing import Dict

from . import schema as S
from .config import DATA_CUTOFF, DEFAULT_SEED, GENERATOR_VERSION, Scale
from .inject import GT_FIELDS
from .util import sha256_file

RUN_DEC_FIELDS = ["run_id", "expected_review_decision", "reason"]


def _w(path, rows, fields, fmt):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([x.name if hasattr(x, "name") else x for x in fields])
        for r in rows:
            w.writerow([fmt(x, r[x.name if hasattr(x, "name") else x]) for x in fields])


def _sql_lit(f, v):
    if v is None:
        return "NULL"
    if f.type == "boolean":
        return "TRUE" if v else "FALSE"
    if f.type == "integer":
        return str(int(v))
    if f.type == "decimal":
        return f"{v:.{f.scale}f}"
    if f.type in ("date", "datetime"):
        return "'" + v.isoformat() + "'"
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path, tables, gz):
    opener = (lambda p: gzip.GzipFile(p, "wb", mtime=0)) if gz else (lambda p: open(p, "wb"))
    with opener(path) as f:
        f.write(b"-- Seed data (generated). Load after schema.sql.\nBEGIN;\n")
        for name in S.TABLE_ORDER:
            t = S.TABLE_MAP[name]
            cols = ", ".join(t.field_names)
            rows = tables[name]
            for i in range(0, len(rows), 500):
                vals = ",\n".join("(" + ", ".join(_sql_lit(fl, r[fl.name]) for fl in t.fields) + ")" for r in rows[i:i + 500])
                f.write(f"INSERT INTO {name} ({cols}) VALUES\n{vals};\n".encode())
        f.write(b"COMMIT;\n")


def write_dataset(out, tables, gt, run_dec, scale: Scale, seed: int, formats=("csv", "json", "sql"),
                  json_max_rows=50000, gzip_sql=False, command=""):
    os.makedirs(out, exist_ok=True)
    files = {}
    for name in S.TABLE_ORDER:
        t = S.TABLE_MAP[name]
        if "csv" in formats:
            _w(os.path.join(out, "csv", f"{name}.csv"), tables[name], t.fields, S.fmt_value)
        if "json" in formats and len(tables[name]) <= json_max_rows:
            p = os.path.join(out, "json", f"{name}.json")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump([{x.name: (S.fmt_value(x, r[x.name]) if r[x.name] is not None and x.type in ("date", "datetime", "decimal") else r[x.name])
                            for x in t.fields} for r in tables[name]], f, indent=0)
    os.makedirs(os.path.join(out, "sql"), exist_ok=True)
    with open(os.path.join(out, "sql", "schema.sql"), "w") as f:
        f.write(S.render_ddl())
    if "sql" in formats:
        write_sql(os.path.join(out, "sql", "seed.sql.gz" if gzip_sql else "seed.sql"), tables, gzip_sql)
    gdir = os.path.join(out, "ground_truth")      # kept apart from input tables on purpose
    _w(os.path.join(gdir, "ground_truth.csv"), gt, GT_FIELDS, lambda f, v: "" if v is None else str(v))
    with open(os.path.join(gdir, "ground_truth.json"), "w") as f:
        json.dump(gt, f, indent=1)
    _w(os.path.join(gdir, "ground_truth_run_decisions.csv"), run_dec, RUN_DEC_FIELDS, lambda f, v: str(v))
    os.makedirs(os.path.join(out, "schema"), exist_ok=True)
    with open(os.path.join(out, "schema", "data_dictionary.json"), "w") as f:
        json.dump(S.dictionary_json(), f, indent=1)
    with open(os.path.join(out, "schema", "DATA_DICTIONARY.md"), "w") as f:
        f.write(S.render_dictionary_md())
    source = {"external_data_used": False,
              "statement": "All records are synthetic, produced by the seeded generator in this repository. No personal, "
                           "confidential or third-party licensed data was accessed or redistributed.",
              "schema_inspiration_only": ["ISO 4217 currency codes", "ISO 3166-1 alpha-2 country codes",
                                          "generic treasury cash-forecasting practice (receipts/payments/scenarios)"],
              "fx_start_levels": "Approximate round numbers chosen by the author; not downloaded or copied from any dataset.",
              "license_of_generated_data": "CC0-1.0", "license_of_code": "MIT"}
    with open(os.path.join(out, "source_manifest.json"), "w") as f:
        json.dump(source, f, indent=1)
    return out


def finalize_manifest(out, tables, scale: Scale, seed: int, command: str):
    """Write checksums + manifest (called after reports exist so they are covered too)."""
    chk = {}
    for root, _, fs in os.walk(out):
        for fn in sorted(fs):
            if fn in ("manifest.json", "checksums.sha256"):
                continue
            p = os.path.join(root, fn)
            chk[os.path.relpath(p, out).replace(os.sep, "/")] = sha256_file(p)
    man = dict(dataset=scale.name, generator_version=GENERATOR_VERSION, seed=seed, data_cutoff_date=DATA_CUTOFF.isoformat(),
               scale=dict(entities=scale.entities, accounts_per_entity=scale.accounts_per_entity,
                          ledger_entries=scale.ledger, forecast_items=scale.forecast_items),
               generator_command=command, row_counts={k: len(v) for k, v in tables.items()},
               file_sha256=dict(sorted(chk.items())))
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(man, f, indent=1)
    with open(os.path.join(out, "checksums.sha256"), "w") as f:
        for k, v in sorted(chk.items()):
            f.write(f"{v}  {k}\n")
    return man


# ----------------------------------------------------------------------------- loader
def _conv(f, s):
    if s == "":
        return None
    if f.type == "integer":
        return int(s)
    if f.type == "decimal":
        return float(s)
    if f.type == "boolean":
        return s == "true"
    if f.type == "date":
        return dt.date.fromisoformat(s)
    if f.type == "datetime":
        return dt.datetime.fromisoformat(s)
    return s


def load_tables(dir_) -> Dict[str, list]:
    out = {}
    for name in S.TABLE_ORDER:
        t = S.TABLE_MAP[name]
        with open(os.path.join(dir_, "csv", f"{name}.csv"), newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            out[name] = [{f.name: _conv(f, row[f.name]) for f in t.fields} for row in rd]
    return out


def load_ground_truth(dir_):
    with open(os.path.join(dir_, "ground_truth", "ground_truth.csv"), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_run_decisions(dir_):
    with open(os.path.join(dir_, "ground_truth", "ground_truth_run_decisions.csv"), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
