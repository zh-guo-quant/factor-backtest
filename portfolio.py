"""Turn factor scorres into long-short portfolio weights on rebalance dates.

Everything here is a pure function of information available at date t. Weights are stamped with t; the one-day lag to execution is applied in backtest.py, never here.

Outputcontract (per rebalance date that forms a portfolio):
-----------------------------------------------------------
buckets : 1..N_BUCKETS for eligible stocks, NaN otherwise (N = highest scores)
weights : +1 / n_top on the top bucket, -1 / n_bottom on the bottom bucket, 0 elsewhere. sum(weights) = 0, sum(|weights|) = 2
-----------------------------------------------------------
"""

from typing import NamedTuple

import numpy as np
import pandas as pd

import config

class Portfolio(NamedTuple):
    """Target holdings stamped with their signal dates."""
    weights: pd.DataFrame
    buckets: pd.DataFrame


#--- Building blocks------------------------------------------------------------------------------------

def rebalance_dates(index: pd.DatetimeIndex, freq: str = config.REBALANCE) -> pd.DatetimeIndex:
    """The last trading day in each period, taken from the panel's own dates."""
    last = pd.Series(index, index = index).resample(freq).max().dropna()
    return pd.DatetimeIndex(last.to_numpy(), name = index.name)

def eligible(factor: pd.DataFrame, tradable: pd.DataFrame) -> pd.DataFrame:
    """Stocks that may enter the sort: a signal exists and the stock is tradable at time t."""
    return factor.notna() & tradable

def assign_buckets(factor: pd.DataFrame, mask: pd.DataFrame, n_buckets: int) -> pd.DataFrame:
    """Cross-sectional bucket 1..n_buckets per date; NaN for ineligible stocks."""
    scores = factor.where(mask)
    ranks = scores.rank(axis = 1, method = "first")
    n = mask.sum(axis = 1)
    buckets = np.ceil(ranks.mul(n_buckets).div(n, axis = 0))
    return buckets.where(n >= n_buckets, axis = 0)

def long_short_weights(buckets: pd.DataFrame, n_buckets: int) -> pd.DataFrame:
    """Equal-weight long the top bucket, equal-weight short the bottom bucket."""
    top = (buckets == n_buckets).astype(float)
    bottom = (buckets == 1).astype(float)
    return top.div(top.sum(axis = 1), axis = 0) - bottom.div(bottom.sum(axis = 1), axis = 0)

def _bucket_counts(buckets: pd.DataFrame, n_buckets: int) -> pd.DataFrame:
    """Number of stocks in each bucket, one row per date, one column per bucket."""
    return pd.concat({k: (buckets == k).sum(axis = 1) for k in range(1, n_buckets + 1)}, axis = 1)

def _validate_portfolio(p: Portfolio, mask: pd.DataFrame, n_buckets: int) -> None:
    """Post-conditions every portfolio must satisfy."""
    w, b = p.weights, p.buckets
    if not (w.index.equals(b.index) and w.columns.equals(b.columns)):
        raise ValueError(
            f"weights and buckets are not aligned."
        )

    net = w.sum(axis = 1).abs().max()
    gross = (w.abs().sum(axis = 1) - 2).abs().max()
    if net > 1e-9 or gross > 1e-9:
        raise ValueError(
            f"not dollar-neutral 1/1: max |net| {net:.2e}, max |gross| {gross:.2e}."
        )
    if ((w != 0) & ~mask.loc[w.index]).any().any():
        raise ValueError(
            f"weight assigned to an ineligible stock."
        )

    counts = _bucket_counts(b, n_buckets)
    if (counts ==0).any().any():
        raise ValueError(
            f"a bucket is empty on some date."
        )

    spread = (counts.max(axis = 1) - counts.min(axis = 1)).max()
    if spread > 1:
        raise ValueError(
            f"bucket sizes differ by {int(spread)} on some date (allowed: 1)."
        )

# --- Public API----------------------------------------------------------------------------------------

def build(
        factor: pd.DataFrame, tradable: pd.DataFrame, n_buckets: int = config.N_BUCKETS
) -> Portfolio:
    """Buckets and long-short weights on every rebalance date that can form one."""
    if not (tradable.index.equals(factor.index) and tradable.columns.equals(factor.columns)):
        raise ValueError(
            f"tradable panel is not aligned with the factor panel."
        ) 

    dates = rebalance_dates(factor.index)
    f = factor.loc[dates]
    mask = eligible(f, tradable.loc[dates])

    buckets = assign_buckets(f, mask, n_buckets).dropna(how = "all")
    weights = long_short_weights(buckets, n_buckets)

    portfolio = Portfolio(weights = weights, buckets = buckets)
    _validate_portfolio(portfolio, mask, n_buckets)
    return portfolio

if __name__ == "__main__":
    import factors as fx
    from data_loader import load_panel

    panels = {"close": load_panel("close")}
    tradable = load_panel("is_tradable")
    for name in fx.FACTORS:
        p = build(fx.compute(name, panels), tradable)
        top = p.buckets == config.N_BUCKETS
        still_top = top & top.shift(-1, fill_value = False)
        n_stay = still_top.sum(axis = 1).iloc[:-1]
        n_top = top.sum(axis = 1).iloc[:-1]
        stay = n_stay / n_top
        sizes = _bucket_counts(p.buckets, config.N_BUCKETS)
        print(f"{name:<10} {len(p.weights):>3} portfolio first {p.weights.index[0].date()} "
              f"bucket size {sizes.min().min()} - {sizes.max().max()} top retention {stay.mean():.1%}")