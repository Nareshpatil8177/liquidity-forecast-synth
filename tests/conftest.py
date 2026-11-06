import os
import pytest

from liquidity.cli import build
from liquidity.config import STARTER, Scale
from liquidity.export import load_ground_truth, load_run_decisions, load_tables

SEED = 20261022


@pytest.fixture(scope="session")
def starter(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("starter"))
    t, v, rep, man, _ = build(out, STARTER, SEED, ["csv", "json", "sql"], False, "pytest")
    return dict(dir=out, mem=t, validation=v, report=rep, manifest=man,
                T=load_tables(out), GT=load_ground_truth(out), RD=load_run_decisions(out))


@pytest.fixture(scope="session")
def tiny_dir(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("tiny"))
    build(out, Scale("custom", 4, 5, 2500, 400), 7, ["csv"], False, "pytest")
    return out
