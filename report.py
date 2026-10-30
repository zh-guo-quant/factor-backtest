"""Run every factor through the engine and report the results.

Place in the engine
-------------------
prepare_wrds.py -> data_loader.py -> factors.py -> portfolio.py -> backtest.py -> report.py

This module only presents: every number comes from backtest.summarise and backtest.contributions,
so the holdout lock in backtest applies here as well.
The in-sample tables, including the position-level attribution of each factor's worst month,
are printed and written to results/in_sample.md.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FixedLocator, NullLocator, PercentFormatter, ScalarFormatter

import backtest 
import config
import factors 
import portfolio 
from data_loader import load_panel

RESULTS_FILE = config.ROOT / "results" / "in_sample.md"
PANELS = ("close", "is_tradable", "raw_close")

# %%
# Block 1. Run the factors
# =================================================================================================

def load_panels() -> dict[str, pd.DataFrame]:
    """The panels the factors, the portfolio and the backtest need, loaded once."""
    return {field: load_panel(field) for field in PANELS}

def run_factors(panels:dict[str, pd.DataFrame], names: list[str] | None = None, cost_bps: float = config.COST_BPS) -> dict[str, backtest.Result]:
    """Backtest the long-short portfolio of each factor."""
    results = {}
    for name in names or factors.FACTORS:
        weights = portfolio.build(factors.compute(name, panels), panels["is_tradable"], panels["raw_close"]).weights
        results[name] = backtest.run(weights, panels["close"], panels["is_tradable"], cost_bps)
    return results

# %%
# Block 2. Tables
# =================================================================================================

def performance(result: dict[str, backtest.Result], sample: str = "in") -> pd.DataFrame:
    """backtest.summarise for every factor, one row each."""
    return pd.DataFrame({name: backtest.summarise(r.holding, r.trading, r.schedule, sample) 
                         for name, r in result.items()}).T.rename_axis("factor")

def _net_equity(r: backtest.Result, sample: str) -> pd.Series:
    """Net equity over one sample: 1 at the first entry close, then after each day."""
    periods = backtest.select(r.schedule, sample)
    days = periods[r.schedule.exit.searchsorted(r.trading.net_daily.index)]
    start = pd.Series([1.0], index = r.schedule.entry[periods][:1])
    return pd.concat([start, (1 + r.trading.net_daily[days]).cumprod()])

def drawdowns(results: dict[str, backtest.Result], sample: str = "in") -> pd.DataFrame:
    """Deepest drawdown of net equity and the worst period, per factor."""
    rows = {}
    for name, r in results.items():
        equity = _net_equity(r, sample)
        drawdown = equity / equity.cummax().clip(lower = 1.0) -1
        trough = drawdown.idxmin()
        net = r.trading.net_period[backtest.select(r.schedule, sample)]
        worst = net.idxmin()
        rows[name] = {
            "peak": equity.loc[:trough].idxmax().date(),
            "trough": trough.date(),
            "drawdown": drawdown.min(),
            "worst_entry": worst.date(),
            "worst_net": net[worst],
        }
    return pd.DataFrame(rows).T.rename_axis("factor")

def execution(results: dict[str, backtest.Result], sample: str = "in") -> pd.DataFrame:
    """Position per period and the share of target positions dropped at execution, by leg."""
    rows = {}
    for name, r in results.items():
        periods = backtest.select(r.schedule, sample)
        target, held = r.target.loc[periods], r.held.loc[periods]
        dropped = target.ne(0) & held.eq(0)
        long, short = target.gt(0), target.lt(0)
        rows[name] = {
            "positions": target.ne(0).sum(axis = 1).mean(),
            "dropped_long": (dropped & long).sum().sum() / long.sum().sum(),
            "dropped_short": (dropped & short).sum().sum() / short.sum().sum(),
        }
    return pd.DataFrame(rows).T.rename_axis("factor")

def _company_names() -> dict[str, str]:
    """symbol -> company name for WRDS data; empty for other sources."""
    if config.SOURCE != "wrds" or not config.WRDS_COMPANY_FILE.exists():
        return {}
    table = pd.read_csv(config.WRDS_COMPANY_FILE, dtype = {"symbol": str})
    return dict(zip(table["symbol"], table["conm"].astype(str).str.slice(0, 30)))

def worst_positions(results: dict[str, backtest.Result], close:pd.DataFrame,
                    sample: str = "in", top: int = 5) -> pd.DataFrame:
    """The positions that lost most in each factor's worst period."""
    names = _company_names()
    frames = []
    for name, r in results.items():
        net = r.trading.net_period[backtest.select(r.schedule, sample)]
        c = backtest.contributions(r.held, r.schedule, close, net.idxmin()).head(top)
        c = c.rename_axis("symbol").reset_index()
        c.insert(0, "factor", name)
        c.insert(2, "company", [names.get(s, "") for s in c["symbol"]])
        frames.append(c)
    return pd.concat(frames, ignore_index = True)

# %%
# Block 3. Aligned tables
# =================================================================================================

PERFORMANCE = {
    "factor": ("factor", None), "months": ("months", "d"), "first": ("first", None),
    "last": ("last", None), "mean": ("mean", ".2%"), "vol": ("vol", ".2%"),
    "sharpe": ("Sharpe", ".2f"), "t_nw": ("t (NW)", ".2f"), "hit": ("hit", ".1%"),
    "max_dd": ("max DD", ".1%"), "long": ("long", ".2%"), "short": ("short", ".2%"),
}
COSTS = {
    "factor": ("factor", None), "turnover": ("turnover", ".2f"), "cost": ("cost/yr", ".2%"),
    "break_even_bps": ("break-even bp", ".1f"),
    **{f"mean_{bps}": (f"@{bps}bp", ".2%") for bps in backtest.COST_GRID_BPS},
}
EXECUTION = {
    "factor": ("factor", None), "positions": ("positions", ".0f"),
    "dropped_long": ("dropped long", ".2%"), "dropped_short": ("dropped short", ".2%"),
}
DRAWDOWN = {
    "factor": ("factor", None), "peak": ("peak", None), "trough": ("trough", None),
    "drawdown": ("drawdown", ".1%"), "worst_entry": ("worst entry", None), "worst_net": ("worst net", ".2%"),
}
WORST = {
    "factor": ("factor", None), "symbol": ("symbol", None), "company": ("company", None),
    "weight": ("weight", ".2%"), "move": ("move", ".1%"), "contrib": ("contrib", ".2%"),
}

def formatted(table: pd.DataFrame, spec: dict[str, tuple[str, str | None]]) -> pd.DataFrame:
    """Select, rename and format columns as text; spec maps column -> (label, format or None)."""
    return pd.DataFrame({label: [format(v, fmt) if fmt else str(v) for v in table[column]]
                         for column, (label, fmt) in spec.items()})

def as_text(shown: pd.DataFrame, left: int = 1, markdown: bool = False) -> str:
    """Aligned table: the first 'left' columns left-aligned, the rest right-aligned."""
    align = ("left",) * left + ("right",) * (shown.shape[1] - left)
    return shown.to_markdown(index = False, tablefmt = "pipe" if markdown else "plain",
                             colalign = align, disable_numparse = True)

# %%
# Block 4. Figures
# =================================================================================================

STYLE = {
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb",
    "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#e1e0d9", "grid.linewidth": 0.8,
    "axes.titlelocation": "left", "axes.titlesize": 12, "axes.titlecolor": "#0b0b0b",
    "axes.labelcolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e",
    "xtick.labelsize": 9, "ytick.labelsize": 9, "axes.labelsize": 9,
    "legend.frameon": False, "legend.fontsize": 9, "lines.linewidth": 1.5,
}
COLORS = {"momentum": "#2a78d6", "reversal": "#eb6834", "low_vol": "#1baf7a"}
EVENTS = {"2020-03-23": ("COVID low", "right"), "2020-11-09": ("vaccine news", "left")}

def _save(fig, path) -> None:
    fig.savefig(path, dpi = 150, metadata = {"Software": None})
    plt.close(fig)

@plt.rc_context(STYLE)
def plot_equity(results: dict[str, backtest.Result], path, sample: str = "in") -> None:
    """Net equity of each factor, starting from 1; the legend gives the final value."""
    fig, ax = plt.subplots(figsize = (9, 4.5), layout = "constrained")
    for name, r in results.items():
        equity = _net_equity(r, sample)
        ax.plot(equity.index, equity, color = COLORS[name], label = f"{name} ({equity.iloc[-1]:.2f})")
    ax.axhline(1, color = "#c3c2b7", linewidth = 0.8)
    for date, (text, side) in EVENTS.items():
        ax.axvline(pd.Timestamp(date), color = "#e1e0d9", linewidth = 0.8, zorder = 0)
        ax.annotate(f" {text}" if side == "right" else f" {text}", (pd.Timestamp(date), 1), 
                    xycoords = ("data", "axes fraction"), ha = side, 
                    va = "top", fontsize = 8, color = "#898781")
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(FixedLocator([0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4]))
    ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.yaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title(f"Cumulative net return, in-sample (net of {config.COST_BPS} bp one-way, log scale)")
    ax.legend(loc = "best")
    _save(fig, path)

@plt.rc_context(STYLE)
def plot_costs(perf:pd.DataFrame, path, max_bps: int = 100) -> None:
    """Mean annual net return at each one-way cost, with each factor's break-even."""
    grid = list(backtest.COST_GRID_BPS)
    costs = np.array([0, max_bps])
    fig, ax = plt.subplots(figsize = (9, 4.5), layout = "constrained")
    for name, s in perf.iterrows():
        slope = (s[f"mean_{grid[-1]}"] - s[f"mean_{grid[0]}"]) / (grid[-1] - grid[0])
        ax.plot(costs, s[f"mean_{grid[0]}"] + slope * (costs - grid[0]), color = COLORS[name],
                label = f"{name} (break-even {s['break_even_bps']:.1f} bp)")
        ax.plot(grid, [s[f"mean_{bps}"] for bps in grid], "o", color = COLORS[name])
        if 0 < s["break_even_bps"] <= max_bps:
            ax.plot(s["break_even_bps"], 0, "o", markersize = 8, markerfacecolor = "#fcfcfb",
                    markeredgecolor = COLORS[name], markeredgewidth = 1.5, zorder = 3)
    ax.axhline(0, color = "#c3c2b7", linewidth = 0.8)
    ax.set_xlim(0, max_bps)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xlabel("One-way cost (bp)")
    ax.set_title("Annual net return against trading cost, in-sample (hollow dot: break-even)")
    ax.legend(loc = "best")
    _save(fig, path)

# %%
# Block 5. Main
# =================================================================================================

def main() -> None:
    panels = load_panels()
    results = run_factors(panels)

    perf = performance(results)
    dd = drawdowns(results)
    if not np.allclose(perf["max_dd"].astype(float), dd["drawdown"].astype(float)):
        raise ValueError("drawdown disagree with backtest.summrise.")

    folder = RESULTS_FILE.parent
    folder.mkdir(parents = True, exist_ok = True)
    plot_equity(results, folder / "in_sample_equity.png")
    plot_costs(perf, folder / "in_sample_costs.png")

    header = (f"In-sample: holding periods ending before {config.HOLDOUT_START}. "
              f"Source {config.SOURCE}; {config.N_BUCKETS} buckets, equal-weighted long-short; "
              f"price floor {config.PRICE_FLOOR:.2f} GBP; executed at the next close; "
              f"net of {config.COST_BPS} bps one-way unless stated.")
    sections = [
        ("Performance", perf, PERFORMANCE, 1),
        ("Costs: break-even and mean net return at each one-way cost", perf, COSTS, 1),
        ("Execution: share of target positions dropped at the next close", execution(results), EXECUTION, 1),
        ("Deepest drawdown and worst month", dd, DRAWDOWN, 1),
        ("Worst month: the five largest losses by position", worst_positions(results, panels["close"]), WORST, 3),
    ]
    
    print(header)
    markdown = ["# In-sample results", "", header, "",
                "![Cumulative net return](in_sample_equity.png)", "",
                "![Annual net return against trading cost](in_sample_costs.png)", ""]
    for title, table, spec, left in sections:
        shown = formatted(table.reset_index(), spec)
        print(f"\n{title}\n{as_text(shown, left)}")
        markdown += [f"## {title}", "", as_text(shown, left, markdown = True), ""]

    RESULTS_FILE.write_text("\n".join(markdown), encoding = "utf-8", newline = "\n")
    print(f"\nwritten {RESULTS_FILE.relative_to(config.ROOT)}")

if __name__ == "__main__":
    main()