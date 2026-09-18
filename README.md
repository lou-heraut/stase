# stase [<img src="https://raw.githubusercontent.com/lou-heraut/stase/main/docs/img/flower.png" align="right" width="160" height="160" alt="stase"/>](https://github.com/lou-heraut/card)

<!-- badges: start -->
[![tests](https://github.com/lou-heraut/stase/actions/workflows/tests.yml/badge.svg)](https://github.com/lou-heraut/stase/actions/workflows/tests.yml)
[![Lifecycle: maturing](https://img.shields.io/badge/lifecycle-maturing-blue)](https://lifecycle.r-lib.org/articles/stages.html)
![](https://img.shields.io/github/last-commit/lou-heraut/stase)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-bd0000)](https://github.com/lou-heraut/stase/blob/main/LICENSE)
<!-- badges: end -->

**STASE** (*STatistical Aggregation & Stationarity Evaluation*) aggregates
daily time series into annual, seasonal or monthly variables, then
analyses their stationarity with a generalized Mann-Kendall test and the
Sen slope. Stasis is the state of a series without trend: the null
hypothesis of the test. stase aggregates records and measures what
departs from it.

## Installation

```bash
pip install "stase @ git+https://github.com/lou-heraut/stase.git"
```

## Quick start

```python
import numpy as np
import pandas as pd
import stase

# a daily record: a datetime column, a text column (series identifier),
# one or more numeric columns. Here two synthetic series, one slowly
# decreasing, the other stable.
dates = pd.date_range("1970-01-01", "2020-12-31", freq="D")
rng = np.random.default_rng(0)
season = 1 + 0.6 * np.cos(2 * np.pi * (dates.dayofyear.to_numpy() - 30) / 365)

def series(name, factor):
    return pd.DataFrame({
        "date": dates, "id": name,
        "Q": (rng.gamma(2, 5, len(dates)) * season
              * np.linspace(1.0, factor, len(dates)))})

data = pd.concat([series("A", 0.75), series("B", 1.0)], ignore_index=True)

# annual mean over the hydrological year (starting on September 1st)
qa = stase.extract(data, func={"QA": (np.nanmean, "Q")},
                   time_step="year", sampling_period="09-01")
# id       date        QA
#  A 1969-09-01  9.548228
#  A 1970-09-01  9.257581
```

Columns are recognised by their **type**, never by their name: datetime
for dates, text for the series identifier, numeric for values. A date
column given as text in ISO `YYYY-MM-DD` format is converted
automatically. Numeric identifiers must be cast to text:
`data["code"].astype(str)`.

## Analysing stationarity

```python
tr = stase.trend(qa)
tr[["id", "variable", "h", "p", "a", "a_relative"]]
# id variable     h            p         a  a_relative
#  A       QA  True 2.767571e-16 -0.055412   -0.632233
#  B       QA False 8.189923e-01  0.001022    0.010210
```

One row per series and per variable. `h` tells whether the trend is
significant at the requested level, `a` is the Sen slope in the unit of
the variable per year, `a_relative` the same as a percentage of the mean.
Three assumptions about temporal dependence are available: `INDE`
(standard test), `AR1` (first-order autocorrelation correction) and `LTP`
(long-term persistence, Hurst coefficient). LTP breaks ties by random
draw: pass `seed=` for a replayable result.

## Chaining aggregations

The output of `stase.extract` feeds back in as input. QMNA, the annual
minimum of monthly mean discharges, is therefore written in two steps:

```python
qm = stase.extract(data, func={"QM": (np.nanmean, "Q")}, time_step="year-month")
qmna = stase.extract(qm, func={"QMNA": (np.nanmin, "QM")}, time_step="year")
# id       date     QMNA
#  A 1970-01-01 4.317909
#  A 1971-01-01 3.528193
```

## Adaptive sampling window

A fixed annual window sometimes cuts an event in two. `Adaptive` decides
it series by series, here by starting the year at the month of the
regime's maximum, which places the low-flow period in the middle of the
window:

```python
vcn = stase.extract(data, func={"VCN": (np.nanmin, "Q")}, time_step="year",
                    sampling_period=stase.Adaptive(np.nanmax, "Q"))
```

## Parameter columns

A column supplied by the caller, constant per series, which is neither
the time axis nor a measurement: a regulatory threshold, a period bound,
a catchment area. Declared in `param_cols`, it can be referenced by a
function, is excluded from gap counting, and is **kept in the output** so
that it survives a chain:

```python
def days_below(Q, threshold):
    return int(np.sum(np.asarray(Q, float) < float(np.asarray(threshold)[0])))

d = data.assign(threshold=np.where(data["id"] == "A", 3.0, 4.0))
n = stase.extract(d, func={"n_days": (days_below, "Q", {"threshold": "threshold"})},
                  time_step="year", param_cols=["threshold"])
# id       date  n_days  threshold
#  A 1970-01-01      66        3.0
#  A 1971-01-01      66        3.0
```

Each series gets its own value, and the threshold stays readable next to
the result it produced.

## What the engine can do

- `time_step`: year, year-month, month, year-season, season, yearday,
  none.
- `func` as tuples `(fn, *columns_or_literals, kwargs?, is_date?)`,
  several variables per call through a dict. A keyword argument whose
  value is a column name receives that column aligned on the group (e.g.
  `{"lim": "upLim"}`).
- `sampling_period`: fixed window (`"09-01"`) or partial
  (`["05-01", "11-30"]`), which then restricts the data to that
  sub-period, or adaptive per series.
- Dynamic outputs with `time_step="none"`: a scalar, an aligned column
  (rolling mean) or free rows (flow duration curve).
- Gap filters: `max_na_pct` (gap rate per sample, compared against the
  exact rate) and `max_na_years` (truncation of series with multi-year
  holes).
- Safe with gappy records: the time grid of each series is materialised
  (missing time steps inserted as NaN), and all series in a call must
  share the same time step (detected per series, explicit error
  otherwise).
- `param_cols`: parameter columns constant per series, kept in the
  output.
- `suffix`: one function applied to several variants of a column in a
  single call, resolved reference by reference (a shared series stays
  shared, only the varying column fans out).

When there is nothing to return (empty input, a `period` excluding all
the data), the output is a zero-row DataFrame with the expected columns:
filters and chains work without special handling of the empty case.

For ready-to-use hydroclimatic variables (low flows, floods,
seasonality...), the [card](https://github.com/lou-heraut/card) package
provides a collection of parameterization cards executed by stase.

## The ecosystem

| | |
|---|---|
| [card](https://github.com/lou-heraut/card) | the card collection, in Python |
| **stase** | the aggregation and trend engine (you are here) |
| [card4r](https://github.com/lou-heraut/card4r) | the same collection, called from R |
| [card-api](https://github.com/lou-heraut/card-api) | the web service, on Hub'Eau discharge data |
| [CARD-R](https://github.com/lou-heraut/CARD-R) · [EXstat](https://github.com/lou-heraut/EXstat) | the historical R packages, superseded |

## Citing

This engine is scientific software: please cite it if you use it in
published work.

```
Héraut L., Dorchies D., Sauquet É., Vidal J.-P. (2026). stase:
statistical aggregation and stationarity evaluation (version 0.6.5).
Software Heritage: swh:1:rev:<commit>
https://github.com/lou-heraut/stase
```

The repository is archived on [Software
Heritage](https://archive.softwareheritage.org/browse/origin/directory/?origin_url=https://github.com/lou-heraut/stase),
which gives a persistent identifier per revision. Machine-readable
metadata: `CITATION.cff` and `codemeta.json` at the root; GitHub offers
"Cite this repository" from the former.

If you are citing a result produced by the
[card-api](https://github.com/lou-heraut/card-api) service, every
response already carries the exact commit and SWHID of the code that
computed it, along with the version of each card used: take those rather
than this template.

## Origin

stase is the Python port of the R package
[EXstat](https://github.com/lou-heraut/EXstat) (INRAE, UR RiverLy),
validated number by number against R. The details of the validation and
the documented divergences are in
[docs/dev/ORIGINE_R.md](https://github.com/lou-heraut/stase/blob/main/docs/dev/ORIGINE_R.md). GPL-3 licence, authors in
the AUTHORS file.

## Development

```bash
pip install -e . && pytest      # full suite, goldens included in tests/data/
```

CI: `.github/workflows/tests.yml` (Python × pandas matrix, ruff).
Benchmark on real data: `benchmarks/bench_rrse.py`. What changed and
when: [CHANGELOG.md](https://github.com/lou-heraut/stase/blob/main/CHANGELOG.md).
