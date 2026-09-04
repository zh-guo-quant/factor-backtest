"""Central configuration. No logic here - only settings."""

# --- Universe ---
# Start small to build the pipeline. Scale to 100+ in Phase 5.
TICKERS = [
    "AAPL", "MSFT", "JNJ", "XOM", "JPM",
    "PG", "KO", "CVX", "WMT", "MRK",
    "PEP", "ABT", "MCD", "CSCO", "ORCL",
    "T", "VZ", "INTC", "IBM", "CAT",
]

# --- Sample period ---
START = "2010-01-01"
END   = "2026-09-01"

# Locked BEFORE any results are seen. Do not change after Phase 1.
HOLDOUT_START = "2022-01-01"

# --- Backtest settings ---
REBALANCE = "M"        # monthly rebalancing
N_BUCKETS = 5          # quintiles for small universes; switch to 10 at 100+ names
COST_BPS = 10          # flat one-way transaction cost assumption

# --- Factor lookbacks (trading days) ---
MOM_LOOKBACK = 252     # 12 months
MOM_SKIP     = 21      # skip most recent month
REV_LOOKBACK = 21      # short-term reversal: past 1 month
VOL_LOOKBACK = 60      # low-volatility: trailing 60 days

# --- Paths ---
DATA_DIR   = "data"
PRICE_FILE = "data/prices.parquet"