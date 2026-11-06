# Data Dictionary

Generated from `liquidity/schema.py` (single source of truth). Amount fields ending `_minor` are integers in currency minor units (1/100). `*_usd_minor` are USD cents. Dates are ISO-8601.

## `legal_entity`

Legal entities of the group (master data, parent of everything).

- **Primary key:** `entity_id`  (ID pattern `^ENT-\d{6}$`)
- **Cardinality / relationships:** 1:N bank_account; 1:N receivable/payable/cash_flow_forecast; self-reference N:1 parent (optional); N:M forecast_run via forecast_run_entity
- **Lifecycle:** ACTIVE -> DORMANT|CLOSED ; DORMANT -> ACTIVE|CLOSED

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `entity_id` | string | Y |  |  | Y |  | ENT-###### zero padded; immutable |
| `legal_name` | string | Y |  |  | Y |  | synthetic name; no real companies |
| `entity_type` | string | Y | HOLDING, OPERATING, SPV, TREASURY_CENTRE |  |  |  |  |
| `country_code` | string | Y | US, DE, FR, NL, GB, IN, SG |  |  |  | ISO 3166-1 alpha-2 |
| `functional_currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  | ISO 4217; drives default account currency |
| `parent_entity_id` | string | N |  |  |  | legal_entity.entity_id | optional; parent id < own id (acyclic); NULL for holding |
| `size_tier` | string | Y | SMALL, MEDIUM, LARGE |  |  |  | derived from relative transaction scale |
| `status` | string | Y | ACTIVE, DORMANT, CLOSED |  |  |  | current lifecycle state; history in state_event |
| `status_since` | date | Y |  |  |  |  | >= effective_from |
| `incorporation_date` | date | Y |  |  |  |  |  |
| `effective_from` | date | Y |  |  |  |  | = incorporation_date |
| `effective_to` | date | N |  |  |  |  | required iff status=CLOSED; > effective_from |
| `min_liquidity_buffer_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | >= 0; derived = 2.0 x mean monthly payables (USD-equivalent at opening FX) |

## `bank_account`

Bank accounts held by legal entities.

- **Primary key:** `account_id`  (ID pattern `^BANKACC-ENT-\d{6}-\d{3}$`)
- **Cardinality / relationships:** N:1 legal_entity; 1:N ledger_entry; 1:N daily_cash_position
- **Lifecycle:** OPEN <-> FROZEN ; OPEN|FROZEN -> CLOSED

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `account_id` | string | Y |  |  | Y |  | BANKACC-<entity-id>-### ; immutable |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `bank_name` | string | Y |  |  |  |  | synthetic bank name |
| `account_type` | string | Y | OPERATING, COLLECTION, PAYROLL, RESERVE, FX |  |  |  |  |
| `currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  | ISO 4217; every ledger entry on the account must use this currency |
| `status` | string | Y | OPEN, FROZEN, CLOSED |  |  |  | current state; history in state_event |
| `opened_date` | date | Y |  |  |  |  | <= opening_balance_date; >= entity.effective_from |
| `closed_date` | date | N |  |  |  |  | required iff status=CLOSED; >= opened_date |
| `opening_balance_date` | date | Y |  |  |  |  | = 2025-12-31 (end-of-day balance) |
| `opening_balance_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | >= 0 |
| `overdraft_limit_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | >= 0 |
| `statement_date` | date | Y |  |  |  |  | bank statement as-of date = closed_date or data cutoff |
| `statement_closing_balance_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | bank-reported closing balance; must equal opening + sum(ledger) unless labelled BALANCE_MISMATCH |

## `ledger_entry`

Posted bank ledger movements (actuals).

- **Primary key:** `ledger_id`  (ID pattern `^LED-2026-\d{8}$`)
- **Cardinality / relationships:** N:1 bank_account; N:1 cash_flow_forecast (optional, 0..N settlements per item)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `ledger_id` | string | Y |  |  | Y |  | LED-2026-######## ; chronological order |
| `account_id` | string | Y |  |  |  | bank_account.account_id |  |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id | must equal bank_account.entity_id |
| `entry_date` | date | Y |  |  |  |  | >= 2026-01-01 and <= data cutoff; business day |
| `currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  | must equal bank_account.currency (else MIXED_CURRENCY anomaly) |
| `direction` | string | Y | CREDIT, DEBIT |  |  |  |  |
| `amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | > 0 |
| `signed_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | +amount for CREDIT, -amount for DEBIT |
| `balance_after_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | running balance = opening + cumulative signed |
| `entry_type` | string | Y | CUSTOMER_RECEIPT, SUPPLIER_PAYMENT, PAYROLL, TAX_PAYMENT, LOAN_REPAYMENT, CAPEX_PAYMENT, CARD_SETTLEMENT, MISC_RECEIPT, INTEREST_CREDIT, BANK_FEE, MISC_PAYMENT, ACCOUNT_CLOSURE_SWEEP |  |  |  |  |
| `cf_id` | string | N |  |  |  | cash_flow_forecast.cf_id | set for settlements of scheduled items |
| `source_ref_id` | string | N |  |  |  |  | RCV-/PAY- id of the settled document (consistent with cf_id) |
| `counterparty_ref` | string | N |  |  |  |  | pseudonymous reference |
| `description` | string | Y |  |  |  |  |  |
| `posting_status` | string | Y | POSTED |  |  |  |  |

## `receivable`

Scheduled customer invoices (expected cash inflows).

- **Primary key:** `receivable_id`  (ID pattern `^RCV-2026-\d{6}$`)
- **Cardinality / relationships:** 1:1 cash_flow_forecast (optional); N:1 legal_entity; N:1 bank_account
- **Lifecycle:** OPEN -> OVERDUE|PARTIALLY_PAID|PAID|CANCELLED|WRITTEN_OFF ; OVERDUE <-> PARTIALLY_PAID ; ... -> PAID|WRITTEN_OFF

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `receivable_id` | string | Y |  |  | Y |  |  |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `account_id` | string | Y |  |  |  | bank_account.account_id | receiving account; same entity; same currency as invoice |
| `counterparty_ref` | string | Y |  |  |  |  | CUST-####; pseudonymous |
| `counterparty_risk_tier` | string | Y | LOW, MEDIUM, HIGH |  |  |  | drives payment delay / partial / write-off behaviour |
| `invoice_date` | date | Y |  |  |  |  |  |
| `due_date` | date | Y |  |  |  |  | >= invoice_date + 1; business day |
| `payment_terms_days` | integer | Y |  | days |  |  | due_date - invoice_date |
| `currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  |  |
| `invoice_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | > 0 |
| `settled_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | derived = sum of linked ledger credits |
| `outstanding_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | derived = invoice - settled while OPEN/OVERDUE/PARTIALLY_PAID else 0 |
| `last_payment_date` | date | N |  |  |  |  | derived from ledger |
| `days_past_due_at_cutoff` | integer | Y |  | days |  |  | derived; 0 if nothing outstanding |
| `status` | string | Y | OPEN, OVERDUE, PARTIALLY_PAID, PAID, WRITTEN_OFF, CANCELLED |  |  |  | derived from state_event chain |
| `terminal_date` | date | N |  |  |  |  | date PAID/WRITTEN_OFF/CANCELLED reached |
| `status_as_of_date` | date | Y |  |  |  |  | = data cutoff |

## `payable`

Scheduled supplier/payroll/tax/loan/capex payments (expected outflows).

- **Primary key:** `payable_id`  (ID pattern `^PAY-2026-\d{6}$`)
- **Cardinality / relationships:** 1:1 cash_flow_forecast (optional); N:1 legal_entity; N:1 bank_account
- **Lifecycle:** OPEN -> OVERDUE|PARTIALLY_PAID|PAID|CANCELLED ; OVERDUE <-> PARTIALLY_PAID

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `payable_id` | string | Y |  |  | Y |  |  |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `account_id` | string | Y |  |  |  | bank_account.account_id | paying account; same entity |
| `supplier_ref` | string | Y |  |  |  |  | SUPP-#### / INTERNAL-PAYROLL / TAXAUTH-xx / LENDER-xx |
| `supplier_tier` | string | Y | CRITICAL, STANDARD, DEFERRABLE |  |  |  |  |
| `category` | string | Y | SUPPLIER_PAYMENT, PAYROLL, TAX_PAYMENT, LOAN_REPAYMENT, CAPEX_ONE_OFF |  |  |  |  |
| `is_large_one_off` | boolean | Y |  |  |  |  | true iff category = CAPEX_ONE_OFF |
| `invoice_date` | date | Y |  |  |  |  |  |
| `due_date` | date | Y |  |  |  |  | >= invoice_date + 1; business day |
| `payment_terms_days` | integer | Y |  | days |  |  |  |
| `currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  |  |
| `invoice_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | > 0 |
| `settled_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | derived from ledger debits |
| `outstanding_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | derived |
| `last_payment_date` | date | N |  |  |  |  |  |
| `days_past_due_at_cutoff` | integer | Y |  | days |  |  |  |
| `status` | string | Y | OPEN, OVERDUE, PARTIALLY_PAID, PAID, CANCELLED |  |  |  |  |
| `terminal_date` | date | N |  |  |  |  |  |
| `status_as_of_date` | date | Y |  |  |  |  |  |

## `cash_flow_forecast`

Forecast item: one expected cash flow derived from exactly one receivable or payable.

- **Primary key:** `cf_id`  (ID pattern `^CF-2026-\d{6}$`)
- **Cardinality / relationships:** 1:1 receivable|payable; 1:N ledger_entry (settlements); N:M forecast_run via forecast_run_item
- **Lifecycle:** SCHEDULED -> DELAYED|PARTIALLY_REALIZED|REALIZED|CANCELLED|WRITTEN_OFF ; DELAYED <-> PARTIALLY_REALIZED

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `cf_id` | string | Y |  |  | Y |  | CF-2026-###### |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `account_id` | string | Y |  |  |  | bank_account.account_id |  |
| `receivable_id` | string | N |  |  | Y | receivable.receivable_id | exactly one of receivable_id/payable_id |
| `payable_id` | string | N |  |  | Y | payable.payable_id | exactly one of receivable_id/payable_id |
| `direction` | string | Y | INFLOW, OUTFLOW |  |  |  | INFLOW iff receivable |
| `category` | string | Y | CUSTOMER_RECEIPT, SUPPLIER_PAYMENT, PAYROLL, TAX_PAYMENT, LOAN_REPAYMENT, CAPEX_ONE_OFF |  |  |  |  |
| `currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  | = bank_account.currency |
| `scheduled_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | > 0; = document invoice amount |
| `expected_date` | date | Y |  |  |  |  | original expected cash date (business day); immutable |
| `revised_expected_date` | date | N |  |  |  |  | > expected_date; only with revised_at |
| `revised_at` | date | N |  |  |  |  | >= created_date and < expected_date; date the revision became known |
| `created_date` | date | Y |  |  |  |  | date the item entered the forecast (= invoice_date) |
| `confidence_score` | decimal(4dp) | Y |  |  |  |  | 0..1; derived from counterparty tier and revision |
| `is_large_one_off` | boolean | Y |  |  |  |  |  |
| `status` | string | Y | SCHEDULED, DELAYED, PARTIALLY_REALIZED, REALIZED, WRITTEN_OFF, CANCELLED |  |  |  | derived from state_event chain |
| `realized_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | derived = sum of linked ledger entries |
| `realized_date` | date | N |  |  |  |  | date of last linked ledger entry |
| `terminal_date` | date | N |  |  |  |  | date REALIZED/WRITTEN_OFF/CANCELLED reached |

## `currency_rate`

Daily FX rates (USD per 1 unit of currency). Missing rows are labelled anomalies.

- **Primary key:** `rate_id`  (ID pattern `^RATE-2026-\d{6}$`)
- **Cardinality / relationships:** referenced logically by currency+date from ledger/position/forecast conversions
- **Composite uniqueness:** (from_currency, rate_date)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `rate_id` | string | Y |  |  | Y |  | never renumbered when a row is removed |
| `rate_date` | date | Y |  |  |  |  | effective date of the rate |
| `from_currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  |  |
| `to_currency` | string | Y | USD |  |  |  | reporting currency |
| `rate` | decimal(8dp) | Y |  | USD per 1 unit |  |  | > 0; USD = 1 |
| `rate_type` | string | Y | SPOT_CLOSE |  |  |  |  |
| `source` | string | Y | SYNTHETIC_RANDOM_WALK |  |  |  |  |

## `liquidity_scenario`

Scenario definitions (documented assumptions).

- **Primary key:** `scenario_id`  (ID pattern `^SCN-[A-Z]+$`)
- **Cardinality / relationships:** 1:N scenario_assumption; 1:N forecast_run

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `scenario_id` | string | Y |  |  | Y |  |  |
| `scenario_name` | string | Y |  |  | Y |  |  |
| `scenario_type` | string | Y | BASE, DELAYED_RECEIPT, STRESS |  |  |  |  |
| `description` | string | Y |  |  |  |  |  |
| `receipt_delay_days` | integer | Y |  | days |  |  | >= 0; added to expected receipt dates |
| `payable_acceleration_days` | integer | Y |  | days |  |  | >= 0; payments pulled forward |
| `receivable_haircut_pct` | decimal(4dp) | Y |  | fraction |  |  | 0..1; credit-loss haircut on receipts |
| `one_off_outflow_multiplier` | decimal(4dp) | Y |  | x |  |  | >= 1 |
| `fx_shock_pct` | decimal(4dp) | Y |  | fraction |  |  | applied to non-USD -> USD plan rate; negative = depreciation |
| `overdue_rollover_days` | integer | Y |  | days |  |  | overdue items assumed to clear this many days after run date |
| `effective_from` | date | Y |  |  |  |  |  |
| `effective_to` | date | N |  |  |  |  |  |
| `status` | string | Y | ACTIVE, RETIRED |  |  |  |  |
| `created_by_role` | string | Y | ACCOUNT_HOLDER, OPERATIONS_ANALYST, RISK_COMPLIANCE_REVIEWER, SYSTEM_ADMIN, SYSTEM |  |  |  |  |

## `scenario_assumption`

One documented parameter per row; must equal liquidity_scenario columns.

- **Primary key:** `assumption_id`  (ID pattern `^ASM-\d{4}$`)
- **Cardinality / relationships:** N:1 liquidity_scenario
- **Composite uniqueness:** (scenario_id, parameter_name)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `assumption_id` | string | Y |  |  | Y |  |  |
| `scenario_id` | string | Y |  |  |  | liquidity_scenario.scenario_id |  |
| `parameter_name` | string | Y |  |  |  |  |  |
| `parameter_value` | decimal(4dp) | Y |  |  |  |  |  |
| `unit` | string | Y |  |  |  |  |  |
| `rationale` | string | Y |  |  |  |  |  |

## `forecast_run`

A versioned execution of a scenario at a run date.

- **Primary key:** `run_id`  (ID pattern `^FCAST-2026-\d{2}-\d{2}-\d{3}$`)
- **Cardinality / relationships:** N:1 liquidity_scenario; N:M legal_entity via forecast_run_entity; N:M cash_flow_forecast via forecast_run_item; 1:N forecast_daily_position; 1:N forecast_vs_actual; self-reference supersedes (optional)
- **Lifecycle:** CREATED -> CALCULATED -> APPROVED | EXCEPTIONS_FLAGGED -> APPROVED|REJECTED ; REJECTED|APPROVED -> SUPERSEDED

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `run_id` | string | Y |  |  | Y |  | FCAST-YYYY-MM-DD-### (run date, per-date sequence); immutable |
| `run_date` | date | Y |  |  |  |  | forecast as-of date (first day of horizon) |
| `data_cutoff_date` | date | Y |  |  |  |  | = run_date - 1; no actual after this date may be used |
| `horizon_start` | date | Y |  |  |  |  | = run_date |
| `horizon_end` | date | Y |  |  |  |  | = run_date + 90 |
| `scenario_id` | string | Y |  |  |  | liquidity_scenario.scenario_id |  |
| `run_version` | integer | Y |  |  |  |  | >= 1; incremented by re-runs |
| `supersedes_run_id` | string | N |  |  |  | forecast_run.run_id | earlier run of same date/scenario |
| `status` | string | Y | CREATED, CALCULATED, EXCEPTIONS_FLAGGED, APPROVED, REJECTED, SUPERSEDED |  |  |  | current state; history in state_event |
| `created_by_role` | string | Y | ACCOUNT_HOLDER, OPERATIONS_ANALYST, RISK_COMPLIANCE_REVIEWER, SYSTEM_ADMIN, SYSTEM |  |  |  |  |
| `line_count` | integer | Y |  |  |  |  | derived = rows in forecast_run_item |
| `entities_in_scope` | integer | Y |  |  |  |  | derived from forecast_run_entity |
| `opening_position_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | derived: in-scope balances at cutoff x plan FX |
| `total_inflow_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | derived from lines |
| `total_outflow_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | derived from lines |
| `closing_position_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | derived: sum of entity projections at horizon end |
| `min_position_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | derived: min over horizon of group projection |
| `min_position_date` | date | Y |  |  |  |  |  |
| `entities_breaching_buffer` | integer | Y |  |  |  |  | entities projected below min_liquidity_buffer on any day |
| `breach_entity_days` | integer | Y |  |  |  |  | entity-days below buffer |
| `fx_status` | string | Y | OK, STALE_CARRY |  |  |  | STALE_CARRY if a plan rate was carried forward |
| `exception_count` | integer | Y |  |  |  |  | run-level exceptions detected at calculation time |
| `review_decision` | string | Y | APPROVED, APPROVED_WITH_EXCEPTIONS, REJECTED |  |  |  | reviewer decision according to documented rule |
| `input_checksum` | string | Y |  |  |  |  | sha256 of canonical line content (reproducibility) |

## `forecast_run_entity`

Bridge: entities in/out of scope per run (N:M).

- **Primary key:** `run_id, entity_id`  (ID pattern `^FCAST-2026-\d{2}-\d{2}-\d{3}\|ENT-\d{6}$`)
- **Cardinality / relationships:** bridge between forecast_run and legal_entity (N:M)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `run_id` | string | Y |  |  |  | forecast_run.run_id |  |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `included` | boolean | Y |  |  |  |  |  |
| `exclusion_reason` | string | N | ENTITY_CLOSED, ENTITY_DORMANT |  |  |  | required iff included=false |
| `opening_position_usd_minor` | integer | N |  | USD minor units (cents) |  |  | required iff included |

## `forecast_run_item`

Bridge: snapshot of each forecast item as used by a run/scenario (N:M).

- **Primary key:** `line_id`  (ID pattern `^RITEM-2026-\d{7}$`)
- **Cardinality / relationships:** bridge forecast_run N:M cash_flow_forecast
- **Composite uniqueness:** (run_id, cf_id)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `line_id` | string | Y |  |  | Y |  |  |
| `run_id` | string | Y |  |  |  | forecast_run.run_id |  |
| `cf_id` | string | Y |  |  |  | cash_flow_forecast.cf_id | (run_id, cf_id) must be unique (else DOUBLE_COUNT anomaly) |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id | = cash_flow_forecast.entity_id |
| `base_date` | date | Y |  |  |  |  | expected date known at cutoff (revised if revised_at <= cutoff) |
| `effective_date` | date | Y |  |  |  |  | scenario-adjusted date; within [run_date, horizon_end] |
| `scheduled_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | remaining amount at cutoff (scheduled - settled by cutoff) |
| `adjusted_amount_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | scenario-adjusted amount (haircut / one-off multiplier) |
| `currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  |  |
| `direction` | string | Y | INFLOW, OUTFLOW |  |  |  |  |
| `fx_rate_to_usd` | decimal(8dp) | Y |  | USD per 1 unit |  |  | plan rate at cutoff x (1+scenario fx shock) |
| `adjusted_amount_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | round(adjusted_amount x fx_rate_to_usd) |
| `amount_basis` | string | Y | SCHEDULED, ACTUAL |  |  |  | ACTUAL is only valid if actual ledger date <= data_cutoff_date |
| `actual_ledger_id` | string | N |  |  |  | ledger_entry.ledger_id | only when amount_basis=ACTUAL |

## `daily_cash_position`

Derived actual daily cash position per bank account.

- **Primary key:** `position_id`  (ID pattern `^POS-2026-\d{8}$`)
- **Cardinality / relationships:** N:1 bank_account
- **Composite uniqueness:** (account_id, position_date)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `position_id` | string | Y |  |  | Y |  |  |
| `account_id` | string | Y |  |  |  | bank_account.account_id |  |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `position_date` | date | Y |  |  |  |  | calendar day, 2026-01-01 .. min(cutoff, closed_date) |
| `currency` | string | Y | USD, EUR, GBP, INR, SGD |  |  |  |  |
| `opening_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | = previous day's closing |
| `inflow_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | sum of credits |
| `outflow_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | sum of debits (positive) |
| `closing_minor` | integer | Y |  | minor units of the row's currency (1/100) |  |  | = opening + inflow - outflow |
| `entry_count` | integer | Y |  |  |  |  |  |
| `fx_rate_to_usd` | decimal(8dp) | N |  |  |  |  | null when fx_status=MISSING |
| `fx_rate_date` | date | N |  |  |  |  | date of the rate used (carry-forward <= 3 days) |
| `fx_status` | string | Y | OK, STALE_CARRY, MISSING |  |  |  |  |
| `closing_usd_minor` | integer | N |  | USD minor units (cents) |  |  | round(closing x rate); null when MISSING |
| `is_overdrawn` | boolean | Y |  |  |  |  | closing < 0 |

## `forecast_daily_position`

Projected daily position per run and in-scope entity (USD).

- **Primary key:** `fdp_id`  (ID pattern `^FDP-2026-\d{8}$`)
- **Cardinality / relationships:** N:1 forecast_run; N:1 legal_entity
- **Composite uniqueness:** (run_id, entity_id, position_date)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `fdp_id` | string | Y |  |  | Y |  |  |
| `run_id` | string | Y |  |  |  | forecast_run.run_id |  |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `position_date` | date | Y |  |  |  |  | run_date .. horizon_end |
| `projected_closing_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | sum_ccy plan_rate x (balance at cutoff + cumulative lines + run-rate) |
| `buffer_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | = legal_entity.min_liquidity_buffer_usd_minor |
| `below_buffer` | boolean | Y |  |  |  |  | projected < buffer |
| `shortfall_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | max(0, buffer - projected) |

## `forecast_vs_actual`

Actual-versus-forecast variance with additive driver decomposition.

- **Primary key:** `comparison_id`  (ID pattern `^CMP-2026-\d{7}$`)
- **Cardinality / relationships:** N:1 forecast_run; N:1 legal_entity
- **Composite uniqueness:** (run_id, entity_id, comparison_date)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `comparison_id` | string | Y |  |  | Y |  |  |
| `run_id` | string | Y |  |  |  | forecast_run.run_id |  |
| `entity_id` | string | Y |  |  |  | legal_entity.entity_id |  |
| `comparison_date` | date | Y |  |  |  |  | weekly checkpoint <= data cutoff |
| `horizon_day` | integer | Y |  | days |  |  | comparison_date - data_cutoff_date |
| `forecast_closing_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | = forecast_daily_position value |
| `actual_closing_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | actual ledger balances x actual FX of the day |
| `variance_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | actual - forecast |
| `variance_pct` | decimal(6dp) | N |  | fraction |  |  | variance / |forecast|; null if forecast = 0 |
| `timing_effect_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | items settled earlier/later than scheduled |
| `amount_effect_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | settled amount differs from scheduled (partial pay, haircut) |
| `unscheduled_flow_effect_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | actual unscheduled flows minus run-rate |
| `fx_effect_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | actual FX vs plan FX on actual balances |
| `double_count_effect_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | duplicated forecast lines |
| `rounding_residual_usd_minor` | integer | Y |  | USD minor units (cents) |  |  | variance - sum(effects); |.| <= 5 |
| `primary_driver` | string | Y | TIMING, AMOUNT, UNSCHEDULED_FLOWS, FX, DOUBLE_COUNT, NONE |  |  |  | effect with the largest absolute value |
| `explanation_status` | string | Y | EXPLAINED, UNEXPLAINED |  |  |  | EXPLAINED iff |residual| <= tolerance |

## `state_event`

Append-only lifecycle history for all stateful objects (no overwrites).

- **Primary key:** `event_id`  (ID pattern `^EVT-2026-\d{8}$`)
- **Cardinality / relationships:** N:1 any lifecycle object
- **Composite uniqueness:** (object_type, object_id, sequence_no)

| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |
|---|---|---|---|---|---|---|---|
| `event_id` | string | Y |  |  | Y |  |  |
| `object_type` | string | Y | LEGAL_ENTITY, BANK_ACCOUNT, RECEIVABLE, PAYABLE, CASH_FLOW_FORECAST, FORECAST_RUN |  |  |  |  |
| `object_id` | string | Y |  |  |  |  | id of the object in its own table (polymorphic; validated in code) |
| `sequence_no` | integer | Y |  |  |  |  | 1..n per object, contiguous |
| `from_state` | string | N |  |  |  |  | NULL for creation event; must equal previous to_state |
| `to_state` | string | Y |  |  |  |  |  |
| `event_ts` | datetime | Y |  |  |  |  | non-decreasing per object |
| `actor_role` | string | Y | ACCOUNT_HOLDER, OPERATIONS_ANALYST, RISK_COMPLIANCE_REVIEWER, SYSTEM_ADMIN, SYSTEM |  |  |  |  |
| `reason_code` | string | Y |  |  |  |  |  |

## Lifecycle transition graphs (enforced by validation)

- **LEGAL_ENTITY**: NEW -> ACTIVE; ACTIVE -> DORMANT/CLOSED; DORMANT -> ACTIVE/CLOSED
- **BANK_ACCOUNT**: NEW -> OPEN; OPEN -> FROZEN/CLOSED; FROZEN -> OPEN/CLOSED
- **RECEIVABLE**: NEW -> OPEN; OPEN -> OVERDUE/PARTIALLY_PAID/PAID/CANCELLED/WRITTEN_OFF; OVERDUE -> PARTIALLY_PAID/PAID/WRITTEN_OFF; PARTIALLY_PAID -> OVERDUE/PAID/WRITTEN_OFF
- **PAYABLE**: NEW -> OPEN; OPEN -> OVERDUE/PARTIALLY_PAID/PAID/CANCELLED; OVERDUE -> PARTIALLY_PAID/PAID; PARTIALLY_PAID -> OVERDUE/PAID
- **CASH_FLOW_FORECAST**: NEW -> SCHEDULED; SCHEDULED -> DELAYED/PARTIALLY_REALIZED/REALIZED/CANCELLED/WRITTEN_OFF; DELAYED -> PARTIALLY_REALIZED/REALIZED/WRITTEN_OFF; PARTIALLY_REALIZED -> DELAYED/REALIZED/WRITTEN_OFF
- **FORECAST_RUN**: NEW -> CREATED; CREATED -> CALCULATED; CALCULATED -> APPROVED/EXCEPTIONS_FLAGGED; EXCEPTIONS_FLAGGED -> APPROVED/REJECTED; REJECTED -> SUPERSEDED; APPROVED -> SUPERSEDED
