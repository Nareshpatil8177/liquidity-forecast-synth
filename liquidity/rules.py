"""Documented business rules shared by generator, forecast engine, detectors and validator."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from .config import FX_TOLERANCE_DAYS
from .util import next_bd, td


class FxIndex:
    """Rate lookup with bounded carry-forward.

    lookup() -> (rate, rate_date, status)
      OK           rate exists for the date
      STALE_CARRY  missing; last available rate within FX_TOLERANCE_DAYS is carried forward (flagged)
      MISSING      no rate within tolerance; USD conversion is blocked (value NULL)
    """

    def __init__(self, rows):
        self.m = {(r["from_currency"], r["rate_date"]): r["rate"] for r in rows}

    def lookup(self, ccy: str, d: dt.date) -> Tuple[Optional[float], Optional[dt.date], str]:
        if ccy == "USD":
            return 1.0, d, "OK"
        r = self.m.get((ccy, d))
        if r is not None:
            return r, d, "OK"
        for k in range(1, FX_TOLERANCE_DAYS + 1):
            dd = d - td(k)
            r = self.m.get((ccy, dd))
            if r is not None:
                return r, dd, "STALE_CARRY"
        return None, None, "MISSING"


def fx_decision(position_in_gap: int) -> str:
    """Documented decision for the n-th consecutive missing daily rate."""
    return "CARRY_FORWARD_WITH_FLAG" if position_in_gap <= FX_TOLERANCE_DAYS else "BLOCK_USD_CONVERSION_UNTIL_RATE_LOADED"


def apply_scenario(sc: dict, direction: str, large: bool, known_date: dt.date,
                   run_date: dt.date, remaining: int) -> Tuple[dt.date, int]:
    """Scenario-adjusted (effective_date, adjusted_amount) for one remaining item.

    * overdue item (known_date < run_date): clears run_date + overdue_rollover_days
    * receipts: known_date + receipt_delay_days (not earlier than run_date)
    * payments: known_date - payable_acceleration_days (not earlier than run_date)
    * receipts are reduced by receivable_haircut_pct; large one-off payments multiplied
    """
    if known_date < run_date:
        eff = run_date + td(sc["overdue_rollover_days"])
    else:
        if direction == "INFLOW":
            eff = known_date + td(sc["receipt_delay_days"])
        else:
            eff = known_date - td(sc["payable_acceleration_days"])
        if eff < run_date:
            eff = run_date
    eff = next_bd(eff)
    if direction == "INFLOW":
        adj = int(round(remaining * (1.0 - sc["receivable_haircut_pct"])))
    else:
        adj = int(round(remaining * (sc["one_off_outflow_multiplier"] if large else 1.0)))
    return eff, adj
