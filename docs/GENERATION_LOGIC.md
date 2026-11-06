# Generation logic (how outcomes follow rules, not dice)

All randomness comes from `random.Random(f"{seed}:{stream}")` (one stream per module), seed **20261022**.
No wall-clock values are written, so identical seeds give byte-identical files.

## Order of generation (parents before children)
1. `currency_rate` - daily random walk with mean reversion for EUR/GBP/INR/SGD vs USD (2025-12-31 .. 2026-10-01) plus
   documented FX movement events: EUR +2% (18 Mar), INR -4% (10-20 Jun), GBP -3% (5 Aug).
2. `legal_entity` (30) - holding / treasury centre / operating / SPV; 27 ACTIVE, 2 DORMANT (from 14 Aug), 1 CLOSED (29 May).
3. `bank_account` (5 per entity: OPERATING, COLLECTION, PAYROLL, RESERVE, FX) across USD, EUR, GBP, INR, SGD.
4. Compliance freezes: temporary freeze windows (no postings) and one account still frozen at cutoff.
5. `receivable` / `payable` / `cash_flow_forecast` (10,000 + 10,000 = 20,000 1:1 items).
6. Outcome rules -> `ledger_entry` settlements (see below), plus unscheduled operating activity and closure sweeps (total exactly 100,000).
7. Opening balances are **derived** so the running balance never breaches the overdraft policy (12% of accounts are
   deliberately "thin" and run close to / inside their overdraft).
8. `state_event` histories are produced by a single lifecycle walker from the dated facts above.
9. Scenarios -> forecast runs -> lines -> projections -> actual-vs-forecast (derived from tables only).

## Outcome rules (ground truth comes from these, never from independent random labels)
| Counterparty tier | Mean delay | Outcomes (full / split / write-off) | Prob. customer announces later date |
|---|---|---|---|
| LOW | +1 d | 96% / 4% / 0% | 3% |
| MEDIUM | +8 d | 86% / 12% / 2% | 10% |
| HIGH | +22 d | 70% / 20% / 10% | 25% |

- Write-off happens 90 days after due; receipts/payments on weekends roll to Monday; payments inside an account freeze
  roll to the first business day after it; entities that close/go dormant settle everything on or before that date.
- Payables: CRITICAL (payroll, tax, loans) pay on the due date; STANDARD +3 d; DEFERRABLE +9 d; 4% of supplier invoices get
  a negotiated extension; 2.5% of payables are **large one-off** CAPEX payments (median 200k USD-eq vs 11k for suppliers).
- 1-1.5% of items are cancelled before due date.

## Derived values (never generated independently)
`ledger.signed_amount`, `ledger.balance_after`, `receivable/payable.settled/outstanding/status/days_past_due`,
`cash_flow_forecast.realized_*/status`, `bank_account.opening_balance/statement_closing_balance`,
`legal_entity.min_liquidity_buffer` (= 2 x mean monthly payables), `daily_cash_position.*`, all `forecast_run.*` metrics.

## Forecast method
Runs are created on the 1st of Jan-Oct 2026 for each of 3 scenarios (13-week horizon, `data_cutoff = run_date - 1`).
`projected(entity, d) = sum_ccy plan_rate x (balance at cutoff + cumulative scenario-adjusted scheduled flows + run-rate x days)`.
Only items created by the cutoff, not terminal by the cutoff, are used; amounts are the *remaining* balance at cutoff.

| Parameter | BASE | DELAYED_RECEIPT | STRESS |
|---|---|---|---|
| receipt_delay_days | 0 | 10 | 21 |
| payable_acceleration_days | 0 | 0 | 5 |
| receivable_haircut_pct | 0 | 0 | 10% |
| one_off_outflow_multiplier | 1.0 | 1.0 | 1.25 |
| fx_shock_pct (non-USD vs USD) | 0 | 0 | -8% |
| overdue_rollover_days | 3 | 7 | 14 |

Scenarios share every other input; validation V19 recomputes every line from the rule + parameters.

## Actual-versus-forecast variance (additive, exact)
`variance = actual - forecast = timing + amount + unscheduled flows + FX + double-count + rounding residual` (|residual| <= 5 cents).
- *timing*: item settled earlier/later than the scenario date; *amount*: settled amount differs (partials, haircut);
- *unscheduled*: actual ad-hoc flows minus the run-rate projection; *FX*: actual vs plan rate on actual balances;
- *double-count*: duplicated forecast lines.

## Injected edge cases (all labelled in `ground_truth/`)
| issue_type | How injected | Where | Expected decision |
|---|---|---|---|
| BALANCE_MISMATCH | bank `statement_closing_balance` shifted by delta (1 cent .. 2,500.00) | bank_account | INVESTIGATE_AND_ADJUST_BEFORE_CLOSE |
| FX_RATE_MISSING | rate rows removed (1-day gaps, a 5-day GBP gap, INR on a run cutoff day) | currency_rate | CARRY_FORWARD_WITH_FLAG (<=3 d) / BLOCK_USD_CONVERSION (>3 d) |
| CASH_FLOW_COUNTED_TWICE | duplicate lines in run FCAST-2026-04-01-001 | forecast_run_item | REJECT_RUN_AND_RERUN |
| FORECAST_USES_ACTUAL_AFTER_CUTOFF | lines in FCAST-2026-06-01-002 use actual ledger amounts dated after cutoff | forecast_run_item | REJECT_RUN_AND_RERUN |
| CURRENCY_MIXED_WITHOUT_CONVERSION | ledger `currency` differs from account currency | ledger_entry | QUARANTINE_AND_CONVERT_AT_ENTRY_DATE_RATE |

Rejected runs get a version-2 re-run (`...-004`) and are marked SUPERSEDED; nothing is overwritten.
The two rejected runs, and the runs whose cutoff day lacks an FX rate (APPROVED_WITH_EXCEPTIONS), are listed in
`ground_truth_run_decisions.csv`.
