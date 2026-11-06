-- Generated from liquidity/schema.py. Compatible with SQLite 3.23+ and PostgreSQL.

CREATE TABLE legal_entity (
  entity_id TEXT NOT NULL,
  legal_name TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('HOLDING', 'OPERATING', 'SPV', 'TREASURY_CENTRE')),
  country_code TEXT NOT NULL CHECK (country_code IN ('US', 'DE', 'FR', 'NL', 'GB', 'IN', 'SG')),
  functional_currency TEXT NOT NULL CHECK (functional_currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  parent_entity_id TEXT,
  size_tier TEXT NOT NULL CHECK (size_tier IN ('SMALL', 'MEDIUM', 'LARGE')),
  status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DORMANT', 'CLOSED')),
  status_since DATE NOT NULL,
  incorporation_date DATE NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  min_liquidity_buffer_usd_minor BIGINT NOT NULL,
  PRIMARY KEY (entity_id),
  UNIQUE (legal_name),
  FOREIGN KEY (parent_entity_id) REFERENCES legal_entity(entity_id)
);

CREATE TABLE bank_account (
  account_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  bank_name TEXT NOT NULL,
  account_type TEXT NOT NULL CHECK (account_type IN ('OPERATING', 'COLLECTION', 'PAYROLL', 'RESERVE', 'FX')),
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'FROZEN', 'CLOSED')),
  opened_date DATE NOT NULL,
  closed_date DATE,
  opening_balance_date DATE NOT NULL,
  opening_balance_minor BIGINT NOT NULL,
  overdraft_limit_minor BIGINT NOT NULL,
  statement_date DATE NOT NULL,
  statement_closing_balance_minor BIGINT NOT NULL,
  PRIMARY KEY (account_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id)
);

CREATE TABLE ledger_entry (
  ledger_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  entry_date DATE NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  direction TEXT NOT NULL CHECK (direction IN ('CREDIT', 'DEBIT')),
  amount_minor BIGINT NOT NULL,
  signed_amount_minor BIGINT NOT NULL,
  balance_after_minor BIGINT NOT NULL,
  entry_type TEXT NOT NULL CHECK (entry_type IN ('CUSTOMER_RECEIPT', 'SUPPLIER_PAYMENT', 'PAYROLL', 'TAX_PAYMENT', 'LOAN_REPAYMENT', 'CAPEX_PAYMENT', 'CARD_SETTLEMENT', 'MISC_RECEIPT', 'INTEREST_CREDIT', 'BANK_FEE', 'MISC_PAYMENT', 'ACCOUNT_CLOSURE_SWEEP')),
  cf_id TEXT,
  source_ref_id TEXT,
  counterparty_ref TEXT,
  description TEXT NOT NULL,
  posting_status TEXT NOT NULL CHECK (posting_status IN ('POSTED')),
  PRIMARY KEY (ledger_id),
  FOREIGN KEY (account_id) REFERENCES bank_account(account_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id),
  FOREIGN KEY (cf_id) REFERENCES cash_flow_forecast(cf_id)
);

CREATE TABLE receivable (
  receivable_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  counterparty_ref TEXT NOT NULL,
  counterparty_risk_tier TEXT NOT NULL CHECK (counterparty_risk_tier IN ('LOW', 'MEDIUM', 'HIGH')),
  invoice_date DATE NOT NULL,
  due_date DATE NOT NULL,
  payment_terms_days BIGINT NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  invoice_amount_minor BIGINT NOT NULL,
  settled_amount_minor BIGINT NOT NULL,
  outstanding_minor BIGINT NOT NULL,
  last_payment_date DATE,
  days_past_due_at_cutoff BIGINT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'OVERDUE', 'PARTIALLY_PAID', 'PAID', 'WRITTEN_OFF', 'CANCELLED')),
  terminal_date DATE,
  status_as_of_date DATE NOT NULL,
  PRIMARY KEY (receivable_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id),
  FOREIGN KEY (account_id) REFERENCES bank_account(account_id)
);

CREATE TABLE payable (
  payable_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  supplier_ref TEXT NOT NULL,
  supplier_tier TEXT NOT NULL CHECK (supplier_tier IN ('CRITICAL', 'STANDARD', 'DEFERRABLE')),
  category TEXT NOT NULL CHECK (category IN ('SUPPLIER_PAYMENT', 'PAYROLL', 'TAX_PAYMENT', 'LOAN_REPAYMENT', 'CAPEX_ONE_OFF')),
  is_large_one_off BOOLEAN NOT NULL,
  invoice_date DATE NOT NULL,
  due_date DATE NOT NULL,
  payment_terms_days BIGINT NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  invoice_amount_minor BIGINT NOT NULL,
  settled_amount_minor BIGINT NOT NULL,
  outstanding_minor BIGINT NOT NULL,
  last_payment_date DATE,
  days_past_due_at_cutoff BIGINT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'OVERDUE', 'PARTIALLY_PAID', 'PAID', 'CANCELLED')),
  terminal_date DATE,
  status_as_of_date DATE NOT NULL,
  PRIMARY KEY (payable_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id),
  FOREIGN KEY (account_id) REFERENCES bank_account(account_id)
);

CREATE TABLE cash_flow_forecast (
  cf_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  receivable_id TEXT,
  payable_id TEXT,
  direction TEXT NOT NULL CHECK (direction IN ('INFLOW', 'OUTFLOW')),
  category TEXT NOT NULL CHECK (category IN ('CUSTOMER_RECEIPT', 'SUPPLIER_PAYMENT', 'PAYROLL', 'TAX_PAYMENT', 'LOAN_REPAYMENT', 'CAPEX_ONE_OFF')),
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  scheduled_amount_minor BIGINT NOT NULL,
  expected_date DATE NOT NULL,
  revised_expected_date DATE,
  revised_at DATE,
  created_date DATE NOT NULL,
  confidence_score NUMERIC(20,8) NOT NULL,
  is_large_one_off BOOLEAN NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('SCHEDULED', 'DELAYED', 'PARTIALLY_REALIZED', 'REALIZED', 'WRITTEN_OFF', 'CANCELLED')),
  realized_amount_minor BIGINT NOT NULL,
  realized_date DATE,
  terminal_date DATE,
  PRIMARY KEY (cf_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id),
  FOREIGN KEY (account_id) REFERENCES bank_account(account_id),
  FOREIGN KEY (receivable_id) REFERENCES receivable(receivable_id),
  UNIQUE (receivable_id),
  FOREIGN KEY (payable_id) REFERENCES payable(payable_id),
  UNIQUE (payable_id)
);

CREATE TABLE currency_rate (
  rate_id TEXT NOT NULL,
  rate_date DATE NOT NULL,
  from_currency TEXT NOT NULL CHECK (from_currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  to_currency TEXT NOT NULL CHECK (to_currency IN ('USD')),
  rate NUMERIC(20,8) NOT NULL,
  rate_type TEXT NOT NULL CHECK (rate_type IN ('SPOT_CLOSE')),
  source TEXT NOT NULL CHECK (source IN ('SYNTHETIC_RANDOM_WALK')),
  PRIMARY KEY (rate_id),
  UNIQUE (from_currency, rate_date)
);

CREATE TABLE liquidity_scenario (
  scenario_id TEXT NOT NULL,
  scenario_name TEXT NOT NULL,
  scenario_type TEXT NOT NULL CHECK (scenario_type IN ('BASE', 'DELAYED_RECEIPT', 'STRESS')),
  description TEXT NOT NULL,
  receipt_delay_days BIGINT NOT NULL,
  payable_acceleration_days BIGINT NOT NULL,
  receivable_haircut_pct NUMERIC(20,8) NOT NULL,
  one_off_outflow_multiplier NUMERIC(20,8) NOT NULL,
  fx_shock_pct NUMERIC(20,8) NOT NULL,
  overdue_rollover_days BIGINT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED')),
  created_by_role TEXT NOT NULL CHECK (created_by_role IN ('ACCOUNT_HOLDER', 'OPERATIONS_ANALYST', 'RISK_COMPLIANCE_REVIEWER', 'SYSTEM_ADMIN', 'SYSTEM')),
  PRIMARY KEY (scenario_id),
  UNIQUE (scenario_name)
);

CREATE TABLE scenario_assumption (
  assumption_id TEXT NOT NULL,
  scenario_id TEXT NOT NULL,
  parameter_name TEXT NOT NULL,
  parameter_value NUMERIC(20,8) NOT NULL,
  unit TEXT NOT NULL,
  rationale TEXT NOT NULL,
  PRIMARY KEY (assumption_id),
  UNIQUE (scenario_id, parameter_name),
  FOREIGN KEY (scenario_id) REFERENCES liquidity_scenario(scenario_id)
);

CREATE TABLE forecast_run (
  run_id TEXT NOT NULL,
  run_date DATE NOT NULL,
  data_cutoff_date DATE NOT NULL,
  horizon_start DATE NOT NULL,
  horizon_end DATE NOT NULL,
  scenario_id TEXT NOT NULL,
  run_version BIGINT NOT NULL,
  supersedes_run_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('CREATED', 'CALCULATED', 'EXCEPTIONS_FLAGGED', 'APPROVED', 'REJECTED', 'SUPERSEDED')),
  created_by_role TEXT NOT NULL CHECK (created_by_role IN ('ACCOUNT_HOLDER', 'OPERATIONS_ANALYST', 'RISK_COMPLIANCE_REVIEWER', 'SYSTEM_ADMIN', 'SYSTEM')),
  line_count BIGINT NOT NULL,
  entities_in_scope BIGINT NOT NULL,
  opening_position_usd_minor BIGINT NOT NULL,
  total_inflow_usd_minor BIGINT NOT NULL,
  total_outflow_usd_minor BIGINT NOT NULL,
  closing_position_usd_minor BIGINT NOT NULL,
  min_position_usd_minor BIGINT NOT NULL,
  min_position_date DATE NOT NULL,
  entities_breaching_buffer BIGINT NOT NULL,
  breach_entity_days BIGINT NOT NULL,
  fx_status TEXT NOT NULL CHECK (fx_status IN ('OK', 'STALE_CARRY')),
  exception_count BIGINT NOT NULL,
  review_decision TEXT NOT NULL CHECK (review_decision IN ('APPROVED', 'APPROVED_WITH_EXCEPTIONS', 'REJECTED')),
  input_checksum TEXT NOT NULL,
  PRIMARY KEY (run_id),
  FOREIGN KEY (scenario_id) REFERENCES liquidity_scenario(scenario_id),
  FOREIGN KEY (supersedes_run_id) REFERENCES forecast_run(run_id)
);

CREATE TABLE forecast_run_entity (
  run_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  included BOOLEAN NOT NULL,
  exclusion_reason TEXT CHECK (exclusion_reason IN ('ENTITY_CLOSED', 'ENTITY_DORMANT')),
  opening_position_usd_minor BIGINT,
  PRIMARY KEY (run_id, entity_id),
  FOREIGN KEY (run_id) REFERENCES forecast_run(run_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id)
);

CREATE TABLE forecast_run_item (
  line_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  cf_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  base_date DATE NOT NULL,
  effective_date DATE NOT NULL,
  scheduled_amount_minor BIGINT NOT NULL,
  adjusted_amount_minor BIGINT NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  direction TEXT NOT NULL CHECK (direction IN ('INFLOW', 'OUTFLOW')),
  fx_rate_to_usd NUMERIC(20,8) NOT NULL,
  adjusted_amount_usd_minor BIGINT NOT NULL,
  amount_basis TEXT NOT NULL CHECK (amount_basis IN ('SCHEDULED', 'ACTUAL')),
  actual_ledger_id TEXT,
  PRIMARY KEY (line_id),
  -- soft rule (checked by validation V15, not a DB constraint): UNIQUE (run_id, cf_id),
  FOREIGN KEY (run_id) REFERENCES forecast_run(run_id),
  FOREIGN KEY (cf_id) REFERENCES cash_flow_forecast(cf_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id),
  FOREIGN KEY (actual_ledger_id) REFERENCES ledger_entry(ledger_id)
);

CREATE TABLE daily_cash_position (
  position_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  position_date DATE NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR', 'SGD')),
  opening_minor BIGINT NOT NULL,
  inflow_minor BIGINT NOT NULL,
  outflow_minor BIGINT NOT NULL,
  closing_minor BIGINT NOT NULL,
  entry_count BIGINT NOT NULL,
  fx_rate_to_usd NUMERIC(20,8),
  fx_rate_date DATE,
  fx_status TEXT NOT NULL CHECK (fx_status IN ('OK', 'STALE_CARRY', 'MISSING')),
  closing_usd_minor BIGINT,
  is_overdrawn BOOLEAN NOT NULL,
  PRIMARY KEY (position_id),
  UNIQUE (account_id, position_date),
  FOREIGN KEY (account_id) REFERENCES bank_account(account_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id)
);

CREATE TABLE forecast_daily_position (
  fdp_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  position_date DATE NOT NULL,
  projected_closing_usd_minor BIGINT NOT NULL,
  buffer_usd_minor BIGINT NOT NULL,
  below_buffer BOOLEAN NOT NULL,
  shortfall_usd_minor BIGINT NOT NULL,
  PRIMARY KEY (fdp_id),
  UNIQUE (run_id, entity_id, position_date),
  FOREIGN KEY (run_id) REFERENCES forecast_run(run_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id)
);

CREATE TABLE forecast_vs_actual (
  comparison_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  comparison_date DATE NOT NULL,
  horizon_day BIGINT NOT NULL,
  forecast_closing_usd_minor BIGINT NOT NULL,
  actual_closing_usd_minor BIGINT NOT NULL,
  variance_usd_minor BIGINT NOT NULL,
  variance_pct NUMERIC(20,8),
  timing_effect_usd_minor BIGINT NOT NULL,
  amount_effect_usd_minor BIGINT NOT NULL,
  unscheduled_flow_effect_usd_minor BIGINT NOT NULL,
  fx_effect_usd_minor BIGINT NOT NULL,
  double_count_effect_usd_minor BIGINT NOT NULL,
  rounding_residual_usd_minor BIGINT NOT NULL,
  primary_driver TEXT NOT NULL CHECK (primary_driver IN ('TIMING', 'AMOUNT', 'UNSCHEDULED_FLOWS', 'FX', 'DOUBLE_COUNT', 'NONE')),
  explanation_status TEXT NOT NULL CHECK (explanation_status IN ('EXPLAINED', 'UNEXPLAINED')),
  PRIMARY KEY (comparison_id),
  UNIQUE (run_id, entity_id, comparison_date),
  FOREIGN KEY (run_id) REFERENCES forecast_run(run_id),
  FOREIGN KEY (entity_id) REFERENCES legal_entity(entity_id)
);

CREATE TABLE state_event (
  event_id TEXT NOT NULL,
  object_type TEXT NOT NULL CHECK (object_type IN ('LEGAL_ENTITY', 'BANK_ACCOUNT', 'RECEIVABLE', 'PAYABLE', 'CASH_FLOW_FORECAST', 'FORECAST_RUN')),
  object_id TEXT NOT NULL,
  sequence_no BIGINT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  event_ts TIMESTAMP NOT NULL,
  actor_role TEXT NOT NULL CHECK (actor_role IN ('ACCOUNT_HOLDER', 'OPERATIONS_ANALYST', 'RISK_COMPLIANCE_REVIEWER', 'SYSTEM_ADMIN', 'SYSTEM')),
  reason_code TEXT NOT NULL,
  PRIMARY KEY (event_id),
  UNIQUE (object_type, object_id, sequence_no)
);
