"""Load raw price data into wide price panel, cached as parquet.

This module is the project's only data boundary: no other file reads a raw price file.
Every source arrives as one long file written by its own prepare script (e.g. prepare_wrds.py).
Adding a source means adding a SourceSchema to SOURCES.

Panel Contract
--------------
index   : DatetimeIndex, strictly increasing, no duplicates
columns : symbols, sorted
values  : float32 for prices, bool for flags
"""

from typing import NamedTuple
from pathlib import Path

import pandas as pd

import config

# --- Canonical vocabulary-----------------------------------------------------------

FIELD_DTYPES = {
    "close": "float32",
    "raw_close": "float32",
    "vwap": "float32",
    "dollar_volume": "float32",
    "is_tradable": "bool",
}

FIELDS = tuple(FIELD_DTYPES)
POSITIVE_FIELDS = ("close", "raw_close", "vwap")


# --- Source declarations --------------------------------------------------------

class SourceSchema(NamedTuple):
    """How one long source file names its columns. Declared."""

    date : str                              # the date column
    symbol : str | None = None              # long only: the symbol column
    fields : dict[str, str] | None = None   # long only: canonical -> source column

    def validate(self) -> None:
        unknown = set(self.fields) - set(FIELDS)
        if unknown:
            raise ValueError(
                f"Unknown canonical fields {sorted(unknown)}; expected {FIELDS}."
            )
        bad = {k: v for k, v in self.fields.items() if not isinstance(v, str)}
        if bad:
            raise ValueError(
                f"'fields' value must be column-name strings, got {bad}."
            )
        
SYNTHETIC = SourceSchema(
    date = "date",
    symbol = "symbol",
    fields = {
        "close": "close",
        "raw_close": "close",
        "vwap": "vwap",
        "dollar_volume": "dollar_volume",
        "is_tradable": "is_tradable"
    }
)

WRDS = SourceSchema(
    date = "date",
    symbol = "symbol",
    fields = {
        "close": "close",
        "raw_close": "raw_close",
        "dollar_volume": "dollar_volume",
        "is_tradable": "is_tradable",
    }
)

SOURCES = {"synthetic": SYNTHETIC, "wrds": WRDS}

def _schema() -> SourceSchema:
    """The schema for the source config selects."""
    try:
        schema = SOURCES[config.SOURCE]
    except KeyError:
        raise KeyError(
            f"Unknown source {config.SOURCE!r}. Known sources: {sorted(SOURCES)}. "
        ) from None
    schema.validate()
    return schema

def _verify_schema(schema: SourceSchema) -> None:
    """Read five rows and confirm the file matches what the schema declares."""
    present = list(pd.read_csv(config.RAW_PRICE_FILE, nrows = 5).columns)
    declared = dict.fromkeys([schema.date, schema.symbol, *schema.fields.values()])
    missing = [c for c in declared if c not in present]
    
    if missing:
        raise KeyError(
            f"{config.RAW_PRICE_FILE.name} is missing declared columns {missing}, "
            f"Actual columns: {present}. Fix the SourceSchema for {config.SOURCE!r}."
        )

def _declared_fields(schema: SourceSchema) -> tuple[str, ...]:
    """Canonical field names this source provide, whatever its layout."""
    return tuple(schema.fields)

def _read_long(schema: SourceSchema) -> pd.DataFrame:
    """Read only the declared columns from a long file. No reshaping here."""
    usecols = [schema.date, schema.symbol, *schema.fields.values()]

    dtypes = {schema.symbol: "category"}
    dtypes.update({
        column: FIELD_DTYPES[canonical]
        for canonical, column in schema.fields.items()
        if FIELD_DTYPES[canonical].startswith("float")
    })

    return pd.read_csv(
        config.RAW_PRICE_FILE,
        usecols = usecols,
        parse_dates = [schema.date],
        dtype = dtypes
    )

def _pivot(raw: pd.DataFrame, schema: SourceSchema, field: str) -> pd.DataFrame:
    """One declared column of a long frame -> one wide panel."""
    column = schema.fields[field]
    try:
        panel = raw.pivot(index = schema.date, columns = schema.symbol, values = column)
    except ValueError as exc:
        n = int(raw.duplicated(subset = [schema.date, schema.symbol]).sum())
        raise ValueError(
            f"pivot failed on {field!r}: {n:,} duplicate (date, symbol) rows in "
            f"{config.RAW_PRICE_FILE.name}. Inspect them and decide explicitly "
            f"how to resolve - do not silently average."
        ) from exc

    if FIELD_DTYPES[field] == "bool":
        panel = panel.eq(True)          # a missing (date, symbol) is not tradable
    else:
        panel = panel.astype(FIELD_DTYPES[field])
    panel.index.name = "date"
    panel.columns.name = "symbol"
    return panel.sort_index().sort_index(axis = 1)

def _build_panels(schema: SourceSchema) -> dict[str, pd.DataFrame]:
    """Every panel this source provides, keyed by canonical field name."""
    
    raw = _read_long(schema)
    print(f" read {len(raw):,} rows * {len(raw.columns)} columns")

    dupes = raw.duplicated(subset = [schema.date, schema.symbol])
    if dupes.any():
        raise ValueError(
            f"{int(dupes.sum()):,} duplicate (date, symbol) rows in "
            f"{config.RAW_PRICE_FILE.name}. Inspect them and decide explicitly "
            f"how to resolve - do not silently average."
        )
    return {field: _pivot(raw, schema, field) for field in schema.fields}

def _validate(panel: pd.DataFrame, field: str) -> None:
    """Fail on anything the engine would otherwise mis-compute silently."""
    if not isinstance(panel.index, pd.DatetimeIndex):
        raise TypeError(f"{field}: index must be a DatetimeIndex. ")
    if panel.index.duplicated().any():
        raise ValueError(f"{field}: index contains duplicate dates. ")
    if not panel.index.is_monotonic_increasing:
        raise ValueError(f"{field}: index is not sorted ascending. ")

    if field in POSITIVE_FIELDS:
        n_bad = int((panel <= 0).to_numpy().sum())
        if n_bad:
            raise ValueError(f"{field}: {n_bad:,} non-positive values. ")

    missing = panel.isna().mean()
    print(f" {field:<14} {panel.shape[0]:,} * {panel.shape[1]:,} "
          f"NaN mean {missing.mean():.3%} max {missing.max():.3%}")

def _cache_path(field: str) -> Path:
    return config.DATA_DIR / f"{config.SOURCE}_{field}.parquet"

def _cache_is_stale(path: Path) -> bool:
    """A cache older than the raw file was built from a previous version of it."""
    return path.stat().st_mtime < config.RAW_PRICE_FILE.stat().st_mtime

def _build_all(schema: SourceSchema) -> None:
    """Read the raw file once, write one parquet panel per declared field."""
    print(f"Building panels from {config.RAW_PRICE_FILE} ...")
    _verify_schema(schema)

    panels = _build_panels(schema)

    config.DATA_DIR.mkdir(parents = True, exist_ok = True)
    for field, panel in panels.items():
        _validate(panel, field)
        panel.columns = panel.columns.astype(str)
        panel.to_parquet(_cache_path(field))
    print(" cached")

def load_panel(field:str, force_rebuild: bool = False) -> pd.DataFrame:
    """Return one wide panel, building the cache on first use"""
    schema = _schema()
    available = _declared_fields(schema)
    if field not in available:
        raise KeyError(
            f"Source {config.SOURCE!r} does not provide {field!r}; "
            f"it provides {sorted(available)}. "
        )

    path = _cache_path(field)
    if force_rebuild or not path.exists() or _cache_is_stale(path):
        _build_all(schema)
    return pd.read_parquet(path)

def load_prices(force_rebuild: bool = False) -> pd.DataFrame:
    """Close prices - the panel factors are computed from."""
    return load_panel("close", force_rebuild)

if __name__ == "__main__":
    prices = load_prices()
    print()
    print(f"shape       : {prices.shape[0]:,} dates * {prices.shape[1]:,} symbols")
    print(f"date range  : {prices.index.min().date()} -> {prices.index.max().date()}")
    print(f"memory      : {prices.memory_usage(deep = True).sum() / 1e6:.1f} MB")
    print()
    print(prices.iloc[:5, :5])