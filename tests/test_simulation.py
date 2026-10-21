"""Tests for the known-answer simulation."""
import numpy as np
import pytest

from vpin.simulation import BASE, WORLDS, auc, high_blocks, simulate


def test_same_seed_same_market():
    a = simulate(WORLDS["T"], days=3, seed=7)
    b = simulate(WORLDS["T"], days=3, seed=7)
    assert a.equals(b)


def test_informed_share_matches_the_pin_formula():
    """Expected informed share of volume = alpha*mu / (alpha*mu + 2*eps), the paper's PIN."""
    bars = simulate(WORLDS["0"], days=60, seed=1)
    pin = BASE["alpha"] * BASE["mu"] / (BASE["alpha"] * BASE["mu"] + 2 * BASE["eps"])
    assert bars["informed"].sum() / bars["volume"].sum() == pytest.approx(pin, rel=0.05)


def test_volatility_world_changes_volatility_but_not_informed_trading():
    bars = simulate(WORLDS["V"], days=40, seed=2)
    change = np.diff(np.log(bars["close"].to_numpy()), prepend=np.log(100))
    hi, lo = bars["v_high"].to_numpy(), ~bars["v_high"].to_numpy()
    assert change[hi].std() > 2 * change[lo].std()
    informed_rate_hi = bars.loc[hi, "informed"].mean()
    informed_rate_lo = bars.loc[lo, "informed"].mean()
    assert informed_rate_hi == pytest.approx(informed_rate_lo, rel=0.15)


def test_blocks_alternate_starting_low():
    day = np.arange(40)
    assert high_blocks(day, 10).tolist() == [False] * 10 + [True] * 10 + [False] * 10 + [True] * 10


def test_auc_extremes():
    label = np.array([False, False, True, True])
    assert auc(np.array([1, 2, 3, 4]), label) == 1.0
    assert auc(np.array([4, 3, 2, 1]), label) == 0.0
    assert auc(np.array([1, 1, 1, 1]), label) == 0.5
