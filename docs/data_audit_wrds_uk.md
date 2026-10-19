# Data audit: WRDS Compustat Global, UK listings

This document records the cleaning rules adopted for the WRDS UK data, the assumptions
behind each rule, and the evidence that supports each assumption. The rules are
implemented in `prepare_wrds.py`. The evidence comes from the audit script `data_test.py`,
the R10 check script `check_r10.py` and manual review (Section 2).

Two kinds of numbers appear in this project. Audit numbers describe the raw data and come
from the audit report; they do not change while the input file is the same. The rows each
cleaning step changes, the final sample and the output hashes are written by
`prepare_wrds.py` to the run record `docs/wrds_clean_manifest.json` on every run and are
not copied by hand into this document.

The document contains summary statistics only. The raw file and the cleaned files contain
row-level licensed WRDS data and are not committed to the repository.

---

## 0. Summary

| Item                  | Value                                                              |
|-----------------------|--------------------------------------------------------------------|
| Source                | WRDS Compustat Global, `exchg = 194` (London Stock Exchange)       |
| Period                | 2014-01-01 to 2024-12-31                                           |
| Input file            | 11,782,633 rows; 6,457 securities; 5,525 companies                 |
| Analysis segment (R1) | 4,406,728 rows; 2,477 securities; 2,427 companies                  |
| Trading calendar (R3) | 2,870 weekdays − 91 non-trading days = 2,779 trading days          |
| Rules                 | 4 foundations (F1–F4) and 14 rules (R1–R14)                        |
| Source SHA-256        | `63d1e8186032380c59bc7a2c67bc054d08dd190c08ad4874133c24768ec0c2f8` |
| Run record            | `docs/wrds_clean_manifest.json`, written by `prepare_wrds.py`      |

| Rule | Content                                                                            | Evidence                     |
|------|------------------------------------------------------------------------------------|------------------------------|
| F1   | Security key `sid = gvkey + "_" + iid`                                             | Audit report                 |
| F2   | Total-return index `tri = prccd / ajexdi * trfd`                                   | Audit report, `check_r10.py` |
| F3   | Source file fixed by SHA-256                                                       | Audit report                 |
| F4   | Output series: `close` is the cleaned level, `ret_adj` the observed one-day return | Construction, output checks  |
| R1   | Keep ordinary shares in GBP with a positive price                                  | Audit report, `check_r10.py` |
| R2   | Returns across a currency change are missing                                       | Audit report                 |
| R3   | Fixed trading calendar of 2,779 days                                               | Audit report                 |
| R4   | Stuck adjustments: price missing until the price next moves                        | Audit report                 |
| R5   | Suspect adjustment events: level corrected, daily return missing                   | Audit report, manual review  |
| R6   | Manual exception list                                                              | Audit report, manual review  |
| R7   | 10p price floor for eligibility (engine)                                           | Audit report                 |
| R8   | Other extreme returns above the floor are genuine                                  | Audit report                 |
| R9   | Tradability: valid price and volume; rule for the 2017 volume gap                  | Audit report                 |
| R10  | One line per company per day; switch-day returns missing                           | Audit report, `check_r10.py` |
| R11  | Exclude funds                                                                      | Audit report, manual review  |
| R12  | Keep UK and Crown Dependency incorporations                                        | Audit report                 |
| R13  | Settle exits at the last price (engine)                                            | Audit report                 |
| R14  | Returns across missing trading days are missing                                    | Audit report                 |

---

## 1. Data source

### 1.1 Download

| Item     | Value                                                                                         |
|----------|-----------------------------------------------------------------------------------------------|
| Provider | WRDS, Compustat Global                                                                        |
| Tables   | Security Daily (`g_secd`), joined on `gvkey` with Company (`g_company`) fields                |
| Filter   | `exchg = 194`                                                                                 |
| Period   | 2014-01-01 to 2024-12-31 (`datadate`)                                                         |
| Coverage | All issue types, all currencies, active and inactive securities (no survivorship filter)      |
| File     | One merged CSV, gzip-compressed, kept locally as `data/wrds_uk_prices.csv.gz` (not committed) |

### 1.2 Fields

| Field      | Table     | Meaning                        | Used by                              |
|------------|-----------|--------------------------------|--------------------------------------|
| `gvkey`    | g_secd    | Company key                    | F1                                   |
| `iid`      | g_secd    | Issue ID within company        | F1                                   |
| `datadate` | g_secd    | Date                           | All rules                            |
| `conm`     | g_secd    | Company name                   | Manual review; company table         |
| `prccd`    | g_secd    | Close price                    | F2, R1, `raw_close`, execution price |
| `prcod`    | g_secd    | Open price                     | Not used (not audited)               |
| `ajexdi`   | g_secd    | Cumulative adjustment factor   | F2, R4, R5                           |
| `trfd`     | g_secd    | Cumulative total-return factor | F2, R4                               |
| `cshtrd`   | g_secd    | Trading volume (shares)        | R3, R9, `dollar_volume`              |
| `cshoc`    | g_secd    | Shares outstanding             | R10, `market_cap`                    |
| `curcdd`   | g_secd    | Currency code                  | R1, R2                               |
| `tpci`     | g_secd    | Issue type code                | R1                                   |
| `exchg`    | g_secd    | Exchange code                  | Download filter                      |
| `secstat`  | g_secd    | Security status                | Inspection only                      |
| `prcstd`   | g_secd    | Price status code              | Not used                             |
| `prirow`   | g_company | Primary issue ID               | R10                                  |
| `sic`      | g_company | SIC code                       | R11, company table                   |
| `gsubind`  | g_company | GICS sub-industry              | Inspection only                      |
| `fic`      | g_company | Country of incorporation       | R12, company table                   |
| `dldte`    | g_company | Date the company was deleted   | R13, company table                   |
| `dlrsn`    | g_company | Reason for deletion            | R13, company table                   |

### 1.3 Boundaries

- Only London listings (`exchg = 194`) are in the file. Lines of the same company on other
  exchanges are not available.
- There is no data before 2014-01-01, so signals that need 252 trading days of history
  start in 2015.
- `g_company` fields (`prirow`, `sic`, `gsubind`, `fic`, `dldte`, `dlrsn`) are current
  snapshots, not historical values. None of them takes more than one value within a
  security or a company.

---

## 2. Evidence base

| Source         | Description                                                                                                                                                                                   |
|----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Audit report   | `data_test.py` → `data_audit_report.txt`, generated 2026-10-10 16:23 UTC; Python 3.12.14, pandas 3.0.2, NumPy 2.4.4; reads every input row; records the SHA-256 of the input file             |
| `check_r10.py` | Read-only check of R10 cases 5 and 6a, line switches and factor differences between lines; run 2026-10-10 on the same file                                                                    |
| Manual review  | The cases named in R5, R6 and R11, checked by hand against the raw rows                                                                                                                       |
| Run record     | `prepare_wrds.py` → `docs/wrds_clean_manifest.json`: rows changed by each step, review lines, parameters, software versions, SHA-256 of the input and of every output; rewritten on every run |

The audit numbers in Sections 0–5 come from the audit report and `check_r10.py` and
describe the raw file or the R1 segment. The run record gives the rows each step changes
in the cleaned sample. The two differ where an earlier step removes or changes rows first:
for example, the audit report has 56 R5 candidates and the run 47, because R4 runs before
R5 (R5, Scale). Both numbers are correct for their stage.

---

## 3. Engine conventions assumed by the rules

| Convention      | Value                                                                                             |
|-----------------|---------------------------------------------------------------------------------------------------|
| Execution price | `prccd` (close), traded at t+1 after the signal date                                              |
| Rebalance       | Month-end                                                                                         |
| Missing values  | Never filled; a missing price or return stays missing                                             |
| Look-ahead      | None; every decision at t uses data up to t                                                       |
| Holdout         | Starts 2022-01-01 (`HOLDOUT_START`)                                                               |
| Factor windows  | Momentum 252/21, reversal 21, low volatility 60 trading days                                      |
| Calendar        | Panels are indexed by the 2,779 trading days; a company-day without a row is missing              |
| Returns         | `close` over the previous trading day's `close`, without filling (`pct_change(fill_method=None)`) |
| Price floor     | Tested on `raw_close`, not on the total-return level `close`                                      |

---

## 4. Foundations

### F1 Security key

**Rule.** A security line is identified by `sid = gvkey + "_" + iid`, with `gvkey` as a
6-character string.

**Assumption.**

- A-F1.1: `(sid, datadate)` identifies exactly one row.

**Why the assumption holds.**

- The audit report finds 0 rows with a missing key part, 0 duplicate `(sid, datadate)`
  keys, and 0 `gvkey` values shorter than 6 characters.

### F2 Total-return index

**Rule.** `tri = prccd / ajexdi * trfd`, valid only when `prccd`, `ajexdi` and `trfd` are
all positive. The within-line return is `ret_adj = tri / prev_tri − 1`, where `prev_tri`
is the previous observation of the same line, and `ret_raw = prccd / prev_prccd − 1` is
the raw price change. These are the returns the rules work on. The `ret_adj` in the output
is the cleaned, observed one-day return defined in F4.

**Assumptions.**

- A-F2.1: `ajexdi` is a cumulative factor that removes splits and other capital changes.
- A-F2.2: `trfd` is a cumulative factor that reinvests dividends.

**Why the assumptions hold.**

- Both are the documented definitions of these Compustat fields.
- The identity `(1 + ret_adj) = (1 + ret_raw) × aj_ratio × (1 + trfd_step)`, with
  `aj_ratio = prev_ajexdi / ajexdi`, has 0 mismatches on 11,775,046 comparable rows
  (largest residual 1.8e-12). This identity follows from the definition of `tri`, so it
  confirms only that the calculation is consistent. It does not prove that the factors
  are correct.
- On dividend days the factors behave as defined. Example from the audit report:
  `001932_01W` on 2014-03-12, raw return −3.49%, `trfd` step +3.03%, adjusted return
  −0.57%. `check_r10.py` shows BHP `03W` recording every ex-dividend date and the South32
  demerger (R10).
- The full file has 1,648 `ajexdi` changes and 44,539 `trfd` changes. The cases where a
  factor is wrong are handled by R4 and R5.
- Requiring each factor to be positive, not only their ratio, keeps two wrong-signed
  factors from producing a valid-looking index. The run record reports the rows that fail
  the test.

### F3 Source integrity

**Rule.** `prepare_wrds.py` computes the SHA-256 of the input file and raises an error if
it differs from `63d1e8186032380c59bc7a2c67bc054d08dd190c08ad4874133c24768ec0c2f8`.

**Assumption.**

- A-F3.1: A file with the same hash has the same content, so every number in this document
  applies to it.

**Why the assumption holds.**

- SHA-256 collisions are not a practical concern.
- The converse does not hold: the gzip header contains a timestamp, so a re-download or
  recompression of identical data produces a different hash. In that case the audit must
  be run again and this document updated before the new hash is accepted.

### F4 Output series

**Rule.** After R10 each company has one row per observed trading day. Two series are
built from it.

- `close` is a total-return level, `tri × c`, where `c` is constant within a company
  except on two kinds of day. On a day changed by R5, `c` changes so that the level moves
  by the cleaned return instead of the index move. On an R10 switch day, `c` puts the new
  line on the old line's last level. On every other day, including across missing returns
  (R2, R4, R6, R14), the level follows `tri`. Where the price is missing (R4, R6), `close`
  is missing.
- `ret_adj` is the observed one-day return: the within-line return of the chosen line when
  the previous row of the company is on the previous trading day and R5 did not change the
  return. It is missing on R2, R5 and R10 switch days, after a missing price (R4, R6), and
  across missing trading days (R14).
- `close` is also hidden on a day whose `ret_adj` is missing when the previous trading day
  has a level, so that no ratio of consecutive `close` values gives a removed return.

The output check requires that wherever two consecutive trading days both have `close`,
`close_t / close_{t−1} − 1 = ret_adj_t` within 1e-9.

**Assumptions.**

- A-F4.1: Signals measured over a window (momentum, reversal) need a level whose ratio
  over the window equals the cleaned cumulative return, including the corrections made by
  R5.
- A-F4.2: Daily statistics (volatility) and daily labels need observed one-day returns
  only. A move that was corrected, or that spans several trading days, must not appear as
  one day's return.

**Why the assumptions hold.**

- A-F4.1: Chaining the cleaned returns is the only way to carry an R5 correction into
  every later level; `tri × c` is the same chain written without a loop.
- A-F4.2: R5 replaces a return by 0 or by a two-day return. Neither is the return of that
  day, which is unknown, so the day's return is missing while the level keeps the
  correction. The same holds for a switch day (A10.5) and for a return across a gap (R14).
- How each event enters the output:

| Event                    | Level                                                             | `close` on the day     | `ret_adj`                                             |
|--------------------------|-------------------------------------------------------------------|------------------------|-------------------------------------------------------|
| R2 currency change       | Follows `tri`                                                     | Hidden                 | Missing                                               |
| R4 stuck price           | Missing during the run; follows `tri` across it                   | Missing during the run | Missing during the run and on the day the price moves |
| R5 unpaired candidate    | Flat on the day (move treated as 0)                               | Hidden                 | Missing                                               |
| R5 pair                  | Flat on the earlier day; the later day carries the two-day return | Hidden                 | Missing on both days                                  |
| R6 bad print             | Missing on the day; follows `tri` across it                       | Missing                | Missing on the day and the next day                   |
| R10 line switch          | Continuous: the new line starts at the old line's level           | Hidden                 | Missing                                               |
| R14 missing trading days | Follows `tri` across the gap                                      | Present                | Missing                                               |

- "Hidden" applies where the previous trading day has a level (rule above). The level
  itself continues, so `close` on later days includes the move.
- One level series cannot have a missing return on one day and a valid return on the next
  unless the first day's `close` is hidden; the valid `ret_adj` of the following day then
  cannot be computed from `close`. The run record reports how many such returns there are
  ("Engine sees ..."). They are the only difference between the returns the engine
  computes and `ret_adj`.
- Use: window signals and multi-day labels from `close`, which includes every correction;
  daily return statistics from `ret_adj`, or from `close` on consecutive trading days (the
  same values where both exist); the price floor from `raw_close`. A multi-day label
  compounded from `ret_adj` is missing whenever its window contains one of the events
  above.

---

## 5. Rules

### R1 Analysis segment

**Rule.** Keep rows with `tpci = '0'`, `curcdd = 'GBP'` and `prccd > 0`.

**Assumptions.**

- A1.1: `tpci = '0'` identifies ordinary shares.
- A1.2: GBP lines are the London prices of ordinary shares; lines in other currencies are
  not part of the UK equity universe.
- A1.3: `prccd` is in pounds, not pence.
- A1.4: Rows without a valid price carry no usable information.

**Why the assumptions hold.**

- A1.1: In Compustat, `tpci = '0'` is the issue type for ordinary (common) shares. The
  file holds 3,985 such securities; the other codes (`%` 1,667; `7` 396; `F` 288; `1` 117;
  `4` 3; `8` 1) are other issue types.
- A1.2: Without FX rates in the download, prices in different currencies cannot be
  combined. The file holds 21 currencies; GBP covers 6,515,433 rows in 3,725 securities.
- A1.3: In `check_r10.py`, BHP plc (`013312_03W`) has a median price of 16.131 and
  2,112,071,796 shares, a market value of about £34bn. In pence the value would be about
  £0.34bn, which is impossible for a FTSE 100 company.
- A1.4: 1,011 rows have a missing price; there are no zero or negative prices. The same
  1,011 rows also have a missing `ajexdi`, so no total-return index can be formed for them.

**Result.** 4,406,728 rows, 2,477 securities, 2,427 companies. The three weekend dates in
the file (2018-06-03, 2020-10-11, 2021-05-30) contain no segment rows.

### R2 Currency change

**Rule.** A return between two observations in different currencies is missing. The mask
is computed on the unfiltered data, before R1.

**Assumption.**

- A2.1: A change of `curcdd` makes the two prices incomparable.

**Why the assumption holds.**

- Without FX rates, a price ratio across currencies mixes the stock return with an
  exchange-rate move.
- In the full file, 1,130 observations have a previous observation in a different
  currency.
- The mask must be computed before R1: if a line goes GBP → USD → GBP, removing the USD
  rows first would make the two GBP observations adjacent, and the return across the USD
  period would look valid.

### R3 Trading calendar

**Rule.** Trading days are all weekdays from 2014-01-01 to 2024-12-31 minus a fixed list of
91 non-trading days (Appendix A), giving 2,779 trading days. Rows on non-trading days are
removed. The list is hard-coded; the code checks that it contains exactly 91 unique
weekdays inside the sample.

**Assumptions.**

- A3.1: The London market was closed on the 91 listed dates.
- A3.2: Rows on those dates carry the previous price forward and contain no trading.
- A3.3: The market was open on every other weekday.

**Why the assumptions hold.**

- A3.1: On all 91 dates fewer than 1% of segment securities have positive volume; on 90 of
  them more than 65% of prices are unchanged. Across all 2,870 weekdays the median share
  with positive volume is 84.66% and the median share of unchanged prices is 38.13%.
- A3.1: A data-driven candidate set (positive volume < 1% or unchanged prices > 65%)
  matches the 91 reference dates exactly: 0 dates only in the reference list, 0 dates
  only in the candidate set.
- A3.1: The list contains every English bank holiday and the one-off closures:
  2020-05-08 (VE Day), 2022-06-02 and 2022-06-03 (Jubilee), 2022-09-19 (State Funeral),
  2023-05-08 (Coronation).
- A3.2: Follows from the near-zero volume and the high share of unchanged prices above.
- A3.3: All 2,779 expected trading days have segment rows (0 missing days), and no
  candidate trading day falls outside the expected trading days.
- The list is fixed rather than recomputed from the data so that the calendar does not
  change if the data are re-downloaded.

**Result.** 139,470 segment rows fall on non-trading days and are removed.

### R4 Stuck adjustment

**Rule.** If the adjustment factor `trfd / ajexdi` moves by more than 20% while the raw
price is unchanged, the price is set to missing from that day until the raw price next
changes. R4 is applied before R5.

**Assumption.**

- A4.1: A large factor change with no price change means the price has not yet been
  updated for the corporate action. The adjusted return on that day, and on the day the
  price finally moves, is an artefact.

**Why the assumption holds.**

- A real split or capital change moves the price on the ex-date; a factor change of more
  than 20% with no price reaction is implausible for a traded security.
- The audit report finds 22 R4 candidates in 22 securities, 11 of them with a previous
  price of at least 10p. In 9 the move comes from `ajexdi`, in 13 from `trfd`:
  - `ajexdi`: for example `275132_01W` on 2023-11-23, `ajexdi` 10 → 1 with the price
    unchanged at 0.00065, adjusted return +900%;
  - `trfd`: for example `328127_01W` on 2023-04-25, `trfd` 33.21 → 70.81 with the price
    unchanged at 1.855, adjusted return +113.2%.
- Across the 22 candidates the false adjusted returns range from −99% to +900%.
- Setting the price to missing removes both artefact returns (into and out of the stale
  period) without inventing a value.
- R4 runs first because 8 of the 22 candidates are also R5 candidates (gvkeys 256842,
  271379, 275132, 284978, 298085, 298097, 310792, 317432).

### R5 Suspect adjustment events

**Rule.** A candidate is a segment row with a valid return where `ajexdi` changes,
`|ret_adj| > 30%`, and `aj_ratio < 0.8` or `aj_ratio > 1.25`. The two events in R6 are
exempt.

- If the candidate and the neighbouring return of the same line (the previous one first,
  otherwise the next) give a two-day return within ±20%, the pair keeps its two-day
  return: the earlier day's return becomes 0 and the later day's return becomes the
  two-day return.
- Otherwise the candidate's return becomes 0.
- The changed returns are used only to build the level (F4). In the output, the daily
  return of every day changed by R5 is missing.
- The code stops for a manual review if a candidate would pair with an exempt return, or
  if two pairs share a day.
- Unpaired candidates that a return 2 to 10 rows away would offset are listed in the run
  record for manual review. They are never paired automatically.

**Assumptions.**

- A5.1: A large adjusted return on a day when the adjustment factor moves far from 1 comes
  from a wrong or mistimed factor, not from a real price move.
- A5.2: When the candidate and a neighbouring return offset each other, the factor was
  applied one day early or late. The two-day return is correct; its split between the two
  days is not.
- A5.3: For an unpaired candidate, a level move of 0 is closer to the truth than the
  misadjusted move.
- A5.4: A mismatch between factor and price that lasts more than one day is either a stuck
  price (R4) or appears in the manual review list.

**Why the assumptions hold.**

- A5.1: The 56 candidates in the audit report fall into clear patterns:

| Pattern                                                                | Candidates | Meaning                                                         |
|------------------------------------------------------------------------|-----------:|-----------------------------------------------------------------|
| `aj_ratio > 1.25`, raw price falls, adjusted return large and positive |         14 | The factor implies a larger capital change than the price shows |
| `aj_ratio < 0.8`, raw price rises, adjusted return large and negative  |         20 | The factor implies a larger consolidation than the price shows  |
| `aj_ratio < 0.8`, other combinations                                   |         10 | Factor and price move on different days or by different ratios  |
| Raw price unchanged                                                    |          8 | Stuck adjustment, handled by R4                                 |
| `aj_ratio > 1.25`, adjusted return negative                            |          3 | Includes the two R6 exemptions                                  |
| Other                                                                  |          1 | `aj_ratio` 3.98 with a raw move of +2.2%                        |

- A5.1: Example: Capita (`104907_01W`) on 2018-05-10, the ex-date of a rights issue.
  `ajexdi` moves from 0.2 to 0.0667 (`aj_ratio` 3.0), as for a 3-for-1 split, while the
  raw price falls 35.8%. The adjusted return is +92.6%. A rights issue at a discount
  lowers the price far less than a 3-for-1 split, so the factor overstates the capital
  change.
- A5.1: The `aj_ratio` band excludes small factor changes, where a large return is more
  likely to be a real price move.
- A5.2: An offset within ±20% over two days means the price level is roughly unchanged
  once both days are combined, and keeping the two-day return preserves the combined move
  exactly; zeroing only one leg would leave the other as a false jump. 3 of the 56
  candidates can be paired with the previous observation, 0 with the next. Example:
  Serinus (`107272_03W`) on 2022-05-17, `ajexdi` records a 10-to-1 consolidation
  (`aj_ratio` 0.1) while the price moves +2.4%; the previous day's return offsets it, so
  the price had already been consolidated one day earlier.
- A5.2: In one pair the candidate's previous observation is two trading days earlier.
  `313481_01W` has no row on 2014-07-08; on 2014-07-09 the price is 3.50 after a 1000-to-1
  consolidation. In pre-consolidation terms the price runs 0.0030 (07-04), 0.0075 (07-07),
  0.0035 (07-09) and 0.0030 (07-10), so 0.0075 is out of line with both sides. The pair
  keeps +16.7% from 07-04 to 07-09, consistent with the surrounding prices; treating the
  candidate alone would keep the +150% of 07-07 in the level. Because the daily returns of
  both days are missing (F4), the move across the missing day never appears as one day's
  return.
- A5.3: A wrong factor shifts the total-return index for every later date, so momentum and
  volatility would read it as a signal. Zeroing the move keeps the index level correct
  before and after the event. The error introduced is the true ex-date return, which for a
  rights issue or consolidation is usually small; the error from keeping the return is the
  full misadjustment (about +92.6% for Capita). The true return cannot be computed because
  the terms of the corporate action are not in the data, so the day's return is missing
  rather than 0 (F4).
- A5.4: Stuck prices are covered by R4 whatever their length (for example `298097_02W`, 33
  trading days). For other delays the run record lists every unpaired candidate that a
  return 2 to 10 rows away would offset. Both cases listed were reviewed by hand, and
  neither is a delayed adjustment:
  - `282379_01W` 2022-01-27: a stock trading at 0.35p to 0.59p with daily moves of 10% to
    50%. The offsetting return is an ordinary +50% two days earlier, and 2022-01-27 is the
    company's last row.
  - `314757_01W` 2016-03-21: incorporated in the Cayman Islands and excluded by R12; a 2p
    to 3p stock suspended from 2016-01-01 to 2016-03-21. The offsetting return is a −37.5%
    move in April.
- A5.4: A wider automatic window would pair such cases by chance, so the window is used
  only for review.

**Scale.** 56 raw candidates in 53 securities; 21 with a previous price of at least 10p; 8
overlap with R4; 3 pairable. After R4, 47 candidates in 45 securities remain: the 8 R4
events are gone, and so is `298097_02W` on 2019-08-27, the day the stuck price of an R4
event moves, whose return is missing after R4. The run record gives the returns changed in
the final sample.

### R6 Manual exceptions

**Rule.** A fixed list of `(sid or gvkey, date, action, reason)`:

| Item                                  | Action                     |
|---------------------------------------|----------------------------|
| STM Group `284812_02W` 2017-06-16     | Price set to missing       |
| H.C. Slingsby `204760_01W` 2017-03-27 | Price set to missing       |
| Countrywide `270250_02W` 2018-08-02   | Exempt from R5             |
| Trackwise `327786_01W` 2022-12-14     | Exempt from R5             |
| 20 fund securities (Appendix B)       | Excluded from the universe |

**Assumptions.**

- A6.1: The STM Group price on 2017-06-16 and the H.C. Slingsby price on 2017-03-27 are
  bad prints.
- A6.2: The Countrywide and Trackwise losses are real.
- A6.3: The 20 listed securities are fund structures.

**Why the assumptions hold.**

- A6.1: The audit report lists both among the extreme returns above the floor that
  reverse the next day (R8), and both have the same pattern: a one-day price far from the
  surrounding level on low volume, followed by a return to that level.
  - STM Group: the price goes 0.43 → 13.601 on 6,654 shares (+3,063%) and falls 96.9% the
    next day, a jump to about 32 times the surrounding level.
  - H.C. Slingsby: the price goes 0.425 → 0.20 on 7,227 shares (−52.9%) and returns to
    0.375 the next day (+87.5%), where it stays for the following week.
- A6.1: Setting each price to missing removes both false returns, into and out of the
  bad print, without inventing a value.
- A6.2: Both are R5 candidates with `aj_ratio > 1.25` and a large negative adjusted return:
  Countrywide `aj_ratio` 1.77, raw return −62.8%, adjusted return −34.0%; Trackwise
  `aj_ratio` 3.80, raw return −86.2%, adjusted return −47.4%. Manual review classified
  both as collapses of distressed companies combined with a recapitalisation. If the factor
  overstated the capital change, the adjusted return would be biased upward, so the true
  loss would be at least as large. Zeroing these returns would hide real losses.
- A6.3: Each listed security was reviewed by hand. They are venture capital trusts,
  zero-dividend preference shares, funds with "FUND" in the name, and closed-end
  investment companies classified as `sic` 6799.

### R7 Price floor

**Rule.** A security is not eligible at a rebalance date if its previous raw close
(`raw_close`) is below 10p. 20p is the robustness check. The engine applies the floor.

**Assumption.**

- A7.1: Returns of very low-priced stocks are dominated by tick size, illiquidity and bad
  prints, not by the effects the factors measure.

**Why the assumption holds.**

- Extreme returns (`|ret_adj| > 50%`) by previous close, segment rows with a valid return:

| Previous close | Rows      | Securities | Extreme | Per 10k | p99 of abs return |
|----------------|----------:|-----------:|--------:|--------:|------------------:|
| < 1p           |   327,589 |        540 |     927 |    28.3 |            28.00% |
| 1p – 5p        |   464,936 |        857 |     719 |    15.5 |            22.37% |
| 5p – 10p       |   261,655 |        873 |     284 |    10.9 |            18.31% |
| 10p – 20p      |   280,909 |        910 |     177 |     6.3 |            16.67% |
| 20p – 50p      |   482,133 |      1,089 |     189 |     3.9 |            13.94% |
| 50p – £1       |   544,703 |      1,123 |     108 |     2.0 |            10.73% |
| ≥ £1           | 2,042,322 |      1,514 |     138 |     0.7 |             8.16% |

- The rate of extreme returns falls steadily as the price rises: rows below 10p have 15 to
  40 times the rate of rows at £1 or more. Other data problems concentrate there too:
  35 of the 56 R5 candidates and 11 of the 22 R4 candidates have a previous price below
  10p, and the Okyo Pharma problems found by `check_r10.py` (R10) occur at about 1p to 3p.
- There is no natural break, so the cut-off is a judgement. 10p removes the three
  highest-rate groups; the 20p robustness check tests whether results depend on it.

### R8 Extreme returns above the floor

**Rule.** Extreme returns at or above the price floor are kept as genuine, apart from the
R6 exceptions.

**Assumption.**

- A8.1: Bad prints above 10p are rare enough to be handled case by case.

**Why the assumption holds.**

- The audit report finds 612 extreme returns at or above 10p, in 421 securities. 13 of them
  fall on an `ajexdi` change and are handled by R5; 5 fall on a security's last segment
  observation and are covered by R13.
- Only 13 of the 612 reverse at the next observation (two-day return within ±20%). Of
  these, 11 are rises of +51.6% to +64.9% followed by falls of −22.4% to −36.7%, on
  volumes of 170,893 to 52,638,250 shares: partial reversals of genuine small-cap moves.
  A filter that removed reversals would mostly remove such moves, so none is used.
- The remaining 2 have the bad-print pattern, a one-day move that reverses on low volume:
  STM Group (`284812_02W`, 2017-06-16) and H.C. Slingsby (`204760_01W`, 2017-03-27). Both
  are in R6.
- Bad prints are therefore rare above 10p and are handled one by one in R6.

### R9 Tradability and the 2017 volume gap

**Rule.** A row is tradable if it has a valid price and `cshtrd > 0`. Inside `VOLUME_GAP =
2017-06-19 to 2017-10-13` (inclusive), a row with a valid price is also tradable if the
raw price changed from the previous trading day. A row without a valid price (R4, R6) is
never tradable.

**Assumptions.**

- A9.1: Outside the gap, missing volume means no trading.
- A9.2: Inside the gap, missing volume is a vendor coverage problem, not an absence of
  trading.
- A9.3: Inside the gap, a one-day price change shows that the security traded.
- A9.4: A row without a valid price cannot be traded at a known price.

**Why the assumptions hold.**

- A9.1: `cshtrd` is never zero on segment trading days, inside or outside the gap, so
  "no trade" can only be recorded as missing. Outside the gap, rows with missing volume
  but a changed price are only 0.94% of rows, so missing volume almost always comes with
  an unchanged price.
- A9.2: At a 65% threshold on the share of securities with positive volume, the
  low-coverage days form one contiguous run of 84 trading days, which is exactly every
  trading day from 2017-06-19 to 2017-10-13. The only non-trading day in the range is the
  bank holiday 2017-08-28. Missing volume is 49.85% inside the run against 15.35% outside.
  At 60% only 68 days are flagged, in 10 runs (longest 50 days, 2017-06-19 to
  2017-08-25), so coverage hovers around 60% throughout: the gap is fixed as a date range,
  not as a threshold.
- A9.3: Inside the gap, rows with missing volume and a changed price are 17.80%, against
  0.94% outside: many prices moved without recorded volume. A price change can also come
  from a corporate action, so it is only proxy evidence of trading.
- A9.3: The change must be a one-day change. A change measured across missing trading days
  does not show that trading happened on this day, so `ret_raw` follows the one-day test
  of R14.
- A9.4: R4 and R6 rows have no usable price, so a trade there could not be valued.
- The rule is conservative. Rows with positive volume are 50.15% in the gap against 84.65%
  outside, and rows with missing volume and an unchanged price are 32.03% against 14.41%;
  part of the excess probably traded but is still treated as not tradable.

**Impact.** The t+1 execution days of four month-end rebalances (June to September 2017)
fall in the gap. Robustness check: treat every row with a valid price in the gap as
tradable.

### R10 One line per company per day

**Rule.** Returns are computed within each line first. Then, for each company and day:

1. if exactly one line is observed, use it;
2. otherwise use the primary line (`iid = prirow`) if it is observed;
3. otherwise use the line with the largest valid market value (`prccd × cshoc` after R4
   and R6, both positive and the product finite);
4. if lines tie, use the smallest `iid`;
5. if the line chosen differs from the line chosen on the company's previous observed day,
   the company's return on that day is missing and the level continues from the old line
   (F4).

The code raises an error if a company-day has more than one primary line (case 3), a tie
when only some market values are valid (case 6b), or no valid market value (case 7).

**Assumptions.**

- A10.1: Each company should enter a portfolio once.
- A10.2: The primary line, where observed, is the main London line.
- A10.3: Without a primary line, the line with the largest market value is the main line.
- A10.4: Tied lines are economically equivalent.
- A10.5: On a day when the chosen line changes, the new line's within-line return is not a
  return of the company series, because its starting price was not selected the day before.

**Why the assumptions hold.**

- A10.1: Two lines of one company would be two bets on the same firm.
- A10.2: `prirow` is a current snapshot, so it is used only on days when that line is
  observed. In the segment, the primary line is observed for 2,248 of 2,427 companies and
  never for 179.
- A10.3 and A10.4: The cases are small. Company-days by case:

| Case | Description                                   | Company-days | Companies |
|------|-----------------------------------------------|-------------:|----------:|
| 1    | Single line                                   |    4,349,349 |     2,418 |
| 2    | Several lines, one primary                    |       23,859 |        31 |
| 3    | Several primary lines                         |            0 |         0 |
| 4    | No primary, all values valid, unique maximum  |          851 |         3 |
| 5    | No primary, all values valid, tie             |        1,029 |         1 |
| 6a   | No primary, some values valid, unique maximum |        2,108 |         1 |
| 6b   | No primary, some values valid, tie            |            0 |         0 |
| 7    | No primary, no valid value                    |            0 |         0 |

- Cases 4, 5 and 6a together cover 3,988 company-days (0.09% of the total). Even a wrong
  choice there has a negligible effect on the results.
- Case 6a, BHP (gvkey 013312), checked with `check_r10.py`. Line `03W` is chosen on all
  2,108 days. Its shares outstanding (2,112,071,796) match BHP plc before the 2022
  unification. Line `10W` has identical prices on all 2,108 days but no shares outstanding
  and, before 2019, no dividend factor (`trfd` = 1). `03W` records every ex-dividend date
  and the South32 demerger (2015-05-18), so the line chosen is also the one with complete
  factors. From 2022-01-31 only `10W` remains (BHP Group Ltd after the unification); its
  `trfd` changes on 2022-02-24, 2022-05-25, 2022-09-01, 2023-03-09, 2023-09-07,
  2024-03-07 and 2024-09-12, which covers every dividend, and the 12% step on 2022-05-25
  is consistent with the in-specie distribution of Woodside shares.
- Case 5, Okyo Pharma (gvkey 289153), checked with `check_r10.py`. On all 1,029 tie days
  the two lines have identical prices and shares outstanding and 99.61% identical volume:
  the same security recorded twice. Choosing the smaller `iid` has no effect.
- A10.5: The chosen line changes on 52 company-days in 14 companies. 13 are one-off line
  changes (for example BHP 2022-01-31, TUI AG 2014-12-17, Ithaca Energy 2022-11-09). 39 are
  at Okyo Pharma between 2017-06-19 and 2018-03-23, where the two lines carry different
  quotes and alternate as the larger market value. On 2017-06-16 line `02W` prints 0.0100
  between 0.0325 and 0.0302; R10 chooses `01W` that day and `02W` on 2017-06-19, whose
  within-line return of +202.5% is measured from the unselected bad print. Setting
  switch-day returns to missing removes such returns; every remaining return is the ratio
  of two consecutive prices of the same chosen line. The cost is 52 returns.
- These counts are for the segment. R10 runs after R11 and R12 (Section 6), so fewer
  switches remain in the final sample; the run record gives the number.

### R11 Funds

**Rule.** Exclude `sic` 6722 and 6726, plus the 20 fund securities in R6.

**Assumption.**

- A11.1: Funds hold portfolios of other securities; their returns follow net asset value
  and do not belong in an equity factor universe.

**Why the assumption holds.**

- `sic` 6722 is open-end investment funds and 6726 is unit trusts and closed-end investment
  funds, so both codes identify fund structures by definition.
- `sic` 6798 is REITs, which are property companies, and 6799 (investors not elsewhere
  classified) mixes investment companies with private-equity managers, so these codes are
  kept; the fund structures among them are listed by hand in R6.
- Segment securities by `sic` code: 6722 19; 6726 135; 6798 73; 6799 114; missing 21.
- Names confirm the codes. 112 segment securities have fund-like names (VCT, FUND, ZDP,
  TRUST, INVESTMENT); 70 of them are in 6722/6726, 25 in 6798/6799 and 17 elsewhere. The 84
  securities in 6722/6726 without such names are also funds by their code.
- GICS cannot be used: `gsubind` is missing for 72 of the 112 fund-like names.
- The 42 fund-like names outside 6722/6726 were reviewed by hand; 18 of the 20 securities
  in R6 come from this list. Names alone are not reliable: the list also contains Jupiter
  Fund Management (an asset manager, kept), Secure Trust Bank and Daily Mail & General
  Trust.

### R12 Country of incorporation

**Rule.** Keep `fic` in {GBR, JEY, GGY, IMN}. Robustness check: no country filter.

**Assumption.**

- A12.1: Companies incorporated in the UK or the Crown Dependencies have London as their
  main market; for other companies the London line may be secondary.

**Why the assumption holds.**

- Segment securities by `fic`: GBR 1,922; JEY 100; GGY 92; IRL 55; VGB 50; AUS 49;
  CYM 48; IMN 39; BMU 38; 27 other codes with 13 or fewer each. The four kept codes cover
  2,153 of 2,477 securities.
- `prirow` cannot identify the main market. The primary line of 179 segment companies is
  never observed in the segment, and 64 of them are incorporated in the UK, where London
  is the obvious main market:

| Incorporation | Primary line not observed | Primary line observed | Total |
|---------------|--------------------------:|----------------------:|------:|
| GBR           |                        64 |                 1,820 | 1,884 |
| GGY           |                        10 |                    80 |    90 |
| IMN           |                         4 |                    35 |    39 |
| JEY           |                         5 |                    92 |    97 |
| Other         |                        96 |                   221 |   317 |
| Total         |                       179 |                 2,248 | 2,427 |

- `fic` is present for every security and company in the file and never takes more than
  one value within a company.
- Jersey, Guernsey and the Isle of Man are common holding-company domiciles for
  London-listed firms.
- In the run, R12 removes fewer securities than the 324 outside the four codes, because
  some of them are funds already removed by R11 and R6.
- The filter is a judgement, so the robustness check removes it.

### R13 Delisting

**Rule.** A security that leaves the sample is settled at its last price. Robustness
check: an extra −30% return for exits with `dlrsn` other than 01 (acquisition or merger),
04 (reverse acquisition) and 09 (now private). The engine applies the rule;
`prepare_wrds.py` writes the exit data to `data/wrds_companies.csv` (Section 6.2).

**Assumptions.**

- A13.1: The last observed price is a reasonable exit value.
- A13.2: Exits for other reasons may include failures with losses after the last price.

**Why the assumptions hold.**

- Exits matter: 1,157 of 2,427 segment companies have their last price before 2024-12-31.
  Keeping them avoids survivorship bias. The run record gives the number for the final
  universe.
- A13.1: `dldte` relative to the last price date, for the 1,157 companies:

| `dldte`                 | Companies |
|-------------------------|----------:|
| Missing                 |        58 |
| Before the last price   |        18 |
| Same day                |        98 |
| 1–7 days after          |       868 |
| 8–31 days after         |        35 |
| More than 31 days after |        80 |

- 966 companies (83.5%) are deleted on the day of the last price or within 7 days, so the
  last price is close to the exit. The 80 long gaps suggest suspensions.
- A13.1: Acquisitions, reverse acquisitions and take-privates usually trade close to the
  offer price until the end, so the last price is close to the cash received.
- A13.2: Failures can lose further value after trading stops. Shumway (1997) finds an
  average delisting return of about −30% for performance-related delistings in US data;
  it is used only as a sensitivity check.
- A13.2: `dlrsn` of the 1,157 exits: 10 (other) 610; 01 (acquisition or merger) 388;
  missing 58; 09 (now private) 53; 04 (reverse acquisition) 25; 03 (liquidation) 20;
  02 (bankruptcy) 2; 07 1. The cash exits (01, 04, 09) are 466 companies; the other 691,
  mostly the opaque code 10, receive the −30% in the robustness check.
- 153 companies still trading on 2024-12-31 have a `dldte`, all after 2024-12-31, so they
  are not exits within the sample.
- 39 segment lines end while their company continues on another line; these are line
  changes handled by R10, not exits.

### R14 Long intervals and stale prices

**Rule.** A return is a one-day return only if the previous row of the same company is on
the previous trading day. Otherwise `ret_adj` is missing in the output, and the level
keeps the move across the gap (F4). `ret_raw`, which R9 uses, passes the same test at line
level. R14 is applied to `ret_adj` after R5, so that R5 still corrects a misadjusted
factor across a gap in the level.

The engine adds a second guard: its panels are indexed by all 2,779 trading days and
returns are computed without filling, so a return across a missing day is missing there as
well.

**Assumptions.**

- A14.1: Missing days inside a line's history are rare enough that losing the returns
  across them does not matter.
- A14.2: Runs of unchanged prices reflect real non-trading of illiquid stocks, not data
  errors.
- A14.3: A price observed after a gap is a valid price; only the day the move happened is
  unknown.

**Why the assumptions hold.**

- A14.1: Only 90 valid returns span more than one trading day. Valid returns by number
  of trading days since the previous observation:

| Trading days | Rows      | Median return |
|--------------|----------:|--------------:|
| 1            | 4,264,687 |         0.00% |
| 2–5          |        51 |         0.00% |
| 6–21         |        11 |         0.00% |
| 22–252       |        22 |       −15.72% |
| > 252        |         6 |       −14.42% |

- A14.2: Returns by number of consecutive unchanged prices before a price change:

| Unchanged prices | Rows      | Median return |
|------------------|----------:|--------------:|
| 0                | 2,210,116 |        −0.08% |
| 1–4              |   375,172 |        −0.52% |
| 5–20             |    67,071 |        −1.04% |
| 21–60            |     6,696 |        −1.56% |
| 61–250           |     1,189 |        −2.56% |
| > 250            |        84 |        −4.88% |

- Long runs are rare, and the median return after a run stays within −5%, which fits
  illiquid stocks that trade occasionally rather than prices that were never updated.
- A14.3: Keeping the move in the level leaves window signals correct across the gap;
  dropping it would understate every later level by the move.
- The engine must value positions held across a missing day; that is an engine rule, not
  a data rule. Stale prices lower measured volatility and so bias the low-volatility
  factor toward illiquid stocks (Section 8).

---

## 6. Implementation in `prepare_wrds.py`

### 6.1 Order of application

The steps run in this order, which is also the order of the step log in the run record.

| Step | Function                                                                | Rules                                          |
|-----:|-------------------------------------------------------------------------|------------------------------------------------|
|    1 | `check_source`                                                          | F3                                             |
|    2 | `load`                                                                  | F1                                             |
|    3 | `count_currency_breaks`                                                 | R2: changes counted on the unfiltered file     |
|    4 | `keep_segment`                                                          | R1                                             |
|    5 | `keep_trading_days`                                                     | R3                                             |
|    6 | `mark_currency_breaks`                                                  | R2: rows whose return crosses a change         |
|    7 | `fix_stuck_adjustments`                                                 | R4                                             |
|    8 | `remove_bad_prints`                                                     | R6: bad prints                                 |
|    9 | `line_returns`                                                          | F2; R2 applied; R14 for `ret_raw`              |
|   10 | `clean_adjustments`                                                     | R5; R6 exemptions                              |
|   11 | `select_universe`                                                       | R11; R6 fund list; R12                         |
|   12 | `select_lines`                                                          | R10                                            |
|   13 | `build_close`                                                           | F4; R14 for `ret_adj`                          |
|   14 | `add_trading_fields`                                                    | R9; `raw_close`, `dollar_volume`, `market_cap` |
|   15 | `write_output`, `write_company_table`, `write_events`, `write_manifest` | Output checks and files (6.2)                  |

- R3 runs before the price fixes, so every later rule sees trading days only. R2 is
  counted before R1 and R3, so that a change on a removed row is not lost.
- R11 and R12 remove whole securities before R10, so R10 chooses only among lines that
  stay in the universe. Returns are computed before these filters; removing whole
  securities does not cut any remaining return.
- R7 and R13 are applied by the engine at rebalance and exit. R8 changes no data.

### 6.2 Output files

| File                            | Content                                                                                                     | Committed |
|---------------------------------|-------------------------------------------------------------------------------------------------------------|-----------|
| `data/wrds_clean.csv.gz`        | One row per company and trading day (fields below)                                                          | No        |
| `data/wrds_companies.csv`       | One row per company: `conm`, `sic`, `fic`, `dlrsn`, `dldte`, first and last date                            | No        |
| `data/wrds_clean_events.csv`    | Every row-level change by R2, R4, R5, R6, R10 and R14: rule, `sid`, date, field, old and new value          | No        |
| `docs/wrds_clean_manifest.json` | Run record: step log, review lines, parameters, versions, SHA-256 of the input and of the three files above | Yes       |

Fields of `data/wrds_clean.csv.gz`:

| Field           | Unit        | Definition                                                                      |
|-----------------|-------------|---------------------------------------------------------------------------------|
| `date`          | —           | Trading day (R3)                                                                |
| `symbol`        | —           | `gvkey`, 6 digits                                                               |
| `close`         | Index level | Total-return level (F4); only ratios are meaningful                             |
| `raw_close`     | GBP         | `prccd` of the chosen line after R4 and R6                                      |
| `dollar_volume` | GBP         | `prccd × cshtrd`; the name follows the engine interface, the currency is GBP    |
| `is_tradable`   | Boolean     | R9                                                                              |
| `ret_adj`       | Return      | Observed one-day return (F4)                                                    |
| `market_cap`    | GBP         | `prccd × cshoc` of the chosen line, not the total over all lines of the company |

The engine reads the first six fields; `ret_adj` and `market_cap` are for other projects
that use the same data. Before writing, `prepare_wrds.py` checks one row per company and
day, 6-digit symbols, the full trading calendar, positive `close`, `raw_close` and
`market_cap` after conversion to float32, non-negative `dollar_volume`, boolean
`is_tradable`, no tradable row without a price, finite one-day `ret_adj` above −100%, and
the identity between `close` and `ret_adj` (F4). The same input gives byte-identical
files.

---

## 7. Robustness checks

| Rule | Baseline                                      | Alternative                                        |
|------|-----------------------------------------------|----------------------------------------------------|
| R5   | Corrections as in R5                          | No R5 (the original returns are in the event file) |
| R7   | 10p floor                                     | 20p floor                                          |
| R9   | Inside the gap: `cshtrd > 0` or price changed | Inside the gap: every row with a valid price       |
| R12  | GBR, JEY, GGY, IMN                            | No country filter                                  |
| R13  | Last price                                    | Extra −30% for exits other than 01, 04, 09         |

---

## 8. Limitations

- `prirow`, `sic`, `gsubind` and `fic` are current snapshots, not point-in-time values.
- Delisting information is available only at company level.
- `cshtrd` never records zero, so no-trade and no-data cannot be told apart; inside the
  2017 gap this is worse.
- R5 sets the level move of an unpaired candidate to 0 and keeps only the two-day move of
  a pair. The true returns of these days are unknown; they are missing in `ret_adj`, but
  the level depends on the assumption.
- Cleaning uses information from after the date. R5 changes a day's return using the
  neighbouring day (all three pairs in this file use the previous return, so day t−1 is
  changed using day t); R4 needs the day the price next moves; the lists in R6 come from
  ex-post review. The cleaned data describe what happened, not what was known on each day.
- Across an R4 gap the level follows `tri`. For `298097_02W` the factor moves on
  2019-07-11 and again on 2019-08-27, when the stuck price finally moves, and the level
  falls about 76% across the gap. If the two factor moves record the same consolidation
  twice, the fall is false; the data cannot tell.
- Mismatches between factor and price longer than one day are not corrected automatically;
  they are listed for manual review (R5).
- A valid `ret_adj` on the day after a hidden `close` cannot be computed from `close`
  (F4).
- `market_cap` is the value of the chosen line only.
- The 91 non-trading days were matched against the data and known holidays; they were not
  checked against an official exchange calendar.
- `prcod` was not audited and must not be used as an execution price without its own audit.
- The SHA-256 changes if the file is re-downloaded or recompressed, even when the content
  is the same.
- Stale prices bias the low-volatility factor.
- The completeness of `trfd` was not audited security by security. BHP `10W` shows that a
  line can carry prices without dividend factors (before 2019).
- R4 does not catch factor catch-ups below 20%. Okyo Pharma `01W` on 2018-01-12: `trfd`
  moves from 3.417 to 4.073 with the price unchanged, a false return of +19.2%. The price
  is about 1.25p, below the R7 floor.

---

## 9. Reproduction and data handling

- The audit script `data_test.py` and the R10 check script `check_r10.py` are not
  included in this repository. Their output contains row-level licensed data and is
  never committed.
- The raw file is kept locally as `data/wrds_uk_prices.csv.gz`; `data/` is listed in
  `.gitignore`. `prepare_wrds.py` refuses to run unless the file's SHA-256 matches the
  value in Section 0.
- `prepare_wrds.py` writes the three data files of Section 6.2 to `data/` and the run
  record to `docs/wrds_clean_manifest.json`. The run record contains counts, parameters
  and hashes only; it is committed and must not be edited by hand.
- The same input gives byte-identical outputs, so a rebuild can be checked against the
  SHA-256 values in the run record.
- Committed: this document, the run record and the SHA-256 of the input.

---

## Appendix A. Non-trading days (91)

| Year | Dates                                                                |
|-----:|----------------------------------------------------------------------|
| 2014 | 01-01, 04-18, 04-21, 05-05, 05-26, 08-25, 12-25, 12-26               |
| 2015 | 01-01, 04-03, 04-06, 05-04, 05-25, 08-31, 12-25, 12-28               |
| 2016 | 01-01, 03-25, 03-28, 05-02, 05-30, 08-29, 12-26, 12-27               |
| 2017 | 01-02, 04-14, 04-17, 05-01, 05-29, 08-28, 12-25, 12-26               |
| 2018 | 01-01, 03-30, 04-02, 05-07, 05-28, 08-27, 12-25, 12-26               |
| 2019 | 01-01, 04-19, 04-22, 05-06, 05-27, 08-26, 12-25, 12-26               |
| 2020 | 01-01, 04-10, 04-13, 05-08, 05-25, 08-31, 12-25, 12-28               |
| 2021 | 01-01, 04-02, 04-05, 05-03, 05-31, 08-30, 12-27, 12-28               |
| 2022 | 01-03, 04-15, 04-18, 05-02, 06-02, 06-03, 08-29, 09-19, 12-26, 12-27 |
| 2023 | 01-02, 04-07, 04-10, 05-01, 05-08, 05-29, 08-28, 12-25, 12-26        |
| 2024 | 01-01, 03-29, 04-01, 05-06, 05-27, 08-26, 12-25, 12-26               |

## Appendix B. Excluded fund securities (20)

| Type                                         | sid                                                                                |
|----------------------------------------------|------------------------------------------------------------------------------------|
| Venture capital trusts                       | 334189_01W, 338652_01W, 354688_01W, 360936_01W, 360955_01W                         |
| Zero-dividend preference shares              | 317049_01W, 318314_01W                                                             |
| "FUND" in the name                           | 275853_01W, 281799_01W, 282866_01W, 285008_01W, 297720_01W, 313845_01W             |
| Closed-end investment companies (`sic` 6799) | 201019_01W, 297187_01W, 298091_01W, 314166_01W, 325198_01W, 328536_01W, 328934_01W |
