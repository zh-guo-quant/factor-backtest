"""Turn target weights into what they earn: execution, holding, costs and results.

Place in the engine:
-------------------
prepare_wrds.py -> data_loader.py -> factors.py -> portfolio.py -> backtest.py
clean data         wide panels       signals at t  weights at t    returns

Timing:
------
Weights are stamped with their signal date t, a month-end close. They are executed at the close 
of the next trading day (entry) and held until the close of the next entry day (exit) when the
next portfolio replaces them. This is the only place the one-day lag is applied. A position earns 
its first return on the day after the entry.
"""

from typing import NamedTuple

import numpy as np
import pandas as pd

import config


# %%
# Block 1. Timing and execution
# =================================================================================================

class Schedule(NamedTuple):
    """One entry per holding period."""
    signal: pd.DatetimeIndex    # t: the date the weights are stamped with
    entry: pd.DatetimeIndex     # t + 1: executed at this close
    exit: pd.DatetimeIndex      # the next entry: the last trading day for the final period

def make_schedule(signal_dates: pd.DatetimeIndex, calendar: pd.DatetimeIndex) -> Schedule:
    """Entry and exit dates for each signal date, on the panel's own trading calendar.
    
    A signal on the last trading day has no next day to trade on and is dropped."""
    if not signal_dates.is_monotonic_increasing or signal_dates.has_duplicates:
        raise ValueError("signal dates must be strictly increasing.")
    position = calendar.get_indexer(signal_dates)
    if (position < 0).any():
        raise ValueError("some signal dates are not trading days of the calendar.")

    entry_position = position + 1
    keep = entry_position < len(calendar)
    signal = signal_dates[keep]
    entry = calendar[entry_position[keep]]
    exits = entry[1:].append(calendar[-1:])
    if not (entry < exits).all():
        raise ValueError("a holding period has no day after its entry.")
    return Schedule(signal = signal, entry = entry, exit = exits)

def execute(weights: pd.DataFrame, schedule: Schedule, tradable: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Weights held from each entry close, indexed by entry date.
    
    A stock is executed only if it is tradable on the entry day and has a close to be valued from.
    Stocks that cannot be executed are dropped and each leg is rescaled to +1 / -1."""
    if not (tradable.columns.equals(weights.columns) and close.columns.equals(weights.columns)
            and tradable.index.equals(close.index)):
        raise ValueError("weights, tradable and close are not aligned.")

    target = weights.loc[schedule.signal].set_axis(schedule.entry)
    can_trade = tradable.loc[schedule.entry] & close.loc[schedule.entry].notna()
    held = target.where(can_trade, 0.0)

    long = held.clip(lower = 0)
    short = held.clip(upper = 0)
    long_sum = long.sum(axis = 1)
    short_sum = - short.sum(axis = 1)
    empty = long_sum.eq(0) | short_sum.eq(0)
    if empty.any():
        raise ValueError(
            f"a leg has no executable stock on {list(empty[empty].index.date)}."
        )
    return long.div(long_sum, axis = 0) + short.div(short_sum, axis = 0)

def _validate_execution(held: pd.DataFrame, target: pd.DataFrame, tradable: pd.DataFrame, close: pd.DataFrame) -> None:
    """Post-conditions of every executed portfolio."""
    long = held.clip(lower = 0).sum(axis = 1)
    short = held.clip(upper = 0).sum(axis = 1)
    if (long - 1).abs().max() > 1e-9 or (short + 1).abs().max() > 1e-9:
        raise ValueError("executed legs do not sum to +1 / -1.")
    executable = tradable.loc[held.index] & close.loc[held.index].notna()
    if (held.ne(0) & ~executable).any().any():
        raise ValueError("weight held in a stock that could not be executed.")
    if (held.ne(0) & target.eq(0)).any().any():
        raise ValueError("execution added a stock that was not in the target portfolio.")

# %%
# Block 2. Holding period valuation
# =================================================================================================

class Holding(NamedTuple):
    """What the executed weights earned, before costs."""
    daily: pd.DataFrame     # date * [long, short, long_short]: returns on each day after entry
    period: pd.DataFrame    # entry * [long, short, long_short]: returns from entry to exit
    drifted: pd.DataFrame   # exit * symbols: weights at the exit close, per unit of equity
    stale_share: float      # share of position-days valued at an earlier close

def hold(held: pd.DataFrame, schedule: Schedule, close: pd.DataFrame) -> Holding:
    """Value each executed portfolio from its entry close to its exit close.
    
    Buy-and-hold: a position is worth its entry weight times close / entry close.
    A missing close is valued at the last observed close of the period, so a company that leaves
    the sample is settled at its last price (R13). The panel itself is never filled.
    
    Each leg starts at 1 per unit of equity and equity = 1 + long value - short value,
    so the daily long-short returns of a period compound to (long return - short return).
    The 'short' column is the return of the stocks shorted: positive means the leg lost."""
    daily, period, drifted = [], {}, {}
    stale = cells = 0
    for entry, exit_ in zip(schedule.entry, schedule.exit):
        w = held.loc[entry]
        w = w[w.ne(0)]
        raw = close.loc[entry:exit_, w.index].astype("float64")
        if raw.iloc[0].isna().any():
            raise ValueError(
                f"a position entered on {entry.date()} has no entry close."
            )
        later = raw.iloc[1:]
        stale += int(later.isna().sum().sum())
        cells += later.size
        relative = raw.ffill() / raw.iloc[0]    # valuation at the last observed close, this period only

        long, short = w[w > 0], -w[w < 0]
        v_long = relative[long.index] @ long
        v_short = relative[short.index] @ short
        equity = 1 + v_long - v_short
        if not equity.gt(0).all():
            raise ValueError(
                f"equity falls to zero in the period entered on {entry.date()}"
            )

        values = pd.DataFrame({"long": v_long, "short": v_short, "long_short": equity})
        daily.append((values / values.shift(1) - 1).iloc[1:])
        period[entry] = values.iloc[-1] - 1
        drifted[exit_] = relative.iloc[-1] * w / equity.iloc[-1]

    return Holding(
        daily = pd.concat(daily),
        period = pd.DataFrame(period).T.rename_axis("entry"),
        drifted = (pd.DataFrame(drifted).T.reindex(columns = held.columns).fillna(0.0).rename_axis("exit")),
        stale_share = stale / cells,
    )

def _validate_holding(h: Holding, schedule: Schedule, calendar: pd.DatetimeIndex) -> None:
    """Post-conditions of the holding-period returns."""
    days = calendar[(calendar > schedule.entry[0]) & (calendar <= schedule.exit[-1])]
    if not h.daily.index.equals(days):
        raise ValueError("daily returns do not cover each day from the first entry to the last exit once.")
    if not np.isfinite(h.daily.to_numpy()).all():
        raise ValueError("daily returns contain missing or infinite values.")

    period_of_day = schedule.entry[schedule.exit.searchsorted(h.daily.index)]
    compounded = (1 + h.daily).groupby(period_of_day).prod() - 1
    error = (compounded - h.period).abs().max().max()
    if error > 1e-9:
        raise ValueError(
            f"daily returns do not compound to the period returns (max error {error:.1e})."
        )

# %% 
# Block 3. Turnover and costs
# =================================================================================================

class Trading(NamedTuple):
    """Trades at each entry and the long-short returns after costs."""
    turnover: pd.Series     # entry: sum of |weight traded| per unit of equity (build 2, full replacement 4)
    cost: pd.Series         # entry: cost as a share of equity
    net_daily: pd.Series    # date: long-short returns after costs
    net_period: pd.Series   # entry: long-short period returns after costs

def trade(held: pd.DataFrame, h: Holding, schedule: Schedule, cost_bps: float = config.COST_BPS) -> Trading:
    """Turnover at each entry and the long-short returns after costs.
    
    Turnover is measured against the previous portfolio as it drifted to the entry close;
    the first entry builds from cash. One-way cost_bps is charged on every unit traded,
    as a share of equity, and booked on the first day of the period the trade opens.
    The final portfolio is not liquidated: the strategy is assumed to continue."""
    before = h.drifted.reindex(held.index).fillna(0.0)  # exit k-1 is entry k; nothing before the first
    turnover = (held - before).abs().sum(axis = 1)
    cost = turnover * cost_bps / 1e4

    first_day = h.daily.index[h.daily.index.searchsorted(schedule.entry, side = "right")]
    charge = pd.Series(0.0, index = h.daily.index)
    charge[first_day] = cost.to_numpy()
    net_daily = (1 - charge) * (1 + h.daily["long_short"]) - 1
    net_period = (1 - cost) * (1 + h.period["long_short"]) - 1
    return Trading(turnover = turnover, cost = cost, net_daily = net_daily, net_period = net_period)

def _validate_trading(t: Trading, held: pd.DataFrame, schedule: Schedule) -> None:
    """Post-conditions of turnover and net returns."""
    if abs(t.turnover.iloc[0] - held.iloc[0].abs().sum()) > 1e-9:
        raise ValueError("the first entry must build the portfolio from cash.")
    if not (np.isfinite(t.turnover) & t.turnover.ge(0)).all():
        raise ValueError("turnover is negative or not finite.")

    period_of_day = schedule.entry[schedule.exit.searchsorted(t.net_daily.index)]
    compounded = (1 + t.net_daily).groupby(period_of_day).prod() - 1
    error = (compounded - t.net_period).abs().max()
    if error > 1e-9:
        raise ValueError(
            f"net daily returns do not compound to net period returns (max error {error:.1e})."
        )

# %%
# Block 4. Performance and the locked holdout
# =================================================================================================

PERIODS_PER_YEAR = 12               # monthly rebalancing (config.REBALANCE = "ME")
COST_GRID_BPS = (0, 10, 25, 50)     # one-way costs for the sensitivity table

def in_sample(schedule: Schedule) -> np.ndarray:
    """True for periods that end before the holdout. A period that ends inside it is holdout."""
    return schedule.exit < pd.Timestamp(config.HOLDOUT_START)

def select(schedule: Schedule, sample: str = "in") -> np.ndarray:
    """Periods of one sample. The holdout stays locked until config.HOLDOUT_UNLOCKED is True."""
    if sample == "in":
        return in_sample(schedule)
    if sample == "holdout":
        if not config.HOLDOUT_UNLOCKED:
            raise PermissionError(
                "the holdout is locked: set.config_HOLDOUT_UNLOCKED = True only once the " 
                "in-sample design is final."
            )
        return ~in_sample(schedule)
    raise ValueError(
        f"sample must be 'in' or 'holdout', got {sample!r}."
    )

def newey_west_t(x: pd.Series, lags: int | None = None) -> float:
    """t-statistic of the mean with Newey-West (1987) standard and Bartlett weights."""



if __name__ == "__main__":
    import factors as fx
    import portfolio as pf
    from data_loader import load_panel

    close = load_panel("close")
    tradable = load_panel("is_tradable")
    raw_close = load_panel("raw_close")

    print(f"{'factor':<10}{'periods':>8}{'first day':>12}{'days':>7}{'dropped':>9}"
          f"{'stale share':>13}{'turnover':>10}{'median':>8}{'max':>7}{'cost/yr':>9}")
    diagnostics = []
    for name in fx.FACTORS:
        p = pf.build(fx.compute(name, {"close": close}), tradable, raw_close)
        sched = make_schedule(p.weights.index, close.index)
        held = execute(p.weights, sched, tradable, close)
        target = p.weights.loc[sched.signal].set_axis(sched.entry)
        _validate_execution(held, target, tradable, close)
        h = hold(held, sched, close)
        _validate_holding(h, sched, close.index)
        t = trade(held, h, sched)
        _validate_trading(t, held, sched)

        dropped = int((target.ne(0) & held.eq(0)).sum().sum())
        ins = t.turnover.index < config.HOLDOUT_START
        rebal = t.turnover[ins].iloc[1:]                # in-sample rebalance, initial build excluded
        cost_year = t.cost[ins].iloc[1:].mean() * 12    # monthly rebalancing
        print(f"{name:<10}{len(sched.entry):>8}{str(h.daily.index[0].date()):>12}{len(h.daily):>7}"
              f"{dropped:>9}{h.stale_share:>13.3%}{rebal.mean():>10.2f}{rebal.median():>8.2f}"
              f"{rebal.max():>7.2f}{cost_year:>9.2%}")
        drop = target.ne(0) & held.eq(0)
        long_side, short_side = target.gt(0), target.lt(0)
        in_gap = (drop.index >= "2017-06-19") & (drop.index <= "2017-10-13")
        diagnostics.append((
            name,
            (drop & long_side).sum().sum() / long_side.sum().sum(),
            (drop & short_side).sum().sum() / short_side.sum().sum(),
            int(drop.loc[in_gap].sum().sum()),
            t.turnover[ins].idxmax().date(),
        ))
    print()
    print(f"{'factor':<10}{'drop long':>11}{'drop short':>12}{'in gap':>8}{'max turnover':>14}")
    for name, long_share, short_share, gap, peak in diagnostics:
        print(f"{name:<10}{long_share:>11.2%}{short_share:>12.2%}{gap:>8}{str(peak):>14}")