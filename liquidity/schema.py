"""Single source of truth for tables, fields, enums, FKs, lifecycles.

Drives: CSV/JSON/SQL export, DDL, validation (PK/FK/enum/required/regex) and the
generated data dictionary (docs/DATA_DICTIONARY.md, schema/data_dictionary.json).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .config import CURRENCIES

# ----------------------------------------------------------------------------- enums
ENTITY_TYPES = ("HOLDING", "OPERATING", "SPV", "TREASURY_CENTRE")
COUNTRIES = ("US", "DE", "FR", "NL", "GB", "IN", "SG")
SIZE_TIERS = ("SMALL", "MEDIUM", "LARGE")
ENTITY_STATUS = ("ACTIVE", "DORMANT", "CLOSED")
ACCOUNT_TYPES = ("OPERATING", "COLLECTION", "PAYROLL", "RESERVE", "FX")
ACCOUNT_STATUS = ("OPEN", "FROZEN", "CLOSED")
DIRECTIONS = ("CREDIT", "DEBIT")
ENTRY_TYPES = ("CUSTOMER_RECEIPT", "SUPPLIER_PAYMENT", "PAYROLL", "TAX_PAYMENT", "LOAN_REPAYMENT",
               "CAPEX_PAYMENT", "CARD_SETTLEMENT", "MISC_RECEIPT", "INTEREST_CREDIT", "BANK_FEE",
               "MISC_PAYMENT", "ACCOUNT_CLOSURE_SWEEP")
POSTING_STATUS = ("POSTED",)
RISK_TIERS = ("LOW", "MEDIUM", "HIGH")
SUPPLIER_TIERS = ("CRITICAL", "STANDARD", "DEFERRABLE")
PAYABLE_CATEGORIES = ("SUPPLIER_PAYMENT", "PAYROLL", "TAX_PAYMENT", "LOAN_REPAYMENT", "CAPEX_ONE_OFF")
DOC_STATUS_R = ("OPEN", "OVERDUE", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF", "CANCELLED")
DOC_STATUS_P = ("OPEN", "OVERDUE", "PARTIALLY_PAID", "PAID", "CANCELLED")
CF_DIRECTIONS = ("INFLOW", "OUTFLOW")
CF_CATEGORIES = ("CUSTOMER_RECEIPT",) + PAYABLE_CATEGORIES
CF_STATUS = ("SCHEDULED", "DELAYED", "PARTIALLY_REALIZED", "REALIZED", "WRITTEN_OFF", "CANCELLED")
SCENARIO_TYPES = ("BASE", "DELAYED_RECEIPT", "STRESS")
SCENARIO_STATUS = ("ACTIVE", "RETIRED")
RUN_STATUS = ("CREATED", "CALCULATED", "EXCEPTIONS_FLAGGED", "APPROVED", "REJECTED", "SUPERSEDED")
REVIEW_DECISIONS = ("APPROVED", "APPROVED_WITH_EXCEPTIONS", "REJECTED")
FX_RUN_STATUS = ("OK", "STALE_CARRY")
FX_STATUS = ("OK", "STALE_CARRY", "MISSING")
AMOUNT_BASIS = ("SCHEDULED", "ACTUAL")
ACTOR_ROLES = ("ACCOUNT_HOLDER", "OPERATIONS_ANALYST", "RISK_COMPLIANCE_REVIEWER", "SYSTEM_ADMIN", "SYSTEM")
OBJECT_TYPES = ("LEGAL_ENTITY", "BANK_ACCOUNT", "RECEIVABLE", "PAYABLE", "CASH_FLOW_FORECAST", "FORECAST_RUN")
DRIVERS = ("TIMING", "AMOUNT", "UNSCHEDULED_FLOWS", "FX", "DOUBLE_COUNT", "NONE")
EXPLANATION_STATUS = ("EXPLAINED", "UNEXPLAINED")

# lifecycle graphs: object_type -> {from_state: (allowed to_states)}; None = creation
TRANSITIONS: Dict[str, Dict[object, Tuple[str, ...]]] = {
    "LEGAL_ENTITY": {None: ("ACTIVE",), "ACTIVE": ("DORMANT", "CLOSED"), "DORMANT": ("ACTIVE", "CLOSED")},
    "BANK_ACCOUNT": {None: ("OPEN",), "OPEN": ("FROZEN", "CLOSED"), "FROZEN": ("OPEN", "CLOSED")},
    "RECEIVABLE": {None: ("OPEN",),
                   "OPEN": ("OVERDUE", "PARTIALLY_PAID", "PAID", "CANCELLED", "WRITTEN_OFF"),
                   "OVERDUE": ("PARTIALLY_PAID", "PAID", "WRITTEN_OFF"),
                   "PARTIALLY_PAID": ("OVERDUE", "PAID", "WRITTEN_OFF")},
    "PAYABLE": {None: ("OPEN",),
                "OPEN": ("OVERDUE", "PARTIALLY_PAID", "PAID", "CANCELLED"),
                "OVERDUE": ("PARTIALLY_PAID", "PAID"),
                "PARTIALLY_PAID": ("OVERDUE", "PAID")},
    "CASH_FLOW_FORECAST": {None: ("SCHEDULED",),
                           "SCHEDULED": ("DELAYED", "PARTIALLY_REALIZED", "REALIZED", "CANCELLED", "WRITTEN_OFF"),
                           "DELAYED": ("PARTIALLY_REALIZED", "REALIZED", "WRITTEN_OFF"),
                           "PARTIALLY_REALIZED": ("DELAYED", "REALIZED", "WRITTEN_OFF")},
    "FORECAST_RUN": {None: ("CREATED",), "CREATED": ("CALCULATED",),
                     "CALCULATED": ("APPROVED", "EXCEPTIONS_FLAGGED"),
                     "EXCEPTIONS_FLAGGED": ("APPROVED", "REJECTED"),
                     "REJECTED": ("SUPERSEDED",), "APPROVED": ("SUPERSEDED",)},
}


# ----------------------------------------------------------------------------- model
@dataclass(frozen=True)
class Field:
    name: str
    type: str = "string"        # string | integer | decimal | date | datetime | boolean
    required: bool = True
    allowed: Tuple = ()
    unit: str = ""
    unique: bool = False
    rule: str = ""
    fk: str = ""                # "table.column"
    scale: int = 0              # decimals for type=decimal


@dataclass(frozen=True)
class Table:
    name: str
    pk: Tuple[str, ...]
    description: str
    id_pattern: str
    fields: Tuple[Field, ...]
    cardinality: str = ""
    lifecycle: str = ""
    unique_together: Tuple[Tuple[str, ...], ...] = ()

    @property
    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]


def F(name, type="string", req=True, allowed=(), unit="", uniq=False, rule="", fk="", scale=0):
    return Field(name, type, req, tuple(allowed), unit, uniq, rule, fk, scale)


USD_MINOR = "minor units of the row's currency (1/100)"
USD_REP = "USD minor units (cents)"

TABLES: List[Table] = [
    Table("legal_entity", ("entity_id",), "Legal entities of the group (master data, parent of everything).",
          r"^ENT-\d{6}$", (
        F("entity_id", uniq=True, rule="ENT-###### zero padded; immutable"),
        F("legal_name", uniq=True, rule="synthetic name; no real companies"),
        F("entity_type", allowed=ENTITY_TYPES),
        F("country_code", allowed=COUNTRIES, rule="ISO 3166-1 alpha-2"),
        F("functional_currency", allowed=CURRENCIES, rule="ISO 4217; drives default account currency"),
        F("parent_entity_id", req=False, fk="legal_entity.entity_id", rule="optional; parent id < own id (acyclic); NULL for holding"),
        F("size_tier", allowed=SIZE_TIERS, rule="derived from relative transaction scale"),
        F("status", allowed=ENTITY_STATUS, rule="current lifecycle state; history in state_event"),
        F("status_since", "date", rule=">= effective_from"),
        F("incorporation_date", "date"),
        F("effective_from", "date", rule="= incorporation_date"),
        F("effective_to", "date", req=False, rule="required iff status=CLOSED; > effective_from"),
        F("min_liquidity_buffer_usd_minor", "integer", unit=USD_REP,
          rule=">= 0; derived = 2.0 x mean monthly payables (USD-equivalent at opening FX)"),
    ), cardinality="1:N bank_account; 1:N receivable/payable/cash_flow_forecast; self-reference N:1 parent (optional); "
                   "N:M forecast_run via forecast_run_entity",
        lifecycle="ACTIVE -> DORMANT|CLOSED ; DORMANT -> ACTIVE|CLOSED"),

    Table("bank_account", ("account_id",), "Bank accounts held by legal entities.", r"^BANKACC-ENT-\d{6}-\d{3}$", (
        F("account_id", uniq=True, rule="BANKACC-<entity-id>-### ; immutable"),
        F("entity_id", fk="legal_entity.entity_id"),
        F("bank_name", rule="synthetic bank name"),
        F("account_type", allowed=ACCOUNT_TYPES),
        F("currency", allowed=CURRENCIES, rule="ISO 4217; every ledger entry on the account must use this currency"),
        F("status", allowed=ACCOUNT_STATUS, rule="current state; history in state_event"),
        F("opened_date", "date", rule="<= opening_balance_date; >= entity.effective_from"),
        F("closed_date", "date", req=False, rule="required iff status=CLOSED; >= opened_date"),
        F("opening_balance_date", "date", rule="= 2025-12-31 (end-of-day balance)"),
        F("opening_balance_minor", "integer", unit=USD_MINOR, rule=">= 0"),
        F("overdraft_limit_minor", "integer", unit=USD_MINOR, rule=">= 0"),
        F("statement_date", "date", rule="bank statement as-of date = closed_date or data cutoff"),
        F("statement_closing_balance_minor", "integer", unit=USD_MINOR,
          rule="bank-reported closing balance; must equal opening + sum(ledger) unless labelled BALANCE_MISMATCH"),
    ), cardinality="N:1 legal_entity; 1:N ledger_entry; 1:N daily_cash_position",
        lifecycle="OPEN <-> FROZEN ; OPEN|FROZEN -> CLOSED"),

    Table("ledger_entry", ("ledger_id",), "Posted bank ledger movements (actuals).", r"^LED-2026-\d{8}$", (
        F("ledger_id", uniq=True, rule="LED-2026-######## ; chronological order"),
        F("account_id", fk="bank_account.account_id"),
        F("entity_id", fk="legal_entity.entity_id", rule="must equal bank_account.entity_id"),
        F("entry_date", "date", rule=">= 2026-01-01 and <= data cutoff; business day"),
        F("currency", allowed=CURRENCIES, rule="must equal bank_account.currency (else MIXED_CURRENCY anomaly)"),
        F("direction", allowed=DIRECTIONS),
        F("amount_minor", "integer", unit=USD_MINOR, rule="> 0"),
        F("signed_amount_minor", "integer", unit=USD_MINOR, rule="+amount for CREDIT, -amount for DEBIT"),
        F("balance_after_minor", "integer", unit=USD_MINOR, rule="running balance = opening + cumulative signed"),
        F("entry_type", allowed=ENTRY_TYPES),
        F("cf_id", req=False, fk="cash_flow_forecast.cf_id", rule="set for settlements of scheduled items"),
        F("source_ref_id", req=False, rule="RCV-/PAY- id of the settled document (consistent with cf_id)"),
        F("counterparty_ref", req=False, rule="pseudonymous reference"),
        F("description"),
        F("posting_status", allowed=POSTING_STATUS),
    ), cardinality="N:1 bank_account; N:1 cash_flow_forecast (optional, 0..N settlements per item)"),

    Table("receivable", ("receivable_id",), "Scheduled customer invoices (expected cash inflows).",
          r"^RCV-2026-\d{6}$", (
        F("receivable_id", uniq=True),
        F("entity_id", fk="legal_entity.entity_id"),
        F("account_id", fk="bank_account.account_id", rule="receiving account; same entity; same currency as invoice"),
        F("counterparty_ref", rule="CUST-####; pseudonymous"),
        F("counterparty_risk_tier", allowed=RISK_TIERS, rule="drives payment delay / partial / write-off behaviour"),
        F("invoice_date", "date"),
        F("due_date", "date", rule=">= invoice_date + 1; business day"),
        F("payment_terms_days", "integer", unit="days", rule="due_date - invoice_date"),
        F("currency", allowed=CURRENCIES),
        F("invoice_amount_minor", "integer", unit=USD_MINOR, rule="> 0"),
        F("settled_amount_minor", "integer", unit=USD_MINOR, rule="derived = sum of linked ledger credits"),
        F("outstanding_minor", "integer", unit=USD_MINOR, rule="derived = invoice - settled while OPEN/OVERDUE/PARTIALLY_PAID else 0"),
        F("last_payment_date", "date", req=False, rule="derived from ledger"),
        F("days_past_due_at_cutoff", "integer", unit="days", rule="derived; 0 if nothing outstanding"),
        F("status", allowed=DOC_STATUS_R, rule="derived from state_event chain"),
        F("terminal_date", "date", req=False, rule="date PAID/WRITTEN_OFF/CANCELLED reached"),
        F("status_as_of_date", "date", rule="= data cutoff"),
    ), cardinality="1:1 cash_flow_forecast (optional); N:1 legal_entity; N:1 bank_account",
        lifecycle="OPEN -> OVERDUE|PARTIALLY_PAID|PAID|CANCELLED|WRITTEN_OFF ; OVERDUE <-> PARTIALLY_PAID ; ... -> PAID|WRITTEN_OFF"),

    Table("payable", ("payable_id",), "Scheduled supplier/payroll/tax/loan/capex payments (expected outflows).",
          r"^PAY-2026-\d{6}$", (
        F("payable_id", uniq=True),
        F("entity_id", fk="legal_entity.entity_id"),
        F("account_id", fk="bank_account.account_id", rule="paying account; same entity"),
        F("supplier_ref", rule="SUPP-#### / INTERNAL-PAYROLL / TAXAUTH-xx / LENDER-xx"),
        F("supplier_tier", allowed=SUPPLIER_TIERS),
        F("category", allowed=PAYABLE_CATEGORIES),
        F("is_large_one_off", "boolean", rule="true iff category = CAPEX_ONE_OFF"),
        F("invoice_date", "date"),
        F("due_date", "date", rule=">= invoice_date + 1; business day"),
        F("payment_terms_days", "integer", unit="days"),
        F("currency", allowed=CURRENCIES),
        F("invoice_amount_minor", "integer", unit=USD_MINOR, rule="> 0"),
        F("settled_amount_minor", "integer", unit=USD_MINOR, rule="derived from ledger debits"),
        F("outstanding_minor", "integer", unit=USD_MINOR, rule="derived"),
        F("last_payment_date", "date", req=False),
        F("days_past_due_at_cutoff", "integer", unit="days"),
        F("status", allowed=DOC_STATUS_P),
        F("terminal_date", "date", req=False),
        F("status_as_of_date", "date"),
    ), cardinality="1:1 cash_flow_forecast (optional); N:1 legal_entity; N:1 bank_account",
        lifecycle="OPEN -> OVERDUE|PARTIALLY_PAID|PAID|CANCELLED ; OVERDUE <-> PARTIALLY_PAID"),

    Table("cash_flow_forecast", ("cf_id",), "Forecast item: one expected cash flow derived from exactly one receivable or payable.",
          r"^CF-2026-\d{6}$", (
        F("cf_id", uniq=True, rule="CF-2026-######"),
        F("entity_id", fk="legal_entity.entity_id"),
        F("account_id", fk="bank_account.account_id"),
        F("receivable_id", req=False, fk="receivable.receivable_id", uniq=True, rule="exactly one of receivable_id/payable_id"),
        F("payable_id", req=False, fk="payable.payable_id", uniq=True, rule="exactly one of receivable_id/payable_id"),
        F("direction", allowed=CF_DIRECTIONS, rule="INFLOW iff receivable"),
        F("category", allowed=CF_CATEGORIES),
        F("currency", allowed=CURRENCIES, rule="= bank_account.currency"),
        F("scheduled_amount_minor", "integer", unit=USD_MINOR, rule="> 0; = document invoice amount"),
        F("expected_date", "date", rule="original expected cash date (business day); immutable"),
        F("revised_expected_date", "date", req=False, rule="> expected_date; only with revised_at"),
        F("revised_at", "date", req=False, rule=">= created_date and < expected_date; date the revision became known"),
        F("created_date", "date", rule="date the item entered the forecast (= invoice_date)"),
        F("confidence_score", "decimal", scale=4, rule="0..1; derived from counterparty tier and revision"),
        F("is_large_one_off", "boolean"),
        F("status", allowed=CF_STATUS, rule="derived from state_event chain"),
        F("realized_amount_minor", "integer", unit=USD_MINOR, rule="derived = sum of linked ledger entries"),
        F("realized_date", "date", req=False, rule="date of last linked ledger entry"),
        F("terminal_date", "date", req=False, rule="date REALIZED/WRITTEN_OFF/CANCELLED reached"),
    ), cardinality="1:1 receivable|payable; 1:N ledger_entry (settlements); N:M forecast_run via forecast_run_item",
        lifecycle="SCHEDULED -> DELAYED|PARTIALLY_REALIZED|REALIZED|CANCELLED|WRITTEN_OFF ; DELAYED <-> PARTIALLY_REALIZED"),

    Table("currency_rate", ("rate_id",), "Daily FX rates (USD per 1 unit of currency). Missing rows are labelled anomalies.",
          r"^RATE-2026-\d{6}$", (
        F("rate_id", uniq=True, rule="never renumbered when a row is removed"),
        F("rate_date", "date", rule="effective date of the rate"),
        F("from_currency", allowed=CURRENCIES),
        F("to_currency", allowed=("USD",), rule="reporting currency"),
        F("rate", "decimal", scale=8, unit="USD per 1 unit", rule="> 0; USD = 1"),
        F("rate_type", allowed=("SPOT_CLOSE",)),
        F("source", allowed=("SYNTHETIC_RANDOM_WALK",)),
    ), unique_together=(("from_currency", "rate_date"),),
        cardinality="referenced logically by currency+date from ledger/position/forecast conversions"),

    Table("liquidity_scenario", ("scenario_id",), "Scenario definitions (documented assumptions).",
          r"^SCN-[A-Z]+$", (
        F("scenario_id", uniq=True),
        F("scenario_name", uniq=True),
        F("scenario_type", allowed=SCENARIO_TYPES),
        F("description"),
        F("receipt_delay_days", "integer", unit="days", rule=">= 0; added to expected receipt dates"),
        F("payable_acceleration_days", "integer", unit="days", rule=">= 0; payments pulled forward"),
        F("receivable_haircut_pct", "decimal", scale=4, unit="fraction", rule="0..1; credit-loss haircut on receipts"),
        F("one_off_outflow_multiplier", "decimal", scale=4, unit="x", rule=">= 1"),
        F("fx_shock_pct", "decimal", scale=4, unit="fraction", rule="applied to non-USD -> USD plan rate; negative = depreciation"),
        F("overdue_rollover_days", "integer", unit="days", rule="overdue items assumed to clear this many days after run date"),
        F("effective_from", "date"),
        F("effective_to", "date", req=False),
        F("status", allowed=SCENARIO_STATUS),
        F("created_by_role", allowed=ACTOR_ROLES),
    ), cardinality="1:N scenario_assumption; 1:N forecast_run"),

    Table("scenario_assumption", ("assumption_id",), "One documented parameter per row; must equal liquidity_scenario columns.",
          r"^ASM-\d{4}$", (
        F("assumption_id", uniq=True),
        F("scenario_id", fk="liquidity_scenario.scenario_id"),
        F("parameter_name"),
        F("parameter_value", "decimal", scale=4),
        F("unit"),
        F("rationale"),
    ), unique_together=(("scenario_id", "parameter_name"),), cardinality="N:1 liquidity_scenario"),

    Table("forecast_run", ("run_id",), "A versioned execution of a scenario at a run date.",
          r"^FCAST-2026-\d{2}-\d{2}-\d{3}$", (
        F("run_id", uniq=True, rule="FCAST-YYYY-MM-DD-### (run date, per-date sequence); immutable"),
        F("run_date", "date", rule="forecast as-of date (first day of horizon)"),
        F("data_cutoff_date", "date", rule="= run_date - 1; no actual after this date may be used"),
        F("horizon_start", "date", rule="= run_date"),
        F("horizon_end", "date", rule="= run_date + 90"),
        F("scenario_id", fk="liquidity_scenario.scenario_id"),
        F("run_version", "integer", rule=">= 1; incremented by re-runs"),
        F("supersedes_run_id", req=False, fk="forecast_run.run_id", rule="earlier run of same date/scenario"),
        F("status", allowed=RUN_STATUS, rule="current state; history in state_event"),
        F("created_by_role", allowed=ACTOR_ROLES),
        F("line_count", "integer", rule="derived = rows in forecast_run_item"),
        F("entities_in_scope", "integer", rule="derived from forecast_run_entity"),
        F("opening_position_usd_minor", "integer", unit=USD_REP, rule="derived: in-scope balances at cutoff x plan FX"),
        F("total_inflow_usd_minor", "integer", unit=USD_REP, rule="derived from lines"),
        F("total_outflow_usd_minor", "integer", unit=USD_REP, rule="derived from lines"),
        F("closing_position_usd_minor", "integer", unit=USD_REP, rule="derived: sum of entity projections at horizon end"),
        F("min_position_usd_minor", "integer", unit=USD_REP, rule="derived: min over horizon of group projection"),
        F("min_position_date", "date"),
        F("entities_breaching_buffer", "integer", rule="entities projected below min_liquidity_buffer on any day"),
        F("breach_entity_days", "integer", rule="entity-days below buffer"),
        F("fx_status", allowed=FX_RUN_STATUS, rule="STALE_CARRY if a plan rate was carried forward"),
        F("exception_count", "integer", rule="run-level exceptions detected at calculation time"),
        F("review_decision", allowed=REVIEW_DECISIONS, rule="reviewer decision according to documented rule"),
        F("input_checksum", rule="sha256 of canonical line content (reproducibility)"),
    ), cardinality="N:1 liquidity_scenario; N:M legal_entity via forecast_run_entity; N:M cash_flow_forecast via forecast_run_item; "
                   "1:N forecast_daily_position; 1:N forecast_vs_actual; self-reference supersedes (optional)",
        lifecycle="CREATED -> CALCULATED -> APPROVED | EXCEPTIONS_FLAGGED -> APPROVED|REJECTED ; REJECTED|APPROVED -> SUPERSEDED"),

    Table("forecast_run_entity", ("run_id", "entity_id"), "Bridge: entities in/out of scope per run (N:M).",
          r"^FCAST-2026-\d{2}-\d{2}-\d{3}\|ENT-\d{6}$", (
        F("run_id", fk="forecast_run.run_id"),
        F("entity_id", fk="legal_entity.entity_id"),
        F("included", "boolean"),
        F("exclusion_reason", req=False, allowed=("ENTITY_CLOSED", "ENTITY_DORMANT"), rule="required iff included=false"),
        F("opening_position_usd_minor", "integer", req=False, unit=USD_REP, rule="required iff included"),
    ), cardinality="bridge between forecast_run and legal_entity (N:M)"),

    Table("forecast_run_item", ("line_id",), "Bridge: snapshot of each forecast item as used by a run/scenario (N:M).",
          r"^RITEM-2026-\d{7}$", (
        F("line_id", uniq=True),
        F("run_id", fk="forecast_run.run_id"),
        F("cf_id", fk="cash_flow_forecast.cf_id", rule="(run_id, cf_id) must be unique (else DOUBLE_COUNT anomaly)"),
        F("entity_id", fk="legal_entity.entity_id", rule="= cash_flow_forecast.entity_id"),
        F("base_date", "date", rule="expected date known at cutoff (revised if revised_at <= cutoff)"),
        F("effective_date", "date", rule="scenario-adjusted date; within [run_date, horizon_end]"),
        F("scheduled_amount_minor", "integer", unit=USD_MINOR, rule="remaining amount at cutoff (scheduled - settled by cutoff)"),
        F("adjusted_amount_minor", "integer", unit=USD_MINOR, rule="scenario-adjusted amount (haircut / one-off multiplier)"),
        F("currency", allowed=CURRENCIES),
        F("direction", allowed=CF_DIRECTIONS),
        F("fx_rate_to_usd", "decimal", scale=8, unit="USD per 1 unit", rule="plan rate at cutoff x (1+scenario fx shock)"),
        F("adjusted_amount_usd_minor", "integer", unit=USD_REP, rule="round(adjusted_amount x fx_rate_to_usd)"),
        F("amount_basis", allowed=AMOUNT_BASIS, rule="ACTUAL is only valid if actual ledger date <= data_cutoff_date"),
        F("actual_ledger_id", req=False, fk="ledger_entry.ledger_id", rule="only when amount_basis=ACTUAL"),
    ), unique_together=(("run_id", "cf_id"),), cardinality="bridge forecast_run N:M cash_flow_forecast"),

    Table("daily_cash_position", ("position_id",), "Derived actual daily cash position per bank account.",
          r"^POS-2026-\d{8}$", (
        F("position_id", uniq=True),
        F("account_id", fk="bank_account.account_id"),
        F("entity_id", fk="legal_entity.entity_id"),
        F("position_date", "date", rule="calendar day, 2026-01-01 .. min(cutoff, closed_date)"),
        F("currency", allowed=CURRENCIES),
        F("opening_minor", "integer", unit=USD_MINOR, rule="= previous day's closing"),
        F("inflow_minor", "integer", unit=USD_MINOR, rule="sum of credits"),
        F("outflow_minor", "integer", unit=USD_MINOR, rule="sum of debits (positive)"),
        F("closing_minor", "integer", unit=USD_MINOR, rule="= opening + inflow - outflow"),
        F("entry_count", "integer"),
        F("fx_rate_to_usd", "decimal", req=False, scale=8, rule="null when fx_status=MISSING"),
        F("fx_rate_date", "date", req=False, rule="date of the rate used (carry-forward <= 3 days)"),
        F("fx_status", allowed=FX_STATUS),
        F("closing_usd_minor", "integer", req=False, unit=USD_REP, rule="round(closing x rate); null when MISSING"),
        F("is_overdrawn", "boolean", rule="closing < 0"),
    ), unique_together=(("account_id", "position_date"),), cardinality="N:1 bank_account"),

    Table("forecast_daily_position", ("fdp_id",), "Projected daily position per run and in-scope entity (USD).",
          r"^FDP-2026-\d{8}$", (
        F("fdp_id", uniq=True),
        F("run_id", fk="forecast_run.run_id"),
        F("entity_id", fk="legal_entity.entity_id"),
        F("position_date", "date", rule="run_date .. horizon_end"),
        F("projected_closing_usd_minor", "integer", unit=USD_REP,
          rule="sum_ccy plan_rate x (balance at cutoff + cumulative lines + run-rate)"),
        F("buffer_usd_minor", "integer", unit=USD_REP, rule="= legal_entity.min_liquidity_buffer_usd_minor"),
        F("below_buffer", "boolean", rule="projected < buffer"),
        F("shortfall_usd_minor", "integer", unit=USD_REP, rule="max(0, buffer - projected)"),
    ), unique_together=(("run_id", "entity_id", "position_date"),), cardinality="N:1 forecast_run; N:1 legal_entity"),

    Table("forecast_vs_actual", ("comparison_id",), "Actual-versus-forecast variance with additive driver decomposition.",
          r"^CMP-2026-\d{7}$", (
        F("comparison_id", uniq=True),
        F("run_id", fk="forecast_run.run_id"),
        F("entity_id", fk="legal_entity.entity_id"),
        F("comparison_date", "date", rule="weekly checkpoint <= data cutoff"),
        F("horizon_day", "integer", unit="days", rule="comparison_date - data_cutoff_date"),
        F("forecast_closing_usd_minor", "integer", unit=USD_REP, rule="= forecast_daily_position value"),
        F("actual_closing_usd_minor", "integer", unit=USD_REP, rule="actual ledger balances x actual FX of the day"),
        F("variance_usd_minor", "integer", unit=USD_REP, rule="actual - forecast"),
        F("variance_pct", "decimal", req=False, scale=6, unit="fraction", rule="variance / |forecast|; null if forecast = 0"),
        F("timing_effect_usd_minor", "integer", unit=USD_REP, rule="items settled earlier/later than scheduled"),
        F("amount_effect_usd_minor", "integer", unit=USD_REP, rule="settled amount differs from scheduled (partial pay, haircut)"),
        F("unscheduled_flow_effect_usd_minor", "integer", unit=USD_REP, rule="actual unscheduled flows minus run-rate"),
        F("fx_effect_usd_minor", "integer", unit=USD_REP, rule="actual FX vs plan FX on actual balances"),
        F("double_count_effect_usd_minor", "integer", unit=USD_REP, rule="duplicated forecast lines"),
        F("rounding_residual_usd_minor", "integer", unit=USD_REP, rule="variance - sum(effects); |.| <= 5"),
        F("primary_driver", allowed=DRIVERS, rule="effect with the largest absolute value"),
        F("explanation_status", allowed=EXPLANATION_STATUS, rule="EXPLAINED iff |residual| <= tolerance"),
    ), unique_together=(("run_id", "entity_id", "comparison_date"),), cardinality="N:1 forecast_run; N:1 legal_entity"),

    Table("state_event", ("event_id",), "Append-only lifecycle history for all stateful objects (no overwrites).",
          r"^EVT-2026-\d{8}$", (
        F("event_id", uniq=True),
        F("object_type", allowed=OBJECT_TYPES),
        F("object_id", rule="id of the object in its own table (polymorphic; validated in code)"),
        F("sequence_no", "integer", rule="1..n per object, contiguous"),
        F("from_state", req=False, rule="NULL for creation event; must equal previous to_state"),
        F("to_state"),
        F("event_ts", "datetime", rule="non-decreasing per object"),
        F("actor_role", allowed=ACTOR_ROLES),
        F("reason_code"),
    ), unique_together=(("object_type", "object_id", "sequence_no"),), cardinality="N:1 any lifecycle object"),
]

TABLE_MAP: Dict[str, Table] = {t.name: t for t in TABLES}
TABLE_ORDER = [t.name for t in TABLES]   # parents before children (dependency order)


def foreign_keys() -> List[Tuple[str, str, str, str]]:
    out = []
    for t in TABLES:
        for f in t.fields:
            if f.fk:
                rt, rc = f.fk.split(".")
                out.append((t.name, f.name, rt, rc))
    return out


# ----------------------------------------------------------------------------- rendering
def fmt_value(f: Field, v) -> str:
    if v is None:
        return ""
    if f.type == "boolean":
        return "true" if v else "false"
    if f.type == "decimal":
        return f"{v:.{f.scale}f}"
    if f.type in ("date", "datetime"):
        return v.isoformat()
    return str(v)


def render_dictionary_md() -> str:
    L = ["# Data Dictionary", "",
         "Generated from `liquidity/schema.py` (single source of truth). Amount fields ending `_minor` are integers in "
         "currency minor units (1/100). `*_usd_minor` are USD cents. Dates are ISO-8601.", ""]
    for t in TABLES:
        L += [f"## `{t.name}`", "", t.description, "",
              f"- **Primary key:** `{', '.join(t.pk)}`  (ID pattern `{t.id_pattern}`)",
              f"- **Cardinality / relationships:** {t.cardinality or 'n/a'}"]
        if t.lifecycle:
            L.append(f"- **Lifecycle:** {t.lifecycle}")
        if t.unique_together:
            L.append("- **Composite uniqueness:** " + "; ".join("(" + ", ".join(u) + ")" for u in t.unique_together))
        L += ["", "| Field | Type | Req | Allowed values | Unit | Unique | FK | Validation rule |",
              "|---|---|---|---|---|---|---|---|"]
        for f in t.fields:
            typ = f.type + (f"({f.scale}dp)" if f.type == "decimal" else "")
            allowed = ", ".join(f.allowed) if f.allowed else ""
            L.append(f"| `{f.name}` | {typ} | {'Y' if f.required else 'N'} | {allowed} | {f.unit} | "
                     f"{'Y' if f.unique else ''} | {f.fk} | {f.rule} |")
        L.append("")
    L += ["## Lifecycle transition graphs (enforced by validation)", ""]
    for ot, g in TRANSITIONS.items():
        L.append(f"- **{ot}**: " + "; ".join(f"{k or 'NEW'} -> {'/'.join(v)}" for k, v in g.items()))
    return "\n".join(L) + "\n"


def dictionary_json() -> dict:
    return {t.name: {"primary_key": list(t.pk), "id_pattern": t.id_pattern, "description": t.description,
                     "cardinality": t.cardinality, "lifecycle": t.lifecycle,
                     "unique_together": [list(u) for u in t.unique_together],
                     "fields": [{"name": f.name, "type": f.type, "required": f.required,
                                 "allowed": list(f.allowed), "unit": f.unit, "unique": f.unique,
                                 "foreign_key": f.fk, "rule": f.rule} for f in t.fields]}
            for t in TABLES}


_SQL_TYPES = {"string": "TEXT", "integer": "BIGINT", "decimal": "NUMERIC(20,8)", "date": "DATE",
              "datetime": "TIMESTAMP", "boolean": "BOOLEAN"}


def render_ddl() -> str:
    L = ["-- Generated from liquidity/schema.py. Compatible with SQLite 3.23+ and PostgreSQL.", ""]
    for t in TABLES:
        cols = []
        for f in t.fields:
            c = f"  {f.name} {_SQL_TYPES[f.type]}"
            if f.required:
                c += " NOT NULL"
            if f.allowed:
                c += " CHECK (" + f.name + " IN (" + ", ".join("'" + a + "'" for a in f.allowed) + "))"
            cols.append(c)
        cols.append(f"  PRIMARY KEY ({', '.join(t.pk)})")
        for u in t.unique_together:
            if t.name == "forecast_run_item":      # soft rule: labelled DOUBLE_COUNT rows violate it on purpose
                cols.append(f"  -- soft rule (checked by validation V15, not a DB constraint): UNIQUE ({', '.join(u)})")
                continue
            cols.append(f"  UNIQUE ({', '.join(u)})")
        for f in t.fields:
            if f.fk:
                rt, rc = f.fk.split(".")
                cols.append(f"  FOREIGN KEY ({f.name}) REFERENCES {rt}({rc})")
            if f.unique and f.name not in t.pk and f.name in ("receivable_id", "payable_id", "legal_name", "scenario_name"):
                cols.append(f"  UNIQUE ({f.name})")
        L.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(cols) + "\n);\n")
    return "\n".join(L)
