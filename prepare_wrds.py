# %% Block1. Settings and the step log
# =================================================================================================
"""Build the engine input file for source 'wrds' from the audited WRDS_UK file.

Rules (F1 - F3, R1 - R14) are documented in docs/data_audit_wrds_uk.md.
Every step records how many rows it changed, so the log can be checked against the audit report.

Output: data/wrds_clean.csv.gz, one row per company and trading day:
date, symbol, close, raw_close, dollar_volume, is_tradable.
"""

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
    The running count is kept so that R1 and R3 can drop rows without losing a break that sat on a dropped row.
    """
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

# =================================================================================================
def main():
    _LOG.clear()
    print_log_header()
    check_source()
    df = load()
    df = count_currency_breaks(df)
    df = keep_segment(df)
    df = keep_trading_days(df)
    df= mark_currency_breaks(df)
    print(f"\n{'rows':<10}{len(df):>12,}")
    print(f"{'sids':<10}{df['sid'].nunique():>12,}")
    print(f"{'companies':<10}{df['gvkey'].nunique():>12,}")
    print(f"{'days':<10}{df['datadate'].nunique():>12,}")
    return df

if __name__ == "__main__":
    main()