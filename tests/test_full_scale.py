"""Slow: verifies the required baseline volume. Run with:  RUN_FULL=1 pytest -m slow"""
import os
import pytest

from liquidity.cli import build
from liquidity.config import FULL

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not os.environ.get("RUN_FULL"), reason="set RUN_FULL=1 to run the 100k-row build")
def test_full_volume_and_validation(tmp_path):
    _, v, rep, man, _ = build(str(tmp_path / "full"), FULL, 20261022, ["csv"], False, "pytest")
    c = man["row_counts"]
    assert (c["legal_entity"], c["bank_account"], c["ledger_entry"], c["cash_flow_forecast"]) == (30, 150, 100000, 20000)
    assert v["summary"]["failed"] == 0
    assert rep["detection"]["overall"]["recall"] == 1.0
