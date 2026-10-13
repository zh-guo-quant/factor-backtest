# %% Block1. Settings and the step log
# =================================================================================================
"""Build the engine input file for source 'wrds' from the audited WRDS_UK file.

Rules (F1 - F3, R1 - R14) are documented in docs/data_audit_wrds_uk.md.
Every step records how many rows it changed, so the log can be checked against the audit report.

Output: data/wrds_clean.csv.gz, one row per company and trading day:
date, symbol, close, raw_close, dollar_volume, is_tradable."""

import hashlib

import numpy as np
import pandas as pd

import config

RAW_FILE = config.WRDS_RAW_FILE
EXPECTED_SHA256 = config.WRDS_SHA256
OUTPUT_FILE = config.RAW_FILES["wrds"]

# Only the columns later steps use; dropping the rest at read tiem saves memory.
USE_COLUMNS = [
    "gvkey", "iid", "datadate", "conm", "tpci", "curcdd",
    "prccd", "ajexdi", "trfd", "cshtrd", "cshoc",
    "prirow", "sic", "fic", "dlrsn",
]
STRING_COLUMNS = ["gvkey", "iid", "tpci", "curcdd", "prirow", "sic", "fic", "dlrsn"]
NUMERIC_COLUMNS = ["prccd", "ajexdi", "trfd", "cshtrd", "cshoc"]
KEY = ["sid", "datadate"]

SAMPLE_START, SAMPLE_END = "2014-01-01", "2024-12-31"

# R3: the 91 non-trading days (Appendix A of the audit socument).
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

def log(rule, action, rows, securities):
    """Record one step and print it as a row of log table."""
    _LOG.append((rule, action, int(rows), int(securities)))
    print(LOG_FORMAT.format(rule, action, f"{int(rows):,}", f"{int(securities):,}"))

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
        df[column] = pd.to_numeric(df[column], errors = "coerce")
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

# %% Block 3. R2 currency breaks, R1 analysis segment, R3 trading calender.
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
    
    A row is flagged if any break occured since the previous kept row of the same sid.
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
    """Quene one review line for R4: how long the stuck runs are."""
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
    df.loc[stuck, "prccd"] = np.nan
    return df

def remove_bad_prints(df, bad_prints = BAD_PRINTS):
    """R6: set the listed bad-print prices to missing."""
    affected = set()
    for sid, date in bad_prints:
        hit = df["sid"].eq(sid) & df["datadate"].eq(pd.Timestamp(date))
        if hit.sum() != 1:
            raise ValueError(
                f"R6 bad print {sid} {date}: {int(hit.sum())} matching rows, expected 1"
            )
        df.loc[hit, "prccd"] = np.nan
        affected.add(sid)
    log("R6", "bad-print prices set to missing", len(bad_prints), len(affected))
    return df

# %% Block 5. F2 within-line returns, R2 applied
# =================================================================================================

def line_returns(df):
    """F2: total-return index and returns within each sid, on the cleaned price.
    
    A return is missing when either end has no valid index (no price, R4, R6)
    or when it crosses a currency change (R2).
    The first row of a sid has no return.
    tri and ret_adj are used again in Block 9 to build close."""
    df["tri"] = df["prccd"] / df["ajexdi"] * df["trfd"]
    previous = df.groupby("sid", sort = False)[["prccd", "ajexdi", "tri"]].shift(1)
    both_valid = positive(df["tri"]) & positive(previous["tri"])
    valid = both_valid & ~df["currency_break"]

    df["prev_ajexdi"] = previous["ajexdi"]
    df["ret_raw"] = (df["prccd"] / previous["prccd"] - 1).where(valid)
    df["ret_adj"] = (df["tri"] / previous["tri"] - 1).where(valid)

    crossed = both_valid & df["currency_break"]
    log("F2", "valid within-line returns", valid.sum(), df.loc[valid, "sid"].nunique())
    log("R2", "returns set to missing (currency change)", crossed.sum(), df.loc[crossed, "sid"].nunique())
    return df.drop(columns = "currency_break")

# %% Block 6. R5 suspect adjustment events, R6 exemptions
# =================================================================================================

R5_ABS_RET = 0.30
R5_AJ_RATIO_LOW, R5_AJ_RATIO_HIGH = 0.80, 1.25
R5_PAIR_TOLERANCE = 0.20
# R6: genuine losses that must not be zeroed; each must be an R5 candidate.
R5_EXEMPT = [
    ("270250_02W", "2018-08-02"),    # Countrywide: recapitalisation, aj_ratio = 1.77
    ("327786_01W", "2022-12-14"),    # Trackwise: recapitalisatoin, aj_ratio = 3.80
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

def clean_adjustments(df, exempt = R5_EXEMPT):
    """R5: zero the return on adjustment days whose factor moves far from 1 
    and whose adjusted return is large.
    If an adjacent return of the same sid offset it (two-day return within +/-20%),
    zero that return as well."""
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
    paired_with = {}
    for name, periods in [("previous", 1), ("next", -1)]:
        neighbour = grouped.shift(periods)
        two_day = (1 + df["ret_adj"]) * (1 + neighbour) - 1
        paired_with[name] = target & neighbour.notna() & two_day.abs().le(R5_PAIR_TOLERANCE)
    pair_prev = paired_with["previous"]
    pair_next = paired_with["next"] & ~pair_prev
    # The neighbour row of each pair: shift the flag onto it within the sid
    neighbour_rows = (pair_prev.groupby(df["sid"], sort = False).shift(-1, fill_value = False)
                      | pair_next.groupby(df["sid"], sort = False).shift(1, fill_value = False))

    log("R5", "candidates", candidate.sum(), df.loc[candidate, "sid"].nunique())
    log("R6", "candidates exempt from R5", is_exempt.sum(), df.loc[is_exempt, "sid"].nunique())
    log("R5", "candidate returns set to 0", target.sum(), df.loc[target, "sid"].nunique())
    log("R5", "paired neighbour returns set to 0", neighbour_rows.sum(), df.loc[neighbour_rows, "sid"].nunique())
    df.loc[target | neighbour_rows, "ret_adj"] = 0.0
    return df.drop(columns = "prev_ajexdi")

# %% Block7. R11 Fund codes, R6 fund list, R12 country of incorporation
# =================================================================================================

FUND_SIC = ["6722", "6726"] 
#R11: open-end funds, unit trusts and closed-end funds
#R6: fund structures outside those codes, reviewed by hand (audit Appendix B).
FUND_SIDS = [
    "334189_01W", "338652_01W", "354688_01W", "360936_01W", "360955_01W",  # ventur ecapital trusts
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


# =================================================================================================
def main():
    _LOG.clear()
    _REVIEW.clear()
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
    print(f"\n{'rows':<10}{len(df):>12,}")
    print(f"{'sids':<10}{df['sid'].nunique():>12,}")
    print(f"{'companies':<10}{df['gvkey'].nunique():>12,}")
    print(f"{'days':<10}{df['datadate'].nunique():>12,}")
    if _REVIEW:
        print("\nReview")
        print("\n".join(_REVIEW))
    return df

if __name__ == "__main__":
    main()
# %%
