"""Central configuration. No logic here - only settings."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent

# Locked BEFORE any results are seen. Do not change after Phase 1.
HOLDOUT_START = "2022-01-01"

# --- Backtest settings ---
REBALANCE = "ME"        # monthly rebalancing
N_BUCKETS = 10          # deciles: 1000 symbols gives 10 per bucket
COST_BPS = 10           # flat one-way transaction cost assumption

# --- Factor lookbacks (trading days) ---
MOM_LOOKBACK = 252     # 12 months
MOM_SKIP     = 21      # skip most recent month
REV_LOOKBACK = 21      # short-term reversal: past 1 month
REV_SKIP     = 0       # skip for short-term reversal: default 0, but can be set to 1 to remove bid-ask bounce
VOL_LOOKBACK = 60      # low-volatility: trailing 60 days

# --- Paths ---
DATA_DIR   = ROOT / "data"
RAW_PRICE_FILE = DATA_DIR / "synthetic_prices.csv.gz"
SOURCE = "synthetic"