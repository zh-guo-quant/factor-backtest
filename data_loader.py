"""Load raw price data into wide price panel, cached as parquet.

This module is the project's only data boundary: no other file reads a raw
price file. Adding a data source means adding a SourceSchema to SOURCES;
nothing downstream changes.

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
    "vwap": "float32",
    "dollar_volume": "float32",
    "is_tradable": "bool",
}

FIELDS = tuple(FIELD_DTYPES)
POSITIVE_FIELDS = ("close", "vwap")

DATE_NAMES = {"date", "datetime", "time", "timestamp", "dt", "trade_date"}
SYMBOL_NAMES = {"ticker", "symbol", "sid", "asset", "code", "stock", "permno"}
FIELD_NAMES ={
    "close": {"close", "adj_close", "adjclose", "price", "px", "px_last"},
    "vwap": {"vwap", "twap", "avg_price"},
    "dollar_volume": {"dollar_volume", "turnover", "amount", "value_traded"},
    "is_tradable": {"is_tradable", "tradable", "tradeable", "active"},
}

# --- Source declarations --------------------------------------------------------

class SourceSchema(NamedTuple):
    """How one data source lays out its columns. Declared."""

    layout : str                            # "long" or "wide"
    date : str                              # the date column
    symbol : str | None = None              # long only: the symbol column
    fields : dict[str, str] | None = None   # long only: canonical -> source column
    value_field : str | None = None         # wide only: what the symbol columns hold

    def validate(self) -> None:
        if self.layout == "long":
            if not self.symbol or not self.fields:
                raise ValueError("Long layout needs both 'symbol' and 'fields'")

            unknown = set(self.fields) - set(FIELDS)
            if unknown:
                raise ValueError(
                    f"Unknown canonical fields {sorted(unknown)}; expected {FIELDS}. "
                )

            bad = {k: v for k, v in self.fields.items() if not isinstance(v, str)}
            if bad:
                raise ValueError(
                    f"`fields` values must be column-name strings, got {bad}"
                )
            
        elif self.layout == "wide":
            if not self.value_field:
                raise ValueError("Wide layout needs 'value_field'")
            if self.value_field not in FIELDS:
                raise ValueError(
                    f"Unknown canonical fields {self.value_field!r}; expected {FIELDS}. "
                )
        else:
            raise ValueError(f"Unknown layout: {self.layout}; use 'long' or 'wide'")

SYNTHETIC = SourceSchema(
    layout = "long",
    date = "date",
    symbol = "symbol",
    fields = {
        "close": "close",
        "vwap": "vwap",
        "dollar_volume": "dollar_volume",
        "is_tradable": "is_tradable"
    }
)

SOURCES = {"synthetic": SYNTHETIC}

def _schema() -> SourceSchema:
    """The schema for the source config selects."""
    try:
        schema = SOURCES[config.SOURCE]
    except KeyError:
        raise KeyError(
            f"Unknown source {config.SOURCE!r}.Known sources: {sorted(SOURCES)}."
        ) from None
    schema.validate()
    return schema

def _verify_schema(schema: SourceSchema) -> None:
    """Read five rows and confirm the file matches what the schema declares."""
    present = list(pd.read_csv(config.RAW_PRICE_FILE, nrows = 5).columns)
    present_set = set(present)
    name = config.RAW_PRICE_FILE.name

    if schema.date not in present_set:
        raise KeyError(
            f"{name}: declared date column {schema.date!r} is absent. "
            f"Actual columns: {present}. "
        )
    
    if schema.layout == "long":
        declared = [schema.symbol, *schema.fields.values()]
        missing = [c for c in declared if c not in present_set]
        if missing:
            raise KeyError(
                f"{name} is missing declared columns {missing}. "
                f"Actual columns: {present}. "
                f"Fix the SourceSchema for {config.SOURCE!r}, or run suggested_schema(). "
            )

    else:
        symbol_cols = [c for c in present if c != schema.date]
        if not symbol_cols:
            raise ValueError(f"{name}: layout = 'wide' but no symbol columns found.")

        reserved = SYMBOL_NAMES.union(*FIELD_NAMES.values())
        field_like = [c for c in symbol_cols if str(c).strip().lower() in reserved]
        if field_like:
            raise ValueError(
                f"{name}: layout='wide' but columns {field_like} are field names, "
                f"not symbols - this file is probably long. "
                f"Fix the SourceSchema for {config.SOURCE!r}, or run suggest_schema()."
            )

def _declared_fields(schema: SourceSchema) -> tuple[str, ...]:
    """Canonical field names this source provide, whatever its layout."""
    if schema.layout == "long":
        return tuple(schema.fields)
    return (schema.value_field,)

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

    panel = panel.astype(FIELD_DTYPES[field])
    panel.index.name = "date"
    panel.columns.name = "symbol"
    return panel.sort_index().sort_index(axis = 1)

def _build_panels(schema: SourceSchema) -> dict[str, pd.DataFrame]:
    """Every panel this source provides, keyed by canonical field name.

    This is the only place layout is branched on: everything below sees the
    same thing, a dict of aligned wide panels.
    """
    if schema.layout == "long":
        raw = _read_long(schema)
        print(f" read {len(raw):,} rows * {len(raw.columns)} columns")
        return {field: _pivot(raw, schema, field) for field in schema.fields}

    raise NotImplementedError(
        "layout='wide' is declared and verified but not yet loadable; "
        "implement _read_wide() when a real wide source arrives."
    )

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
    return config.DATA_DIR / f"panel_{field}.parquet"

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
            f"Source {config.SOURCE!r} does not provide {field!r};"
            f"it provides {sorted(available)}. "
        )

    path = _cache_path(field)
    if force_rebuild or not path.exists():
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