"""Tests for the month-block bootstrap."""
import numpy as np
import pandas as pd
import pytest

from vpin import uncertainty as U


def test_draws_resample_every_month_count():
    w = U.draws(12, reps=50, seed=1)
    assert w.shape == (50, 12)
    assert np.all(w.sum(axis=1) == 12)          # each replication draws 12 months


def test_corr_from_sums_matches_numpy():
    rng = np.random.default_rng(0)
    x, y = rng.normal(size=500), rng.normal(size=500)
    y = y + 0.5 * x
    t = np.array([c.sum() for c in U.corr_columns(x, y)])
    assert U.corr_from_sums(t) == pytest.approx(np.corrcoef(x, y)[0, 1])


def test_bootstrap_point_equals_full_sample_and_se_shrinks_with_more_data():
    rng = np.random.default_rng(2)
    def se_for(n_months):
        months = np.repeat(np.arange(n_months), 100)
        x = rng.normal(size=len(months))
        sums = U.monthly_sums(months, [np.ones_like(x), x], n_months)
        res = U.bootstrap(sums, {"mean": lambda t: t[1] / t[0]}, reps=300)["mean"]
        assert res["value"] == pytest.approx(x.mean())
        return res["se"]
    assert se_for(80) < se_for(10)


def test_ols_delta_r2_matches_direct_regression():
    rng = np.random.default_rng(3)
    n = 2000
    X = rng.normal(size=(n, 2))
    y = 1 + 2 * X[:, 0] + 0.5 * X[:, 1] + rng.normal(size=n)
    ts = pd.date_range("2020-01-01", periods=n, freq="6h")
    res = U.ols_delta_r2(X, y, extra=1, ts=ts, reps=50)

    def r2(cols):
        Z = np.column_stack([np.ones(n)] + cols)
        beta, *_ = np.linalg.lstsq(Z, y, rcond=None)
        return 1 - np.var(y - Z @ beta) / np.var(y)
    assert res["r2_full"]["value"] == pytest.approx(r2([X[:, 0], X[:, 1]]))
    assert res["delta_r2"]["value"] == pytest.approx(r2([X[:, 0], X[:, 1]]) - r2([X[:, 0]]))
