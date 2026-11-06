# Short-Term Liquidity Forecasting - Synthetic Data Generator

Seeded, reproducible generator (pure Python standard library) that **consolidates account balances and expected cash flows
to forecast short-term liquidity under base, delayed-receipt and stress scenarios**, with labelled anomalies, a separate
ground truth, a validation suite, rule-based exception detectors and measurable evaluation metrics.

| Required volume (full) | Produced |
|---|---|
| 30 legal entities / 150 bank accounts | 30 / 150 |
| 100,000 ledger entries | 100,000 |
| 20,000 forecast items (10k receivables + 10k payables) | 20,000 |
| 5 currencies | USD, EUR, GBP, INR, SGD |
| Seed | `20261022` |

## Quick start (Windows / macOS / Linux)
```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt          # only pytest is needed
python -m pytest -q                      # tests (~7 s)
python -m liquidity generate --scale starter     # small dataset -> data/starter (~2 s)
python -m liquidity generate --scale full --formats csv,sql --gzip-sql   # full -> data/full (~25 s)
python -m liquidity repro --scale full           # regenerate twice, compare row counts + SHA-256 checksums
python scripts/run_all.py                        # everything above + reports in one go
```
Starter and full use the **same generator**; scale is parameterised
(`--scale`, or custom `--entities N --ledger N --items N`, `--seed N`).

## Commands
| Command | Purpose |
|---|---|
| `python -m liquidity generate --scale starter\|full [--formats csv,json,sql] [--gzip-sql] [--out DIR]` | build, validate, evaluate and export a dataset |
| `python -m liquidity validate --data data/starter` | re-run the 22 validation checks on exported CSVs |
| `python -m liquidity evaluate --data data/starter` | print detector / forecast-accuracy metrics |
| `python -m liquidity repro --scale starter\|full` | reproducibility proof (2 regenerations, checksums compared) |
| `python -m liquidity sqlite --data data/starter` | load schema + seed into SQLite and run `PRAGMA foreign_key_check` |
| `python -m liquidity docs` | regenerate `docs/DATA_DICTIONARY.md` |

Generator command used for the committed starter data: `python -m liquidity generate --scale starter --seed 20261022 --out data/starter --formats csv,json,sql`.

## Repository layout
```
liquidity/            generator package (config, schema, generate, inject, forecast, pipeline, validate, detect, evaluate, export, cli)
tests/                pytest suite (20 fast tests + 1 full-scale test: RUN_FULL=1)
docs/                 DATA_DICTIONARY.md, ERD.md (cardinality, lifecycle), GENERATION_LOGIC.md
data/starter/         committed starter dataset: csv/ json/ sql/ ground_truth/ schema/ + manifest, reports
data/full/            full dataset (git-ignored by default; reproduce with the command above)
reports/              reproducibility + validation + evaluation reports for starter and full
scripts/run_all.py    one-shot runner
```
Each dataset folder contains: `csv/ json/ sql/(schema.sql, seed.sql[.gz]) ground_truth/ schema/ manifest.json
source_manifest.json validation_summary.json evaluation_report.json exceptions_detected.csv checksums.sha256`.

## Data model (16 tables)
Core: `legal_entity, bank_account, ledger_entry, cash_flow_forecast, receivable, payable, currency_rate, liquidity_scenario, forecast_run`.
Supporting: `scenario_assumption`, bridges `forecast_run_item` (run N:M forecast item) and `forecast_run_entity` (run N:M entity),
derived `daily_cash_position`, `forecast_daily_position`, `forecast_vs_actual`, and the append-only `state_event` history.
IDs: `ENT-000001`, `BANKACC-ENT-000001-001`, `LED-2026-00000001`, `CF-2026-000001`, `FCAST-2026-01-01-001`
(plus `RCV-2026-`, `PAY-2026-`, `RATE-2026-`, `SCN-`, `EVT-2026-`, ...). See `docs/DATA_DICTIONARY.md` and `docs/ERD.md`.

## How the requirements are covered
| Requirement | Where |
|---|---|
| Data dictionary (type, required, allowed, unit, unique, rule) | `docs/DATA_DICTIONARY.md`, `schema/data_dictionary.json` (generated from `liquidity/schema.py`) |
| Parents first, valid FKs, bridge tables, history not overwritten | `generate.py`, `forecast.py`; `state_event`; re-runs create new `run_id` and mark the old one SUPERSEDED |
| Opening balances, ledger, receivables/payables, FX, daily positions, 3 scenarios, forecast versions, actual-vs-forecast | `generate.py`, `forecast.py`, tables `daily_cash_position`, `forecast_run`, `forecast_vs_actual` |
| Delayed receivables, FX movement, large one-offs | tier-based delays (5,000+ late receipts), FX shock events, CAPEX_ONE_OFF payables |
| 5 labelled edge cases | `inject.py` -> `ground_truth/ground_truth.csv|json` (balance mismatch, missing FX, double count, look-ahead, mixed currency) |
| Derived values from source records | balances, statuses, settled amounts, buffers, run metrics are computed (see `docs/GENERATION_LOGIC.md`) |
| Separate ground truth, no leakage | `ground_truth/` folder; test + validation V22 check no label columns in inputs; detectors never read it |
| Validation (PK/FK/enum/date/arithmetic/lifecycle/duplicates) | `validate.py` (22 checks) -> `validation_summary.json`; labelled anomalies = expected exceptions, anything else FAILS |
| Reproducibility | `repro` command -> `reports/reproducibility_*.json` (identical row counts and SHA-256 for every file) |
| Acceptance: balances reconcile, scenarios differ only by assumptions, forecasts reproducible, variance explainable | V09/V10, V18/V19, `repro`, V21 |

## Actors
Customer/account holder (entity dormancy/closure requests), operations analyst (creates runs, records invoices),
risk/compliance reviewer (approves/rejects runs, freezes accounts, write-offs), system administrator (onboarding,
scenario definitions, account closure), plus `SYSTEM` for automated events - all recorded in `state_event.actor_role`.
Exceptions are surfaced in `exceptions_detected.csv` with a recommended decision.

## Results on the full dataset (seed 20261022)
- Validation: 17 checks pass, 5 pass with *exactly* the labelled exceptions, 0 fail.
- Detectors vs ground truth: precision 1.0, recall 1.0, decision accuracy 1.0 (106 labelled anomalies); run-decision accuracy 1.0.
- 100% of 9,899 actual-vs-forecast rows are explained (|residual| <= 5 cents). Dominant drivers: unscheduled flows, timing, FX.
- Forecast accuracy (WAPE, approved runs): BASE 2.3% (days 1-14) -> 8.4% (days 46-91) and is optimistic at long horizons
  (receipts arrive later than expected); DELAYED_RECEIPT is better at days 15-45 (3.0% vs 4.4%).
- Overdrawn account-days, 5,570 late receipts, 276 large one-off payments and 3 FX shock events provide boundary/stress coverage.

## Lawful provenance
No external data was downloaded or redistributed (`source_manifest.json`). ISO 4217/3166 codes and general treasury
practice were used for schema inspiration only; FX starting levels are round numbers chosen by the author. Entity,
customer and supplier names/IDs are fictitious. Code: MIT. Generated data: CC0-1.0.

## Troubleshooting
- `ModuleNotFoundError: liquidity` - run commands from the repository root (the folder containing `liquidity/`).
- `python` not found on macOS/Linux - use `python3`.
- Full generation needs ~500 MB RAM and ~25 s.
