# factor-backtest

A cross-sectional equity factor backtesting engine, written from scratch in Python
(personal project, August 2026 – present). Momentum, short-term reversal and
low-volatility factors are sorted into monthly decile portfolios on UK equities
(WRDS Compustat Global, 2014–2024).

**Status: work in progress.** Data loading, factors and portfolio construction are
done; the WRDS data pipeline is being built; the backtest loop and results come next.

## Design principles

- **No look-ahead.** A signal at date t uses data up to t's close; positions are
  executed at the next close.
- **Missing data is never filled.** A missing price or return stays missing.
- **Locked holdout.** Everything from 2022-01-01 is held out and was fixed before any
  result was seen (`config.HOLDOUT_START`).
- **Fail loudly.** Every module validates its output (shapes, warm-up rows, bucket
  sizes, dollar neutrality) and raises instead of silently continuing.

## Repository layout

| File                         | Purpose                                                                           |
|------------------------------|-----------------------------------------------------------------------------------|
| `config.py`                  | All settings: data source, lookbacks, rebalance frequency, holdout date           |
| `prepare_wrds.py`            | Cleans the raw WRDS file into the engine's input (rules in `docs/`)               |
| `data_loader.py`             | The only data boundary: long file to wide date × symbol panels, cached as parquet |
| `factors.py`                 | Momentum (12-1), reversal (1 month), low volatility (60 days)                     |
| `portfolio.py`               | Month-end decile sorts and equal-weight long-short weights                        |
| `docs/data_audit_wrds_uk.md` | Data audit: 14 cleaning rules, their assumptions and evidence                     |

## Data

| Source    | Description                                                          | Included                               |
|-----------|----------------------------------------------------------------------|----------------------------------------|
| Synthetic | 1,000 simulated stocks, 2014–2024, used to build and test the engine | No (109 MB, above GitHub's file limit) |
| WRDS      | Compustat Global, London Stock Exchange, 2014–2024                   | No (licensed)                          |

The WRDS data cannot be redistributed. The audit in
[`docs/data_audit_wrds_uk.md`](docs/data_audit_wrds_uk.md) documents what the raw data
contain, what is wrong with them (rights issues adjusted as splits, a 2017 volume gap,
duplicate share lines, stale prices) and how each problem is handled. 

To rebuild the WRDS input with your own access: place the file at
`data/wrds_uk_prices.csv.gz` (its SHA-256 must match `config.WRDS_SHA256`) and run
`python prepare_wrds.py`.

## How to run

```bash
conda env create -f environment.yml
conda activate quant

python data_loader.py    # build and cache the panels
python factors.py        # compute and validate the three factors
python portfolio.py      # build month-end decile portfolios
```

Set `SOURCE` in `config.py` to `"synthetic"` or `"wrds"`.

## Results

Coming once the backtest loop is complete.
