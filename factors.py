"""Cross-sectional factor signals, computed from the price panel.

Every factor takes the wide close-price panel and returns a panel of the same shape. factor.loc[t, s] is the score fro symbol s from information available at t's close.

Sign convention
---------------
Higher Score = higher expected return, for every factor.

Timing
------
These panels are as-of t. The one-period lag between observing a signal and holding the position is applied once, in backtest.py - never here.
"""

from typing import Callable, Mapping, NamedTuple

import numpy as np
import pandas as pd

import config
from data_loader import load_prices, load_panel

# --- Factor definitions ----------------------------------------------------------------------------

def momentum(close: pd.DataFrame) -> pd.DataFrame:
    """12-month return, skipping the most recent month. Warmup: MOM_LOOKBACK."""
    return close.shift(config.MOM_SKIP) / close.shift(config.MOM_LOOKBACK) - 1

def reversal(close: pd.DataFrame) -> pd.DataFrame:
    """Negated 1-month return - losers are expected to bounce. Warmup: REV_LOOKBACK."""
    return -(close.shift(config.REV_SKIP) / close.shift(config.REV_SKIP + config.REV_LOOKBACK) - 1)

def low_volatility(close: pd.DataFrame) -> pd.DataFrame:
    """Negated trailing volatility of daily returns. Warmup: VOL_LOOKBACK."""
    returns = close.pct_change()
    return -returns.rolling(config.VOL_LOOKBACK).std()

# --- Register factors ---------------------------------------------------------------------------------

class Factor(NamedTuple):
    """A factor and the number of leading rows it cannot produce a value for."""

    fn: Callable[..., pd.DataFrame]
    warmup: int
    inputs: tuple[str, ...] = ("close",)

FACTORS = {
    "momentum": Factor(momentum, config.MOM_LOOKBACK),
    "reversal": Factor(reversal, config.REV_SKIP + config.REV_LOOKBACK),
    "low_vol": Factor(low_volatility, config.VOL_LOOKBACK),
}

# --- public API -----------------------------------------------------------------------------------------

def _validate_factor(
        factor: pd.DataFrame, reference: pd.DataFrame, name: str, warmup: int
) -> None:
    """Post-conditions every factor panel must satisfy."""
    if factor.shape != reference.shape:
        raise ValueError(
            f"{name}: shape {factor.shape} differs from reference {reference.shape}."
        )
    if not factor.index.equals(reference.index):
        raise ValueError(
            f"{name}: index {factor.index} differs from reference {reference.index}."
        )
    if not factor.columns.equals(reference.columns):
        raise ValueError(
            f"{name}: columns {factor.columns} differs from reference {reference.columns}."
        )

    if warmup >= len(factor):
        raise ValueError(
            f"{name}: warmup {warmup} leaves no rows in a {len(factor)}-row panel."
        )
    if factor.iloc[:warmup].notna().to_numpy().any():
        raise ValueError(
            f"{name}: values inside the first {warmup} warm-up rows -"
            f"lookback is shorter than declared."
        )
    if factor.iloc[warmup].isna().all():
        raise ValueError(
            f"{name}: row {warmup} is entirely NaN -"
            f"lookback is longer than declared."
        )

    n_inf = int(np.isinf(factor.to_numpy()).sum())
    if n_inf > 0:
        raise ValueError(
            f"{name}: {n_inf} infinite values found."
        )

def _gather(
        spec: Factor, panels: Mapping[str, pd.DataFrame] | None
) -> dict[str, pd.DataFrame]:
    """The panels a factor declares, taken from 'panels' or loaded on demand."""
    panels = panels or {}
    inputs = {f: panels[f] if f in panels else load_panel(f) for f in spec.inputs}

    ref_name = spec.inputs[0]
    ref = inputs[ref_name]
    for f, panel in inputs.items():
        if not(panel.index.equals(ref.index) and panel.columns.equals(ref.columns)):
            raise ValueError(
                f"input {f!r} is not aligned with {ref_name!r}. "
            )
    return inputs

def compute(name:str, panels: Mapping[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Compute one factor by name. The only supported way to get a factor."""
    try:
        spec = FACTORS[name]
    except KeyError:
        raise KeyError(
            f"Unknown factor {name!r}; known factors: {sorted(FACTORS)}."
        ) from None

    inputs = _gather(spec, panels)
    factor = spec.fn(**inputs)
    _validate_factor(factor, inputs.get(spec.inputs[0]), name, spec.warmup)
    return factor

if __name__ == "__main__":
    panels = {"close": load_panel("close")}
    for name in FACTORS:
        f = compute(name, panels)
        first = int(f.notna().any(axis = 1).argmax())
        print(f"{name:<10} shape {f.shape} first valid row {first:>4} "
              f"({f.index[first].date()}) coverage {f.notna().mean().mean():.1%}")