"""Deterministic, zero-padded, immutable identifiers."""
from __future__ import annotations

import datetime as dt


def entity_id(i: int) -> str: return f"ENT-{i:06d}"
def account_id(eid: str, n: int) -> str: return f"BANKACC-{eid}-{n:03d}"
def ledger_id(i: int) -> str: return f"LED-2026-{i:08d}"
def cf_id(i: int) -> str: return f"CF-2026-{i:06d}"
def run_id(d: dt.date, seq: int) -> str: return f"FCAST-{d.isoformat()}-{seq:03d}"
def receivable_id(i: int) -> str: return f"RCV-2026-{i:06d}"
def payable_id(i: int) -> str: return f"PAY-2026-{i:06d}"
def rate_id(i: int) -> str: return f"RATE-2026-{i:06d}"
def assumption_id(i: int) -> str: return f"ASM-{i:04d}"
def event_id(i: int) -> str: return f"EVT-2026-{i:08d}"
def run_item_id(i: int) -> str: return f"RITEM-2026-{i:07d}"
def position_id(i: int) -> str: return f"POS-2026-{i:08d}"
def fdp_id(i: int) -> str: return f"FDP-2026-{i:08d}"
def comparison_id(i: int) -> str: return f"CMP-2026-{i:07d}"
def anomaly_id(i: int) -> str: return f"ANOM-{i:04d}"
