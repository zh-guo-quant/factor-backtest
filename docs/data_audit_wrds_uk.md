# Data audit: WRDS Compustat Global, UK listings

This document records the cleaning rules adopted for the WRDS UK data, the assumptions
behind each rule, and the evidence that supports each assumption. The rules are
implemented in `prepare_wrds.py`. The evidence comes from the audit script `data_test.py`
and the R10 check script `check_r10.py` (Section 2).

The document contains summary statistics only. The raw file and the script outputs contain
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
| Rules                 | 3 foundations (F1–F3) and 14 rules (R1–R14)                        |
| Source SHA-256        | `63d1e8186032380c59bc7a2c67bc054d08dd190c08ad4874133c24768ec0c2f8` |

| Rule | Content                                                       | Evidence                     |
|------|---------------------------------------------------------------|------------------------------|
| F1   | Security key `sid = gvkey + "_" + iid`                        | Audit report                 |
| F2   | Total-return index `tri = prccd / ajexdi * trfd`              | Audit report, `check_r10.py` |
| F3   | Source file fixed by SHA-256                                  | Audit report                 |
| R1   | Keep ordinary shares in GBP with a positive price             | Audit report, `check_r10.py` |
| R2   | Returns across a currency change are missing                  | Audit report                 |
| R3   | Fixed trading calendar of 2,779 days                          | Audit report                 |
| R4   | Stuck adjustments: price missing until the price next moves   | Audit report                 |
| R5   | Returns on suspect adjustment events are set to zero          | Audit report                 |
| R6   | Manual exception list                                         | Audit report, manual review  |
| R7   | 10p price floor for eligibility                               | Audit report                 |
| R8   | Other extreme returns above the floor are genuine             | Audit report                 |
| R9   | Tradability rule, with a special rule for the 2017 volume gap | Audit report                 |
| R10  | One line per company per day; switch-day returns missing      | Audit report, `check_r10.py` |
| R11  | Exclude funds                                                 | Audit report, manual review  |
| R12  | Keep UK and Crown Dependency incorporations                   | Audit report                 |
| R13  | Settle exits at the last price                                | Audit report                 |
| R14  | No separate rule for long intervals; no filling               | Audit report                 |

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

| Field      | Table     | Meaning                        | Used by                 |
|------------|-----------|--------------------------------|-------------------------|
| `gvkey`    | g_secd    | Company key                    | F1                      |
| `iid`      | g_secd    | Issue ID within company        | F1                      |
| `datadate` | g_secd    | Date                           | All rules               |
| `conm`     | g_secd    | Company name                   | Manual review only      |
| `prccd`    | g_secd    | Close price                    | F2, R1, execution price |
| `prcod`    | g_secd    | Open price                     | Not used (not audited)  |
| `ajexdi`   | g_secd    | Cumulative adjustment factor   | F2, R4, R5              |
| `trfd`     | g_secd    | Cumulative total-return factor | F2, R4                  |
| `cshtrd`   | g_secd    | Trading volume (shares)        | R3, R9                  |
| `cshoc`    | g_secd    | Shares outstanding             | R10                     |
| `curcdd`   | g_secd    | Currency code                  | R1, R2                  |
| `tpci`     | g_secd    | Issue type code                | R1                      |
| `exchg`    | g_secd    | Exchange code                  | Download filter         |
| `secstat`  | g_secd    | Security status                | Inspection only         |
| `prcstd`   | g_secd    | Price status code              | Not used                |
| `prirow`   | g_company | Primary issue ID               | R10                     |
| `sic`      | g_company | SIC code                       | R11                     |
| `gsubind`  | g_company | GICS sub-industry              | Inspection only         |
| `fic`      | g_company | Country of incorporation       | R12                     |
| `dldte`    | g_company | Date the company was deleted   | R13                     |
| `dlrsn`    | g_company | Reason for deletion            | R13                     |

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

| Source         | Description                                                                                                                                                                       |
|----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Audit report   | `data_test.py` → `data_audit_report.txt`, generated 2026-10-10 16:23 UTC; Python 3.12.14, pandas 3.0.2, NumPy 2.4.4; reads every input row; records the SHA-256 of the input file |
| `check_r10.py` | Read-only check of R10 cases 5 and 6a, line switches and factor differences between lines; run 2026-10-10 on the same file                                                        |

Every number in this document comes from these two outputs. `prepare_wrds.py` prints the
number of rows each rule actually changes.

---

## 3. Engine conventions assumed by the rules

| Convention      | Value                                                        |
|-----------------|--------------------------------------------------------------|
| Execution price | `prccd` (close), traded at t+1 after the signal date         |
| Rebalance       | Month-end                                                    |
| Missing values  | Never filled; a missing price or return stays missing        |
| Look-ahead      | None; every decision at t uses data up to t                  |
| Holdout         | Starts 2022-01-01 (`HOLDOUT_START`)                          |
| Factor windows  | Momentum 252/21, reversal 21, low volatility 60 trading days |

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

**Rule.** `tri = prccd / ajexdi * trfd`. The adjusted return is
`ret_adj = tri / prev_tri − 1`, where `prev_tri` is the previous observation of the same
line.

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
`|ret_adj| > 30%`, and `aj_ratio < 0.8` or `aj_ratio > 1.25`. If the candidate and an
adjacent observation of the same line together give a combined return within ±20%, both
returns are set to 0. Otherwise only the candidate's return is set to 0. The total-return
index is then rebuilt from the cleaned returns. The two events in R6 are exempt.

**Assumptions.**

- A5.1: A large adjusted return on a day when the adjustment factor moves far from 1 comes
  from a wrong or mistimed factor, not from a real price move.
- A5.2: When the candidate and an adjacent return offset each other, the factor was applied
  one day early or late, and both returns are artefacts.
- A5.3: Setting the return to 0 is closer to the true return than keeping it.

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
- A5.2: An offset within ±20% over two days means the price level is essentially
  unchanged once both days are combined. Zeroing only one leg would leave the other as a
  false jump. 3 of the 56 candidates can be paired with the previous observation, 0 with
  the next. Example: Serinus (`107272_03W`) on 2022-05-17, `ajexdi` records a 10-to-1
  consolidation (`aj_ratio` 0.1) while the price moves +2.4%; the previous day's return
  offsets it, so the price had already been consolidated one day earlier.
- A5.3: A wrong factor shifts the total-return index for every later date, so momentum and
  volatility would read it as a signal. Zeroing the return keeps the index level correct
  before and after the event. The error introduced is the true ex-date return, which for a
  rights issue or consolidation is usually small; the error from keeping the return is
  the full misadjustment (about +92.6% for Capita). The true return cannot be computed
  because the terms of the corporate action are not in the data.

**Scale.** 56 raw candidates in 53 securities; 21 with a previous price of at least 10p;
8 overlap with R4; 3 pairable. The final number of changed returns is printed by
`prepare_wrds.py`.

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

**Rule.** A security is not eligible at a rebalance date if its previous close is below
10p. 20p is the robustness check.

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

**Rule.** A security is tradable on a day if `cshtrd > 0`. Inside
`VOLUME_GAP = 2017-06-19 to 2017-10-13` (inclusive), it is tradable if `cshtrd > 0` or
the close changed from the previous trading day.

**Assumptions.**

- A9.1: Outside the gap, missing volume means no trading.
- A9.2: Inside the gap, missing volume is a vendor coverage problem, not an absence of
  trading.
- A9.3: Inside the gap, a price change shows that the security traded.

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
3. otherwise use the line with the largest valid market value
   (`prccd × cshoc`, both positive and the product finite);
4. if lines tie, use the smallest `iid`;
5. if the line chosen differs from the line chosen on the company's previous observed day,
   the company's return on that day is missing.

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
- The filter is a judgement, so the robustness check removes it.

### R13 Delisting

**Rule.** A security that leaves the sample is settled at its last price. Robustness
check: an extra −30% return for exits with `dlrsn` other than 01 (acquisition or merger),
04 (reverse acquisition) and 09 (now private).

**Assumptions.**

- A13.1: The last observed price is a reasonable exit value.
- A13.2: Exits for other reasons may include failures with losses after the last price.

**Why the assumptions hold.**

- Exits matter: 1,157 of 2,427 segment companies have their last price before
  2024-12-31. Keeping them avoids survivorship bias.
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

**Rule.** No separate rule. After R3, each line is reindexed onto the 2,779-day calendar
without filling, so a return across a missing day is missing.

**Assumptions.**

- A14.1: Missing days inside a line's history are rare enough that losing the returns
  across them does not matter.
- A14.2: Runs of unchanged prices reflect real non-trading of illiquid stocks, not data
  errors.

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
- The engine must value positions held across a missing day; that is an engine rule, not
  a data rule. Stale prices lower measured volatility and so bias the low-volatility
  factor toward illiquid stocks (Section 8).

---

## 6. Order of application in `prepare_wrds.py`

1. F3: check the SHA-256.
2. R2: compute the currency-change mask on the unfiltered data.
3. R1: analysis segment.
4. Price-level fixes: R4, then R6 (bad-print prices).
5. Compute returns within each line (F2).
6. R2: apply the currency mask.
7. R5 (with the R6 exemptions).
8. Rebuild the total-return index from the cleaned returns.
9. R10–R12 and R6 fund exclusions: universe; switch-day returns missing (R10).
10. R3 and R14: reindex onto the calendar without filling.
11. R9: tradability flags.

R7 and R13 are applied by the engine at rebalance and exit. `prepare_wrds.py` prints the
number of rows affected by each rule.

---

## 7. Robustness checks

| Rule | Baseline                                      | Alternative                                  |
|------|-----------------------------------------------|----------------------------------------------|
| R7   | 10p floor                                     | 20p floor                                    |
| R9   | Inside the gap: `cshtrd > 0` or price changed | Inside the gap: every row with a valid price |
| R12  | GBR, JEY, GGY, IMN                            | No country filter                            |
| R13  | Last price                                    | Extra −30% for exits other than 01, 04, 09   |

---

## 8. Limitations

- `prirow`, `sic`, `gsubind` and `fic` are current snapshots, not point-in-time values.
- Delisting information is available only at company level.
- `cshtrd` never records zero, so no-trade and no-data cannot be told apart; inside the
  2017 gap this is worse.
- R5 approximates the true ex-date return as 0.
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
- Only this document and the SHA-256 are committed.

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
