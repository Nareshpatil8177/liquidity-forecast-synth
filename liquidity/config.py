"""Central configuration: seed, calendar, scale presets, scenario definitions."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

D = dt.date
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261022
YEAR = 2026

CURRENCIES = ("USD", "EUR", "GBP", "INR", "SGD")
REPORTING_CCY = "USD"

# --- calendar ---------------------------------------------------------------
OPENING_DATE = D(2025, 12, 31)      # opening balances are as-of this date (end of day)
HISTORY_START = D(2026, 1, 1)       # first ledger date
DATA_CUTOFF = D(2026, 9, 30)        # last date for which actuals exist
FX_START = OPENING_DATE
FX_END = D(2026, 10, 1)             # last forecast run date needs a rate
PLAN_END = D(2026, 12, 31)          # latest scheduled receivable/payable due date
CLOSE_DATE = D(2026, 5, 29)         # closure date of the CLOSED entity
DORMANT_DATE = D(2026, 8, 14)       # date entities become DORMANT
RUN_DATES = tuple(D(2026, m, 1) for m in range(1, 11))   # monthly forecast runs
HORIZON_DAYS = 91                   # 13 weeks, run_date .. run_date+90
FX_TOLERANCE_DAYS = 3               # max days a rate may be carried forward
COMPARISON_STEP_DAYS = 7            # weekly actual-vs-forecast checkpoints
RECON_TOLERANCE_MINOR = 5           # rounding tolerance for variance decomposition

# --- FX model ---------------------------------------------------------------
FX_START_RATES = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "INR": 0.0120, "SGD": 0.74}  # USD per 1 unit
FX_VOL = {"EUR": 0.0030, "GBP": 0.0035, "INR": 0.0015, "SGD": 0.0020}              # daily sigma
# (currency, start, end, cumulative move) -> documented FX movement events
FX_SHOCKS = [
    ("EUR", D(2026, 3, 18), D(2026, 3, 18), 0.020),
    ("INR", D(2026, 6, 10), D(2026, 6, 20), -0.040),
    ("GBP", D(2026, 8, 5), D(2026, 8, 5), -0.030),
]

# --- scenarios (documented assumptions) ---------------------------------------
SCENARIOS = [
    dict(scenario_id="SCN-BASE", scenario_name="Base case", scenario_type="BASE",
         description="Contractual/expected dates and amounts; overdue items assumed to clear 3 days after run date.",
         receipt_delay_days=0, payable_acceleration_days=0, receivable_haircut_pct=0.0,
         one_off_outflow_multiplier=1.0, fx_shock_pct=0.0, overdue_rollover_days=3),
    dict(scenario_id="SCN-DELAYED", scenario_name="Delayed receipts", scenario_type="DELAYED_RECEIPT",
         description="Customers pay 10 days later than expected; overdue items clear after 7 days.",
         receipt_delay_days=10, payable_acceleration_days=0, receivable_haircut_pct=0.0,
         one_off_outflow_multiplier=1.0, fx_shock_pct=0.0, overdue_rollover_days=7),
    dict(scenario_id="SCN-STRESS", scenario_name="Liquidity stress", scenario_type="STRESS",
         description="Receipts 21 days late with 10% credit-loss haircut, suppliers paid 5 days early, "
                     "one-off payments +25%, non-USD currencies -8% vs USD, overdue items clear after 14 days.",
         receipt_delay_days=21, payable_acceleration_days=5, receivable_haircut_pct=0.10,
         one_off_outflow_multiplier=1.25, fx_shock_pct=-0.08, overdue_rollover_days=14),
]

# --- anomaly volumes at FULL scale (scaled by ledger/100000, min 2) --------------
ANOMALY_BASE_COUNTS = dict(balance_mismatch=10, mixed_currency=25, fx_missing_random=10,
                           double_count=40, leak=15)


@dataclass(frozen=True)
class Scale:
    name: str
    entities: int
    accounts_per_entity: int
    ledger: int
    forecast_items: int

    @property
    def factor(self) -> float:
        return self.ledger / 100000.0


FULL = Scale("full", 30, 5, 100000, 20000)
STARTER = Scale("starter", 6, 5, 5000, 1000)
PRESETS = {"full": FULL, "starter": STARTER}
