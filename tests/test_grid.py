"""Grille temporelle matérialisée : équivalence lignes absentes / NaN,
troncature max_na_years sur trous de lignes, stop sur résolutions
mixtes, réindexation des séries agrégées dans process_trend."""

import warnings

import numpy as np
import pandas as pd
import pytest

from stase import process_extraction, process_trend


def _daily(id_="S1", start="1980-01-01", end="2019-12-31", seed=0):
    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    q = 10 + rng.gamma(2.0, 2.0, len(dates))
    return pd.DataFrame({"id": id_, "date": dates, "Q": q})


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


# ── équivalence lignes absentes / valeurs NaN ────────────────────────────────

def test_row_gaps_equivalent_to_nan_gaps():
    full = _daily()
    hole = (full["date"] >= "1995-03-10") & (full["date"] <= "1995-07-20")
    gapped = full[~hole]
    nan_dense = full.copy()
    nan_dense.loc[hole, "Q"] = np.nan

    func = {"QA": (np.nanmean, "Q"), "tQJXA": (np.nanargmax, "Q", True)}
    kw = dict(func=func, time_step="year", sampling_period="09-01",
              max_na_pct=50, drop_na_pct=False)
    a = _quiet(process_extraction, gapped, **kw)
    b = _quiet(process_extraction, nan_dense, **kw)
    pd.testing.assert_frame_equal(a, b)


def test_extremum_date_correct_despite_row_gaps():
    one_year = _daily(start="2000-09-01", end="2001-08-31")
    imax = one_year.index[one_year["date"] == "2001-03-15"][0]
    one_year.loc[imax, "Q"] = 999.0
    drop = one_year[(one_year["date"] >= "2001-01-05")
                    & (one_year["date"] <= "2001-01-24")].index
    gapped = one_year.drop(drop)

    kw = dict(func={"t": (np.nanargmax, "Q", True)}, time_step="year",
              sampling_period="09-01")
    ref = _quiet(process_extraction, one_year, **kw)
    got = _quiet(process_extraction, gapped, **kw)
    assert got["t"].iloc[0] == ref["t"].iloc[0]


def test_max_na_years_sees_row_gaps():
    full = _daily()
    hole = (full["date"] >= "1995-01-01") & (full["date"] <= "1999-12-31")
    gapped = full[~hole]
    r = _quiet(process_extraction, gapped,
               func={"QA": (np.nanmean, "Q")}, time_step="year",
               sampling_period="09-01", max_na_pct=3, max_na_years=3,
               drop_na_pct=False)
    valid_years = r.loc[r["QA"].notna(), "date"].dt.year
    # la portion la plus courte (avant le trou) est masquée
    assert valid_years.min() >= 2000


def test_gap_warning_emitted():
    gapped = _daily(end="1984-12-31").iloc[:-400]
    gapped = pd.concat([gapped.iloc[:300], gapped.iloc[350:]],
                       ignore_index=True)
    with pytest.warns(UserWarning, match="pas de temps manquants"):
        process_extraction(gapped, func={"QA": (np.nanmean, "Q")},
                           time_step="year")


# ── résolutions ──────────────────────────────────────────────────────────────

def test_mixed_resolutions_raise():
    daily = _daily("D1", end="1989-12-31")
    monthly = pd.DataFrame({
        "id": "M1",
        "date": pd.date_range("1980-01-01", "1989-12-01", freq="MS"),
        "Q": 5.0,
    })
    data = pd.concat([daily, monthly], ignore_index=True)
    with pytest.raises(ValueError, match="pas de temps"):
        process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year")


def test_monthly_input_with_row_gaps():
    dates = pd.date_range("1980-01-01", "1989-12-01", freq="MS")
    data = pd.DataFrame({"id": "M1", "date": dates,
                         "Q": np.ones(len(dates))})
    gapped = data[data["date"].dt.year != 1985]      # 12 mois absents
    r = _quiet(process_extraction, gapped,
               func={"QA": (np.nanmean, "Q")}, time_step="year",
               drop_na_pct=False)
    assert len(r) == 10                              # 1985 présent (NaN)
    assert r.loc[r["date"].dt.year == 1985, "QA"].isna().all()
    assert r.loc[r["date"].dt.year == 1985, "na_pct"].iloc[0] == 100.0


# ── keep='all' : sortie sur la grille complète ───────────────────────────────

def test_keep_all_returns_dense_grid():
    full = _daily(end="1984-12-31")
    gapped = full[full.index % 7 != 3]               # ~14 % de lignes absentes
    r = _quiet(process_extraction, gapped,
               func={"QA": (np.nanmean, "Q")}, time_step="year",
               keep="all")
    assert len(r) == len(full)


# ── process_trend : grille des séries agrégées ───────────────────────────────

def _annual(values, years, id_="S1"):
    return pd.DataFrame({
        "id": id_,
        "date": pd.to_datetime([f"{y}-09-01" for y in years]),
        "X": values,
    })


def test_trend_sen_slope_exact_with_missing_years():
    years = np.arange(1980, 2020)
    ann = _annual(10 + 0.1 * (years - 1980), years)
    holed = ann[(ann["date"].dt.year < 1995) | (ann["date"].dt.year > 2004)]
    t = _quiet(process_trend, holed, level=0.1, dependency="INDE")
    assert t["a"].iloc[0] == pytest.approx(0.1, abs=1e-9)


def test_trend_off_grid_series_warn():
    years = list(range(1980, 2000))
    ann = _annual(np.linspace(0.0, 1.0, len(years)), years)
    ann.loc[10, "date"] = pd.Timestamp("1990-10-15")
    with pytest.warns(UserWarning, match="hors de leur grille"):
        t = process_trend(ann, dependency="INDE")
    assert len(t) == 1
