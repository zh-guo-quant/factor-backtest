# %% Block1. Settings and the step log
# =================================================================================================
"""Build the engine input file for source 'wrds' from the audited WRDS_UK file.

Rules (F1 - F4, R1 - R14) are documented in docs/data_audit_wrds_uk.md.
Every step records how many rows it changed, so the log can be checked against the audit report.

Output: data/wrds_clean.csv.gz, one row per company and trading day:
date, symbol, close, raw_close, dollar_volume, is_tradable, ret_adj, market_cap."""

import hashlib
import json
import platform

import numpy as np
import pandas as pd

import config

RAW_FILE = config.WRDS_RAW_FILE
EXPECTED_SHA256 = config.WRDS_SHA256
OUTPUT_FILE = config.RAW_FILES["wrds"]
COMPANY_FILE = config.WRDS_COMPANY_FILE
EVENT_FILE = config.DATA_DIR / "wrds_clean_events.csv"
MANIFEST_FILE = config.ROOT / "docs"/ "wrds_clean_manifest.json"

# Only the columns later steps use; dropping the rest at read time saves memory.
USE_COLUMNS = [
    "gvkey", "iid", "datadate", "conm", "tpci", "curcdd",
    "prccd", "ajexdi", "trfd", "cshtrd", "cshoc",
    "prirow", "sic", "fic", "dlrsn", "dldte",
]
STRING_COLUMNS = ["gvkey", "iid", "tpci", "curcdd", "prirow", "sic", "fic", "dlrsn", "dldte",]
NUMERIC_COLUMNS = ["prccd", "ajexdi", "trfd", "cshtrd", "cshoc",]
KEY = ["sid", "datadate",]

SAMPLE_START, SAMPLE_END = "2014-01-01", "2024-12-31"

# R3: the 91 non-trading days (Appendix A of the audit document).
NON_TRADING_DAYS = pd.to_datetime([
    "2014-01-01", "2014-04-18", "2014-04-21", "2014-05-05",
    "2014-05-26", "2014-08-25", "2014-12-25", "2014-12-26",
    "2015-01-01", "2015-04-03", "2015-04-06", "2015-05-04",
    "2015-05-25", "2015-08-31", "2015-12-25", "2015-12-28",
    "2016-01-01", "2016-03-25", "2016-03-28", "2016-05-02",
    "2016-05-30", "2016-08-29", "2016-12-26", "2016-12-27",
    "2017-01-02", "2017-04-14", "2017-04-17", "2017-05-01",
    "2017-05-29", "2017-08-28", "2017-12-25", "2017-12-26",
    "2018-01-01", "2018-03-30", "2018-04-02", "2018-05-07",
    "2018-05-28", "2018-08-27", "2018-12-25", "2018-12-26",
    "2019-01-01", "2019-04-19", "2019-04-22", "2019-05-06",
    "2019-05-27", "2019-08-26", "2019-12-25", "2019-12-26",
    "2020-01-01", "2020-04-10", "2020-04-13", "2020-05-08",
    "2020-05-25", "2020-08-31", "2020-12-25", "2020-12-28",
    "2021-01-01", "2021-04-02", "2021-04-05", "2021-05-03",
    "2021-05-31", "2021-08-30", "2021-12-27", "2021-12-28",
    "2022-01-03", "2022-04-15", "2022-04-18", "2022-05-02",
    "2022-06-02", "2022-06-03", "2022-08-29", "2022-09-19",
    "2022-12-26", "2022-12-27", "2023-01-02", "2023-04-07", 
    "2023-04-10", "2023-05-01", "2023-05-08", "2023-05-29", 
    "2023-08-28", "2023-12-25", "2023-12-26", "2024-01-01", 
    "2024-03-29", "2024-04-01", "2024-05-06", "2024-05-27", 
    "2024-08-26", "2024-12-25", "2024-12-26",
])

LOG_FORMAT = "{:<5}{:<46}{:>12}{:>10}"
_LOG = []
_REVIEW = []
_EVENTS = []

def log(rule, action, rows, securities):
    """Record one step and print it as a row of log table."""
    _LOG.append((rule, action, int(rows), int(securities)))
    print(LOG_FORMAT.format(rule, action, f"{int(rows):,}", f"{int(securities):,}"))

def record(rule, df, mask, field, before, after):
    """Keep row-level changes (rule, sid, date, field, old and new value) for the event file."""
    events = df.loc[mask, ["sid", "datadate"]].assign(rule = rule, field = field)
    events["before"] = before[mask] if isinstance(before, pd.Series) else before
    events["after"] = after[mask] if isinstance(after, pd.Series) else after
    _EVENTS.append(events)

def print_log_header():
    print(LOG_FORMAT.format("rule", "action", "rows", "sids"))
    print("=" * 73)

# %% Block 2. F3 source check, F1 load and key check
# =================================================================================================

def check_source(path = RAW_FILE):
    """F3: refuse to run on any file other than the audited one."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != EXPECTED_SHA256.lower():
        raise ValueError(
            f"{path.name}: SHA-256 {digest.hexdigest()} differs from the audited file. "
            f"Re-run the audit before accepting a new file. "
        )
    
def load(path = RAW_FILE):
    """F1: read the raw file, build sid, sort by (sid, date), check the key."""
    df = pd.read_csv(
        path,
        compression = "gzip",
        usecols = lambda column: column.strip().lower() in USE_COLUMNS,
        dtype = {column: str for column in STRING_COLUMNS},
        low_memory = False,
    )
    df.columns = df.columns.str.strip().str.lower()
    for column in NUMERIC_COLUMNS:
        parsed = pd.to_numeric(df[column], errors = "coerce")
        failed = parsed.isna() & df[column].notna()
        if failed.any():
            raise ValueError(
                f"{column}: {int(failed.sum())} values are not numbers, "
                f"first {df.loc[failed, column].iloc[0]!r}"
            )
        df[column] = parsed
    df["datadate"] = pd.to_datetime(df["datadate"])
    for column in STRING_COLUMNS:
        df[column] = df[column].str.strip()
    df["gvkey"] = df["gvkey"].str.zfill(6)
    df["sid"] = df["gvkey"] + "_" + df["iid"]
    df = df.sort_values(KEY, kind = "stable").reset_index(drop = True)

    if df[KEY].isna().any().any() or df.duplicated(KEY).any():
        raise ValueError("missing or duplicated (sid, datadate) keys; see audit section 1.")
    log("F1", "loaded", len(df), df["sid"].nunique())
    return df

# %% Block 3. R2 currency breaks, R1 analysis segment, R3 trading calendar.
# =================================================================================================

def count_currency_breaks(df):
    """R2, part 1: on the unfiltered file, count currency changes within each sid.
    
    A break is an observation whose previous observation has a different or missing currency.
    The running count is kept so that R1 and R3 can drop rows without losing a break that sat on a dropped row."""
    previous = df.groupby("sid", sort = False)["curcdd"].shift(1)
    has_previous = df["sid"].eq(df["sid"].shift(1))
    is_break = has_previous & df["curcdd"].ne(previous)
    df["breaks_so_far"] = is_break.astype(int).groupby(df["sid"], sort = False).cumsum()
    log("R2", "currency changes in the full file", is_break.sum(), df.loc[is_break, "sid"].nunique())
    return df

def keep_segment(df):
    """R1: ordinary shares, GBP, positive close."""
    keep = df["tpci"].eq("0") & df["curcdd"].eq("GBP") & df["prccd"].gt(0)
    log("R1", "rows outside the segment removed", (~keep).sum(), df.loc[~keep, "sid"].nunique())
    return df.loc[keep].reset_index(drop = True)

def trading_days():
    """R3: weekdays in the sample minus the 91 non-trading days."""
    weekdays = pd.bdate_range(SAMPLE_START, SAMPLE_END)
    reference = pd.DatetimeIndex(NON_TRADING_DAYS)
    if len(reference) != 91 or reference.has_duplicates or not reference.isin(weekdays).all():
        raise ValueError("NON_TRADING_DAYS must be 91 unique weekdays inside the sample.")
    return weekdays.difference(reference)

def follows_previous_day(dates, groups):
    """True where the previous row of the same group is on the previous trading day."""
    days = trading_days()
    day_no = dates.map(pd.Series(np.arange(len(days)), index = days))
    return (day_no - day_no.groupby(groups, sort = False).shift(1)).eq(1)

def keep_trading_days(df):
    """R3: remove rows on non-trading days and weekends; every trading days must remain."""
    days = trading_days()
    keep = df["datadate"].isin(days)
    log("R3", "rows on non-trading days removed", (~keep).sum(), df.loc[~keep, "sid"].nunique())
    df = df.loc[keep].reset_index(drop = True)
    missing = days.difference(df["datadate"].unique())
    if len(missing):
        raise ValueError(
            f"{len(missing)} trading days have no rows, first {missing[0].date()}"
        )
    return df

def mark_currency_breaks(df):
    """R2, part 2: flag rows whose return would cross a currency change.
    
    A row is flagged if any break occurred since the previous kept row of the same sid.
    The flag is applied in line_returns() in Block 5, which sets the return of flagged rows to missing."""
    grouped = df.groupby("sid", sort = False)["breaks_so_far"]
    df["currency_break"] = grouped.diff().gt(0)
    log("R2", "kept rows whose return crosses a change", df["currency_break"].sum(),
        df.loc[df["currency_break"], "sid"].nunique())
    return df.drop(columns = "breaks_so_far")


# %% Block 4. R4 stuck adjustment, R6 bad prints (price-level fixes)
# =================================================================================================

R4_FACTOR_MOVE = 0.20
# R6: prices that are bad prints; each must match exactly one row.
BAD_PRINTS = [
    ("284812_02W", "2017-06-16"),   # STM Group: 0.43 -> 13.601 -> 0.42
    ("204760_01W", "2017-03-27"),   # H.C. Slingsby: 0.425 -> 0.20 -> 0.375
]

def positive(values):
    """True where a value is present, finite and strictly positive."""
    return values.notna() & np.isfinite(values) & values.gt(0)

def summarise_stuck_runs(df, stuck, run):
    """Queue one review line for R4: how long the stuck runs are."""
    if not stuck.any():
        return
    lengths = run[stuck].value_counts()
    _REVIEW.append(
        f"R4 stuck runs: {len(lengths)} events, {int(lengths.sum()):,} rows, "
        f"median {lengths.median():.0f}, max {int(lengths.max()):,} rows"
    )

def fix_stuck_adjustments(df):
    """R4: a factor move above 20% with an unchanged raw price means the price
    has not yet been updated for the corporate action.
    
    The price is set to missing from the event row until the raw price next changes.
    The rows before the event keep their prices, even if it is the same."""
    previous = df.groupby("sid", sort = False)[["prccd", "ajexdi", "trfd"]].shift(1)
    valid = (positive(df["prccd"]) & positive(df["ajexdi"]) & positive(df["trfd"])
             & positive(previous["prccd"]) & positive(previous["ajexdi"])
             & positive(previous["trfd"]) & ~df["currency_break"])
    factor_step = (df["trfd"] / df["ajexdi"]) / (previous["trfd"] / previous["ajexdi"])
    event = valid & df["prccd"].eq(previous["prccd"]) & (factor_step - 1).abs().gt(R4_FACTOR_MOVE)

    # Number of each run of equal prices within a sid; the event sits inside a run.
    new_run = df["sid"].ne(df["sid"].shift(1)) | df["prccd"].ne(df["prccd"].shift(1))
    run = new_run.cumsum()

    # From the event row to the end of its run (cummax keeps True once seen).
    stuck = event.groupby(run).cummax()
    log("R4", "stuck adjustment events", event.sum(), df.loc[event, "sid"].nunique())
    log("R4", "price set to missing", stuck.sum(), df.loc[stuck, "sid"].nunique())
    summarise_stuck_runs(df, stuck, run)
    record("R4", df, stuck, "prccd", df["prccd"], np.nan)
    df.loc[stuck, "prccd"] = np.nan
    return df

def remove_bad_prints(df, bad_prints = BAD_PRINTS):
    """R6: set the listed bad-print prices to missing."""
    hits = pd.Series(False, index = df.index)
    for sid, date in bad_prints:
        hit = df["sid"].eq(sid) & df["datadate"].eq(pd.Timestamp(date))
        if hit.sum() != 1:
            raise ValueError(
                f"R6 bad print {sid} {date}: {int(hit.sum())} matching rows, expected 1"
            )
        hits |= hit
    record("R6", df, hits, "prccd", df["prccd"], np.nan)
    df.loc[hits, "prccd"] = np.nan
    log("R6", "bad-print prices set to missing", hits.sum(), df.loc[hits, "sid"].nunique())
    return df

# %% Block 5. F2 within-line returns, R2 applied
# =================================================================================================

def line_returns(df):
    """F2: total-return index and returns within each sid, on the cleaned price.
    
    A return is missing when either end has no valid index (no price, R4, R6)
    or when it crosses a currency change (R2).
    The first row of a sid has no return.
    tri and ret_adj are used again in Block 9 to build close."""
    factors_ok = positive(df["ajexdi"]) & positive(df["trfd"])
    df["tri"] = (df["prccd"] / df["ajexdi"] * df["trfd"]).where(factors_ok)
    bad_factors = positive(df["prccd"]) & ~factors_ok
    previous = df.groupby("sid", sort = False)[["prccd", "ajexdi", "tri"]].shift(1)
    both_valid = positive(df["tri"]) & positive(previous["tri"])
    valid = both_valid & ~df["currency_break"]

    df["prev_ajexdi"] = previous["ajexdi"]
    one_day = follows_previous_day(df["datadate"], df["sid"])
    df["ret_raw"] = (df["prccd"] / previous["prccd"] - 1).where(valid & one_day)
    df["ret_adj"] = (df["tri"] / previous["tri"] - 1).where(valid)

    crossed = both_valid & df["currency_break"]
    record("R2", df, crossed, "ret_adj", df["tri"] / previous["tri"] - 1, np.nan)
    log("F2", "prices without positive adjustment factors", bad_factors.sum(), df.loc[bad_factors, "sid"].nunique())
    log("F2", "valid within-line returns", valid.sum(), df.loc[valid, "sid"].nunique())
    log("R2", "returns set to missing (currency change)", crossed.sum(), df.loc[crossed, "sid"].nunique())
    return df.drop(columns = "currency_break")

# %% Block 6. R5 suspect adjustment events, R6 exemptions
# =================================================================================================

R5_ABS_RET = 0.30
R5_AJ_RATIO_LOW, R5_AJ_RATIO_HIGH = 0.80, 1.25
R5_PAIR_TOLERANCE = 0.20
R5_REVIEW_WINDOW = 10 # rows; distant offsets are listed for review, never paired automatically

# R6: genuine losses that must not be zeroed; each must be an R5 candidate.
R5_EXEMPT = [
    ("270250_02W", "2018-08-02"),    # Countrywide: recapitalisation, aj_ratio = 1.77
    ("327786_01W", "2022-12-14"),    # Trackwise: recapitalisation, aj_ratio = 3.80
]

def flag_exempt(df, exempt):
    """True on the listed (sid, date) rows; each must match exactly one row."""
    flag = pd.Series(False, index = df.index)
    for sid, date in exempt:
        hit = df["sid"].eq(sid) & df["datadate"].eq(pd.Timestamp(date))
        if hit.sum() != 1:
            raise ValueError(
                f"R6 exemption {sid} {date}: {int(hit.sum())} matching rows, expected 1"
            )
        flag |= hit
    return flag

def review_distant_offsets(df, unpaired, window = R5_REVIEW_WINDOW):
    """List unpaired R5 candidates that a return 2 to 'window' rows away would offset.
    
    Only the candidates are visited. df must be sorted by (sid, date) with a default index, which holds from block 3 on."""
    ret, sid = df["ret_adj"].to_numpy(), df["sid"].to_numpy()
    found = []
    for i in np.flatnonzero(unpaired.to_numpy()):
        near = np.arange(max(i - window, 0), min(i + window + 1, len(df)))
        near = near[(np.abs(near - i) >= 2) & (sid[near] == sid[i])]
        two_day = (1 + ret[i]) * (1 + ret[near]) - 1
        if np.any(np.abs(two_day) <= R5_PAIR_TOLERANCE):
            found.append(f"{sid[i]} {df['datadate'].iat[i].date()}")
    _REVIEW.append(f"R5 unpaired candidates offset 2-{window} rows away: {len(found)}"
                   + (f" ({', '.join(found)})" if found else ""))

def clean_adjustments(df, exempt = R5_EXEMPT):
    """R5: on adjustment days whose factors moves far from 1 and whose adjusted return is large, 
    the return is set to 0.
    If a neighbouring return of the same sid offsets it (two-day return within +/-20%),
    the pair keeps its two-day return: 0 on the earlier day, the two-day return on the later day."""
    aj_ratio = df["prev_ajexdi"] / df["ajexdi"]
    aj_change = positive(df["ajexdi"]) & positive(df["prev_ajexdi"]) & aj_ratio.ne(1)
    candidate = (df["ret_adj"].notna() & aj_change & df["ret_adj"].abs().gt(R5_ABS_RET)
                 & (aj_ratio.lt(R5_AJ_RATIO_LOW) | aj_ratio.gt(R5_AJ_RATIO_HIGH)))

    is_exempt = flag_exempt(df, exempt)
    if (is_exempt & ~candidate).any():
        raise ValueError("an R5 exemption is not an R5 candidate; check R5_EXEMPT")
    target = candidate & ~is_exempt

    # Pair with the previous return first; use the next one only if that fails.
    grouped = df.groupby("sid", sort = False)["ret_adj"]
    paired_with, two_day = {}, {}
    for name, periods in [("previous", 1), ("next", -1)]:
        neighbour = grouped.shift(periods)
        two_day[name] = (1 + df["ret_adj"]) * (1 + neighbour) - 1
        paired_with[name] = (target & neighbour.notna() & two_day[name].abs().le(R5_PAIR_TOLERANCE))
    pair_prev = paired_with["previous"]
    pair_next = paired_with["next"] & ~pair_prev

    # An exempt return must never be zeroed as a neighbour. If a candidate offsets an exempt loss,
    # the exemption itself is in doubt: stop for a manual review.
    by_sid = is_exempt.groupby(df["sid"], sort = False)
    conflict = (pair_prev & by_sid.shift(1, fill_value = False) | pair_next & by_sid.shift(-1, fill_value = False))
    if conflict.any():
        rows = df.loc[conflict, ["sid", "datadate"]].to_string(index = False)
        raise ValueError(
            f"R5 candidates pair with an exempt return; review R5_EXEMPT:\n{rows}"
        )

    # A pair keeps its two-day return: 0 on the earlier day, the two-day return on the later day,
    # so the level after the pair is the true level.
    def shift_in_sid(values, periods, fill):
        return values.groupby(df["sid"], sort = False).shift(periods, fill_value = fill)
    earlier = pair_next | shift_in_sid(pair_prev, -1, False)
    later = pair_prev | shift_in_sid(pair_next, 1, False)
    if (earlier & later).any():
        rows = df.loc[earlier & later, ["sid", "datadate"]].to_string(index = False)
        raise ValueError(
            f"overlapping R5 pairs; review by hand:\n{rows}"
        )
    carried = shift_in_sid(two_day["next"], 1, np.nan)
    new_ret = df["ret_adj"].copy()
    new_ret[target | earlier] = 0.0
    new_ret[later] = two_day["previous"].where(pair_prev, carried)[later]
    unpaired = target & ~earlier & ~later
    review_distant_offsets(df, unpaired)

    log("R5", "candidates", candidate.sum(), df.loc[candidate, "sid"].nunique())
    log("R6", "candidates exempt from R5", is_exempt.sum(), df.loc[is_exempt, "sid"].nunique())
    log("R5", "unpaired candidate returns set to 0", unpaired.sum(), df.loc[unpaired, "sid"].nunique())
    log("R5", "pairs: two-day return moved to later day", later.sum(), df.loc[later, "sid"].nunique())
    changed = unpaired | earlier | later
    record("R5", df, changed, "ret_adj", df["ret_adj"], new_ret)
    df["ret_adj"] = new_ret
    return df.drop(columns = "prev_ajexdi")

# %% Block7. R11 Fund codes, R6 fund list, R12 country of incorporation
# =================================================================================================

FUND_SIC = ["6722", "6726"] 
#R11: open-end funds, unit trusts and closed-end funds
#R6: fund structures outside those codes, reviewed by hand (audit Appendix B).
FUND_SIDS = [
    "334189_01W", "338652_01W", "354688_01W", "360936_01W", "360955_01W",  # venture capital trusts
    "317049_01W", "318314_01W",  # zero-dividend preference shares
    "275853_01W", "281799_01W", "282866_01W", "285008_01W", "297720_01W", "313845_01W",  # "FUND" in the name
    "201019_01W", "297187_01W", "298091_01W", "314166_01W", "325198_01W", "328536_01W", "328934_01W",  # closed-end investment companies, sic 6799
]
KEEP_FIC = ["GBR", "JEY", "GGY", "IMN"]  # R12: None turns the filter off (robustness check)

def drop_rows(df, drop, rule, action):
    """Remove the flagged rows and log how many rows and sids they cover."""
    log(rule, action, drop.sum(), df.loc[drop, "sid"].nunique())
    return df.loc[~drop].reset_index(drop = True)

def select_universe(df, fund_sids = FUND_SIDS, keep_fic = KEEP_FIC):
    """R11, R6 and R12: drop funds and companies incorporated outside the UK and the Crown Dependencies.
    sic and fic are company-level snapshots, so each filter removes whole sid and no return chain is cut."""
    varies = df.groupby("sid", sort = False)[["sic", "fic"]].nunique(dropna = False).gt(1)
    if varies.any().any():
        raise ValueError("sic or fic changes within a sid; a filter would cut a whole chain")
    missing = sorted(set(fund_sids) - set(df["sid"]))
    if missing:
        raise ValueError(
            f"R6 fund sids not in the data: {missing}"
        )

    df = drop_rows(df, df["sic"].isin(FUND_SIC), "R11", "fund sic codes removed")
    df = drop_rows(df, df["sid"].isin(fund_sids), "R6", "listed fund securities removed")
    if keep_fic is not None:
        df = drop_rows(df, ~df["fic"].isin(keep_fic), "R12", "incorporated outside kept countries removed")
    return df

# %% Block 8. R10 one line per company per day
# =================================================================================================

COMPANY_DAY = ["gvkey", "datadate"]

def r10_cases(flags):
    """Count company-days by R10 case; raise on cases 3, 6b and 7."""
    days = flags.groupby(COMPANY_DAY, sort = False).agg(
        lines   = ("sid", "size"), 
        primary = ("primary", "sum"), 
        valid   = ("valid_cap", "sum"), 
        at_max  = ("at_max", "sum"))
    several = days["lines"].gt(1)
    no_primary = several & days["primary"].eq(0)
    all_valid = days["valid"].eq(days["lines"])
    some_valid = days["valid"].gt(0) & ~all_valid
    cases = {
        "1": ~several,
        "2": several & days["primary"].eq(1),
        "3": several & days["primary"].gt(1),
        "4": no_primary & all_valid & days["at_max"].eq(1),
        "5": no_primary & all_valid & days["at_max"].gt(1),
        "6a": no_primary & some_valid & days["at_max"].eq(1),
        "6b": no_primary & some_valid & days["at_max"].gt(1),
        "7": no_primary & days["valid"].eq(0),  
    }
    for name in ["3", "6b", "7"]:
        if cases[name].any():
            gvkey, date = cases[name].idxmax()
            raise ValueError(
                f"R10 case {name} on {int(cases[name].sum())} company-days, "
                f"first {gvkey} {date.date()}; see audit R10"
            )
    return {name: int(mask.sum()) for name, mask in cases.items()}

def select_lines(df):
    """R10: keep one line per company and day.

    Order within a company-day: the primary line, then the largest valid market value (prccd * cshoc),
    then the smallest iid. 
    When the chosen line differs from the one chosen on the company's previous day, that day's return
    is set to missing."""
    with np.errstate(over = "ignore", invalid = "ignore"):
        cap = df["prccd"] * df["cshoc"]
    valid_cap = positive(cap)
    flags = pd.DataFrame({
        "gvkey"    : df["gvkey"],
        "datadate" : df["datadate"],
        "sid"      : df["sid"],
        "iid"      : df["iid"],
        "primary"  : df["iid"].eq(df["prirow"]),
        "valid_cap": valid_cap,
        "cap"      : cap.where(valid_cap),
    })
    day_max = flags.groupby(COMPANY_DAY, sort = False)["cap"].transform("max")
    flags["at_max"] = flags["valid_cap"] & flags["cap"].eq(day_max)
    counts = r10_cases(flags)

    ranked = flags.sort_values(
        COMPANY_DAY + ["primary", "cap", "iid"],
        ascending = [True, True, False, False, True], 
        na_position = "last"
    )
    keep = ~ranked.duplicated(COMPANY_DAY)  # first row of each company-day
    keep = keep.reindex(df.index)           # back to the order of df
    log("R10", "rows on other lines removed", (~keep).sum(), df.loc[~keep, "sid"].nunique())
    df = df.loc[keep].sort_values(COMPANY_DAY).reset_index(drop = True)

    previous = df.groupby("gvkey", sort = False)["sid"].shift(1)
    switch = previous.notna() & df["sid"].ne(previous)
    df["line_switch"] = switch
    record("R10", df, switch, "ret_adj", df["ret_adj"], np.nan)
    df.loc[switch, "ret_adj"] = np.nan
    log("R10", "switch-day returns set to missing", switch.sum(), df.loc[switch, "sid"].nunique())

    _REVIEW.append("R10 company-days by cases: " + ", ".join(f"{name} {n:,}" for name, n in counts.items() if n))
    _REVIEW.append(f"R10 line switches: {int(switch.sum())} days in "
                   f"{df.loc[switch, 'gvkey'].nunique()} companies")
    return df

# %% Block9. Engine fields: close, raw_close, dollar_volume, is_tradable (R9)
# =================================================================================================

VOLUME_GAP = ("2017-06-19", "2017-10-13")   # R9, both ends included

def build_close(df):
    """close: a total-return level per company, equal to chaining (1 + ret_adj).
    
    Written as close = tri * c, where c is constant within a company except on:
        - R5 days, where the cleaned return is not the index move, and
        - R10 switch days, where c puts the new line on the old line's level.
    Across other missing returns (R2, R4, R6, R14) the level follows tri.
    ret_adj is an observed one-day return: it is missing across missing trading days (R14)
    and on days changed by R5, where only the level carries the cleaned move.
    close is hidden where the engine would otherwise compute a removed return:
    the return is missing but the previous trading day has a level."""
    by_company = df.groupby("gvkey", sort = False)
    step = df["tri"] / by_company["tri"].shift(1)
    switch = df["line_switch"]

    # R5: the cleaned differs from the index move (bit-identical otherwise)
    r5 = df["ret_adj"].notna() & df["ret_adj"].ne(step - 1)
    #R10: the company's last valid index value before the switch day.
    last_tri = df["tri"].groupby(df["gvkey"], sort = False).ffill()
    last_tri = last_tri.groupby(df["gvkey"], sort = False).shift(1)
    broken = switch & ~(positive(df["tri"]) & positive(last_tri))
    if broken.any():
        raise ValueError(
            f"{int(broken.sum())} line switches without a valid index on both sides"
        )

    move = pd.Series(1.0, index = df.index)
    move[r5] = (1 + df.loc[r5, "ret_adj"]) / step[r5]
    move[switch] = last_tri[switch] / df.loc[switch, "tri"]
    level = df["tri"] * move.groupby(df["gvkey"], sort = False).cumprod()

    # The level keeps every cleaned move, but two kinds of return are not observed one-day returns and are set to missing:
    # R14, a return across missing trading days; R5, a return changed by R5 (0, or a pair's two-day return).
    one_day = follows_previous_day(df["datadate"], df["gvkey"])
    multi_day = df["ret_adj"].notna() & ~one_day
    r5_day = r5 & ~multi_day
    record("R14", df, multi_day, "ret_adj", df["ret_adj"], np.nan)
    record("R5", df, r5_day, "ret_adj", df["ret_adj"], np.nan)
    df.loc[multi_day | r5_day, "ret_adj"] = np.nan

    # Hide close only where the engine would otherwise compute a removed return.
    previous_level = level.groupby(df["gvkey"], sort = False).shift(1)
    hidden = df["ret_adj"].isna() & level.notna() & previous_level.notna() & one_day
    df["close"] = level.mask(hidden)

    no_price = level.isna()
    log("R5", "changed returns carried into close", r5.sum(), df.loc[r5, "sid"].nunique())
    log("R5", "changed returns: daily return set to missing", r5_day.sum(), df.loc[r5_day, "sid"].nunique())
    log("R14", "returns across missing days set to missing", multi_day.sum(), df.loc[multi_day, "sid"].nunique())
    log("F2", "close missing: no valid price", no_price.sum(), df.loc[no_price, "sid"].nunique())
    log("F2", "close missing: return missing", hidden.sum(), df.loc[hidden, "sid"].nunique())

    # Valid returns the engine cannot see: the day after a hidden close.
    after_hidden = hidden.groupby(df["gvkey"], sort = False).shift(1, fill_value = False)
    unseen = df["ret_adj"].notna() & after_hidden
    valid = int(df["ret_adj"].notna().sum())
    _REVIEW.append(f"Engine sees {valid - int(unseen.sum()):,} of {valid:,} valid returns; "
                   f"{int(unseen.sum())} follow a hidden close")
    return df

def add_trading_fields(df, gap = VOLUME_GAP):
    """raw_close, dollar_volume and R9 is_tradable.
    
    Tradable: a valid price and positive volume. Inside the 2017 volume gap, a price gap also counts.
    A row without a valid price is never tradable."""
    start, end = map(pd.Timestamp, gap)
    in_gap = df["datadate"].between(start, end)
    traded = df["cshtrd"].gt(0)
    moved = df["ret_raw"].notna() & df["ret_raw"].ne(0)
    by_move = in_gap & ~traded & moved

    df["raw_close"] = df["prccd"]
    df["dollar_volume"] = df["prccd"] * df["cshtrd"]
    cap = df["prccd"] * df["cshoc"]
    df["market_cap"] = cap.where(positive(cap))
    df["is_tradable"] = positive(df["prccd"]) & (traded | by_move)

    tradable = df["is_tradable"]
    log("R9", "tradable rows", tradable.sum(), df.loc[tradable, "sid"].nunique())
    log("R9", "tradable only by price change in volume gap", by_move.sum(), df.loc[by_move, "sid"].nunique())
    return df

# %%
# Block 10. Final checks and the output file
# =================================================================================================

# Output column <- working column. The engine reads the first six;
# ret_adj and market_cap are for the ML project (data_loader for backtest ignores the undeclared columns).

OUTPUT_COLUMNS = {
    "date": "datadate",
    "symbol": "gvkey",
    "close": "close",
    "raw_close": "raw_close",
    "dollar_volume": "dollar_volume",
    "is_tradable": "is_tradable",
    "ret_adj": "ret_adj",
    "market_cap": "market_cap",
}
POSITIVE_OUTPUTS = ["close", "raw_close", "market_cap"]
RETURN_TOLERANCE = 1e-9

def validate_output(out):
    """Everything the engine and the ML project rely on; raise listing every failure."""
    problems= []
    if out[["date", "symbol"]].isna().any().any():
        problems.append("missing date or symbol")
    duplicates = out.duplicated(["date", "symbol"])
    if duplicates.any():
        problems.append(f"{int(duplicates.sum())} duplicate (date, symbol) rows")
    if not out["symbol"].str.fullmatch(r"\d{6}").all():
        problems.append("symbol is not a 6-digit gvkey")
    days = trading_days()
    if not pd.DatetimeIndex(out["date"].unique()).sort_values().equals(days):
        problems.append("dates differ from the 2,779-day trading calendar")

    for column in POSITIVE_OUTPUTS:
        values = out[column].dropna()
        as_float32 = values.astype("float32")
        if not (np.isfinite(as_float32) & as_float32.gt(0)).all():
            problems.append(f"{column}: non-positive or non-finite values (after float32)")
    volume = out["dollar_volume"].dropna()
    if not (np.isfinite(volume) & volume.ge(0)).all():
        problems.append("dollar_volume: negative or non-finite values")
    if out["is_tradable"].dtype != bool:
        problems.append("is_tradable is not boolean")
    if (out["is_tradable"] & out["raw_close"].isna()).any():
        problems.append("tradable rows without a price")

    # Returns: ret_adj is a one-day return; the engine computes close over the previous trading day's close,
    # and must get exactly ret_adj wherever it can.
    out = out.sort_values(["symbol", "date"])
    ret = out["ret_adj"].copy()
    one_day = follows_previous_day(out["date"], out["symbol"])
    if not (np.isfinite(ret.dropna()) & ret.dropna().gt(-1)).all():
        problems.append("ret_adj: non-finite values or values at or below -100%")
    if (ret.notna() & ~one_day).any():
        problems.append(f"{int((ret.notna() & ~one_day).sum())} returns span missing trading days")
    previous = out.groupby("symbol", sort = False)["close"].shift(1)
    seen = one_day & out["close"].notna() & previous.notna()
    error = (out["close"] / previous - 1 - ret)[seen].abs()
    disagree = error.isna() | error.gt(RETURN_TOLERANCE)
    if disagree.any():
        problems.append(f"close and ret_adj disagree on {int(disagree.sum())} rows")

    if problems:
        raise ValueError("output checks failed:\n " + "\n ".join(problems))

def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

def write_csv(frame, path, **options):
    """Write through a temporary file, so a failed run never leaves a half-written file."""
    path.parent.mkdir(parents = True, exist_ok = True)
    temporary = path.with_name(path.name + ".tmp")
    frame.to_csv(temporary, index = False, date_format = "%Y-%m-%d", float_format = "%.10g", lineterminator = "\n", **options)
    temporary.replace(path)

def write_output(df, path = OUTPUT_FILE):
    """Select and rename the output columns, check them, write a gzip CSV."""
    out = df[list(OUTPUT_COLUMNS.values())].copy()
    out.columns = list(OUTPUT_COLUMNS)
    validate_output(out)

    write_csv(out, path, compression = {"method": "gzip", "mtime": 0})
    log("F1", "rows written", len(out), out["symbol"].nunique())
    _REVIEW.append(f"Output {path.name}: {path.stat().st_size / 1e6:,.1f} MB, "
                   f"SHA-256 {file_sha256(path)}")
    return out

def write_company_table(df, path = COMPANY_FILE):
    """One row per symbol: name, codes and exit data. R13 itself is applied by the engine."""
    by_company = df.groupby("gvkey", sort = True)
    if by_company[["sic", "fic", "dlrsn", "dldte"]].nunique(dropna = False).gt(1).any().any():
        raise ValueError("sic, fic, dlrsn, dldte changes within a company")
    table = by_company.agg(
        conm = ("conm", "last"), sic = ("sic", "first"), fic = ("fic", "first"),
        dlrsn = ("dlrsn", "first"), dldte = ("dldte", "first"),
        first_date = ("datadate", "min"), last_date = ("datadate", "max"),
    ).rename_axis("symbol").reset_index()
    table["dldte"] = pd.to_datetime(table["dldte"])
    write_csv(table,path)
    log("F1", "company rows written", len(table), len(table))
    exits = table["last_date"].lt(pd.Timestamp(SAMPLE_END))
    _REVIEW.append(f"Companies whose last row is before {SAMPLE_END}: {int(exits.sum()):,}")

def write_events(path = EVENT_FILE):
    """Every row-level change made by R2, R4-R6, R10 and R14, with old and new values."""
    events = pd.concat(_EVENTS, ignore_index = True)
    events = events[["rule", "sid", "datadate", "field", "before", "after"]]
    write_csv(events.rename(columns = {"datadate": "date"}), path)
    log("F1", "change events written", len(events), events["sid"].nunique())

def write_manifest(path = MANIFEST_FILE):
    """Input, parameters, versions, the step log and output hashes of this run."""
    manifest = {
        "input": {"file": RAW_FILE.name, "sha256": EXPECTED_SHA256},
        "outputs": {p.name: file_sha256(p) for p in [OUTPUT_FILE, COMPANY_FILE, EVENT_FILE]},
        "versions": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
        "parameters": {
            "R4_FACTOR_MOVE": R4_FACTOR_MOVE, "BAD_PRINTS": BAD_PRINTS,
            "R5_ABS_RET": R5_ABS_RET, "R5_AJ_RATIO": [R5_AJ_RATIO_LOW, R5_AJ_RATIO_HIGH],
            "R5_PAIR_TOLERANCE": R5_PAIR_TOLERANCE, "R5_REVIEW_WINDOW": R5_REVIEW_WINDOW,
            "R5_EXEMPT": R5_EXEMPT, "FUND_SIC": FUND_SIC, "FUND_SIDS": FUND_SIDS,
            "KEEP_FIC": KEEP_FIC, "VOLUME_GAP": VOLUME_GAP, "NON_TRADING_DAYS": len(NON_TRADING_DAYS),
        },
        "log": [dict(zip(["rule", "action", "rows", "sids"], row)) for row in _LOG],
        "review": _REVIEW,
    }
    path.write_text(json.dumps(manifest, indent = 2) + "\n", encoding = "utf-8")

# =================================================================================================
def main():
    _LOG.clear()
    _REVIEW.clear()
    _EVENTS.clear()
    print_log_header()
    check_source()
    df = load()
    df = count_currency_breaks(df)
    df = keep_segment(df)
    df = keep_trading_days(df)
    df = mark_currency_breaks(df)
    df = fix_stuck_adjustments(df)
    df = remove_bad_prints(df)
    df = line_returns(df)
    df = clean_adjustments(df)
    df = select_universe(df)
    df = select_lines(df)
    df = build_close(df)
    df = add_trading_fields(df)
    write_output(df)
    write_company_table(df)
    write_events()
    print(f"\n{'rows':<10}{len(df):>12,}")
    print(f"{'sids':<10}{df['sid'].nunique():>12,}")
    print(f"{'companies':<10}{df['gvkey'].nunique():>12,}")
    print(f"{'days':<10}{df['datadate'].nunique():>12,}")
    if _REVIEW:
        print("\nReview")
        print("\n".join(_REVIEW))
    write_manifest()
    return df

if __name__ == "__main__":
    main()