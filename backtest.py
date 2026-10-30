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
    cost_bps: float         # the one-way cost this run used

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
    return Trading(turnover = turnover, cost = cost, net_daily = net_daily, net_period = net_period, cost_bps = cost_bps)

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
                "the holdout is locked: set config.HOLDOUT_UNLOCKED = True only once the " 
                "in-sample design is final."
            )
        return ~in_sample(schedule)
    raise ValueError(
        f"sample must be 'in' or 'holdout', got {sample!r}."
    )

def newey_west_t(x: pd.Series, lags: int | None = None) -> float:
    """t-statistic of the mean with Newey-West (1987) standard and Bartlett weights."""
    x = np.asarray(x, dtype = "float64")
    n = len(x)
    if lags is None:
        lags = int(4 * (n / 100) ** (2 / 9))
    e = x - x.mean()
    variance = e @ e / n
    for lag in range(1, lags + 1):
        variance += 2 * (1 - lag / (lags + 1)) * (e[lag:] @ e[:-lag]) / n
    return x.mean() / np.sqrt(variance / n)

def summarise(h: Holding, t: Trading, schedule: Schedule, sample: str = "in") -> pd.Series:
    """Performance of one long-short portfolio on one sample, net of costs unless stated.
    
    Means and volatilities are annualised from period returns; the drawdown comes from daily net returns.
    'long' and 'short' are gross leg returns: long - short is the gross spread. 
    break-even_bps is the one-way cost at which the mean net period return is zero."""
    periods = select(schedule, sample)
    if periods.sum() < 2:
        raise ValueError(
            f"fewer than two periods in sample {sample!r}."
        )
    days = periods[schedule.exit.searchsorted(t.net_daily.index)]   # each day follow its period
    rebalances = periods.copy()
    rebalances[0] = False                                            # the initiation build is not a rebalance

    gross = h.period["long_short"][periods]
    net = t.net_period[periods]
    turnover = t.turnover[periods]
    legs = h.period[periods]

    equity = (1 + t.net_daily[days]).cumprod()
    drawdown = (equity / equity.cummax().clip(lower = 1.0) - 1).min()

    scale = PERIODS_PER_YEAR
    row = {
        "months": int(periods.sum()),
        "first": schedule.entry[periods][0].date(),
        "last": schedule.exit[periods][-1].date(),
        "mean": net.mean() * scale,
        "vol": net.std() * np.sqrt(scale),
        "sharpe": net.mean() / net.std() * np.sqrt(scale),
        "t_nw": newey_west_t(net),
        "hit": (net > 0).mean(),
        "max_dd": drawdown,
        "long": legs["long"].mean() * scale,
        "short": legs["short"].mean() * scale,
        "turnover": t.turnover[rebalances].mean(),
        "cost": t.cost[rebalances].mean() * scale,
        "cost_bps": t.cost_bps,
        "break_even_bps": gross.mean() / (turnover * (1 + gross)).mean() * 1e4,
    }
    for bps in COST_GRID_BPS:
        row[f"mean_{bps}"] = ((1 - bps / 1e4 * turnover) * (1 + gross) - 1).mean() * scale

    at_run = ((1 - t.cost_bps / 1e4 * turnover) * (1 + gross) - 1).mean() * scale
    if abs(at_run - row["mean"]) > 1e-12:
        raise ValueError("the cost formula does not reproduce the net return of this run.")
    return pd.Series(row)

def contributions(held: pd.DataFrame, schedule: Schedule, close: pd.DataFrame,
                  entry: pd.Timestamp) -> pd.DataFrame:
    """Each position's contribution to the gross long-short return of the period entered on 'entry'."""
    k = schedule.entry.get_loc(entry)
    w = held.loc[entry]
    w = w[w.ne(0)]
    levels = close.loc[entry:schedule.exit[k], w.index].astype("float64").ffill()
    move = levels.iloc[-1] / levels.iloc[0] - 1
    return pd.DataFrame({"weight": w, "move": move, "contrib": w * move}).sort_values("contrib")

# %%
# Block 5. Public API
# =================================================================================================

class Result(NamedTuple):
    """Everything one backtest produced, step by step."""
    schedule: Schedule
    target: pd.DataFrame    # entry * symbols: target weights, before execution
    held: pd.DataFrame      # entry * symbols: weights actually held
    holding: Holding        # returns before costs
    trading: Trading        # turnover, costs, returns after costs

def _validate_weights(weights: pd.DataFrame) -> None:
    """The engine backtests 1:1 long-short portfolio only."""
    if weights.isna().any().any():
        raise ValueError("weights contain missing values; use 0 for stocks not held.")
    long = weights.clip(lower = 0).sum(axis = 1)
    short = weights.clip(upper = 0).sum(axis = 1)
    if (long - 1).abs().max() > 1e-9 or (short + 1).abs().max() > 1e-9:
        raise ValueError("each signal data needs a long leg summing to +1 and a short leg summing to -1.")

def run(weights: pd.DataFrame, close: pd.DataFrame, tradable: pd.DataFrame, cost_bps: float = config.COST_BPS) -> Result:
    """Backtest one set of target weights stamped with their signal dates.
    
    The only supported way to backtest. It does not know where the weights came from:
    a factor sort or a model's predictions go through the same steps and checks."""
    _validate_weights(weights)
    schedule = make_schedule(weights.index, close.index)
    target = weights.loc[schedule.signal].set_axis(schedule.entry)

    held = execute(weights, schedule, tradable, close)
    _validate_execution(held, target, tradable, close)
    holding = hold(held, schedule, close)
    _validate_holding(holding, schedule, close.index)
    trading = trade(held, holding, schedule, cost_bps)
    _validate_trading(trading, held, schedule)

    return Result(schedule = schedule, target = target, held = held, holding = holding, trading = trading)


if __name__ == "__main__":
    import factors as fx
    import portfolio as pf
    from data_loader import load_panel

    close = load_panel("close")
    tradable = load_panel("is_tradable")
    raw_close = load_panel("raw_close")

    print(f"{'factor':<10}{'periods':>8}{'first day':>12}{'days':>7}{'dropped':>9}"
          f"{'stale share':>13}{'turnover':>10}{'cost/yr':>9}")
    for name in fx.FACTORS:
        weights = pf.build(fx.compute(name, {"close": close}), tradable, raw_close).weights
        r = run(weights, close, tradable)

        rebalances = in_sample(r.schedule)
        rebalances[0] = False                   # the initial build is not a rebalance
        dropped = int((r.target.ne(0) & r.held.eq(0)).sum().sum())
        print(f"{name:<10}{len(r.schedule.entry):>8}{str(r.holding.daily.index[0].date()):>12}"
              f"{len(r.holding.daily):>7}{dropped:>9}{r.holding.stale_share:>13.3%}"
              f"{r.trading.turnover[rebalances].mean():>10.2f}"
              f"{r.trading.cost[rebalances].mean() * PERIODS_PER_YEAR:>9.2%}")