# factor-backtest

A cross-sectional equity factor backtesting engine, written from scratch in Python
(personal project, August 2026 – present). Momentum, short-term reversal and
low-volatility factors are sorted into monthly decile portfolios on UK equities
(WRDS Compustat Global, 2014–2024).

**Status: work in progress.** Data loading, the WRDS cleaning pipeline, factors and portfolio construction are
done; the backtest loop and results come next.

## Design principles

- **No look-ahead.** A signal at date t uses data up to t's close; positions are
  executed at the next close.
- **Missing data is never filled.** A missing price or return stays missing.
- **Locked holdout.** Everything from 2022-01-01 is held out and was fixed before any
  result was seen (`config.HOLDOUT_START`).
- **Fail loudly.** Every module validates its output (shapes, warm-up rows, bucket
  sizes, dollar neutrality) and raises instead of silently continuing.
- **Reproducible data.** 'prepare_wrds.py' refuses any input other than the audited file, 
  and the same input always produces a byte-identical output.

## Repository layout

| File                         | Purpose                                                                           |
|------------------------------|-----------------------------------------------------------------------------------|
| `config.py`                  | All settings: data source, lookbacks, rebalance frequency, holdout date           |
| `prepare_wrds.py`            | Cleans the raw WRDS file into the engine's input (rules in `docs/`)               |
| `data_loader.py`             | The only data boundary: long file to wide date × symbol panels, cached as parquet |
| `factors.py`                 | Momentum (12-1), reversal (1 month), low volatility (60 days)                     |
| `portfolio.py`               | Month-end decile sorts and equal-weight long-short weights                        |
| `docs/data_audit_wrds_uk.md` | Data audit: each cleaning rule, its assumptions and evidence for them                    |

## Data

| Source    | Description                                                          | Included                               |
|-----------|----------------------------------------------------------------------|----------------------------------------|
| Synthetic | 1,000 simulated stocks, 2014–2024, used to build and test the engine | No (109 MB, above GitHub's file limit) |
| WRDS      | Compustat Global, London Stock Exchange, 2014–2024; 1,955 companies after cleaning              | No (licensed)                          |

The WRDS data cannot be redistributed. The audit in
[`docs/data_audit_wrds_uk.md`](docs/data_audit_wrds_uk.md) documents what the raw data
contain, what is wrong with them (rights issues adjusted as splits, a 2017 volume gap,
duplicate share lines, stale prices) and how each problem is handled. 

To rebuild the WRDS input with your own access: download the data as described in 
Section 1 of the audit, place the file at 'data/wrds_uk_prices.csv.gz' (its SHA-256 must 
match 'config.WRDS_SHA256') and run 'python prepare_wrds.py'. It writes
'data/wrds_clean.csv.gz' and prints the number of rows each rule changes, so the run can 
be checked against the audit.

## How to run

```bash
conda env create -f environment.yml
conda activate quant

python prepare_wrds.py   # WRDS only: clean the raw file into data/wrds_clean.csv.gz
python data_loader.py    # build and cache the panels
python factors.py        # compute and validate the three factors
python portfolio.py      # build month-end decile portfolios
```

Set `SOURCE` in `config.py` to `"wrds"` (default) or "synthetic"'. Neither data file is
in the repositoey, so the commands need the matching input file in 'data/'.

## Results

Coming once the backtest loop is complete.
