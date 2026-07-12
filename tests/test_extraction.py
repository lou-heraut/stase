"""Tests du moteur process_extraction."""

import numpy as np
import pandas as pd
import pytest

from stase import Adaptive, process_extraction
from stase.extraction import _SPARSE_ATTR


def daily(start="2000-01-01", end="2004-12-31", seed=1, ids=("S1",)):
    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    frames = []
    for i, sid in enumerate(ids):
        doy = dates.dayofyear.to_numpy()
        q = 10 + 5 * np.sin(2 * np.pi * (doy - 60 * i) / 365.25) \
            + rng.normal(0, 1, len(dates))
        frames.append(pd.DataFrame({"date": dates, "Q": q, "id": sid}))
    return pd.concat(frames, ignore_index=True)


# ── agrégations de base ─────────────────────────────────────────────────────

def test_year_aggregation_matches_manual():
    data = daily()
    r = process_extraction(data, funct={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period="01-01")
    manual = data[data.date.dt.year == 2001].Q.mean()
    got = r[r.Date == "2001-01-01"].QA.iloc[0]
    assert got == pytest.approx(manual)


def test_windowed_sampling_period():
    data = daily()
    r = process_extraction(data, funct={"QS": (np.nanmean, "Q")},
                           time_step="year",
                           sampling_period=["06-01", "08-31"])
    mask = (data.date >= "2001-06-01") & (data.date <= "2001-08-31")
    assert r[r.Date == "2001-06-01"].QS.iloc[0] == pytest.approx(
        data[mask].Q.mean())


def test_cross_year_window():
    data = daily()
    r = process_extraction(data, funct={"QW": (np.nanmean, "Q")},
                           time_step="year",
                           sampling_period=["11-01", "04-30"])
    mask = (data.date >= "2001-11-01") & (data.date <= "2002-04-30")
    assert r[r.Date == "2001-11-01"].QW.iloc[0] == pytest.approx(
        data[mask].Q.mean())


def test_napct_filters_gappy_year():
    data = daily()
    gap = (data.date >= "2002-03-01") & (data.date <= "2002-04-15")
    data.loc[gap, "Q"] = np.nan          # 46 jours ≈ 12.6 % > 3 %
    r = process_extraction(data, funct={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period="01-01",
                           NApct_lim=3)
    assert np.isnan(r[r.Date == "2002-01-01"].QA.iloc[0])
    assert not np.isnan(r[r.Date == "2001-01-01"].QA.iloc[0])


# ── sampling adaptatif ──────────────────────────────────────────────────────

def test_adaptive_starts_at_max_month():
    data = daily(ids=("S1", "S2"))     # phases décalées de 60 jours
    r = process_extraction(data, funct={"QNA": (np.nanmin, "Q")},
                           time_step="year",
                           sampling_period=Adaptive(np.nanmax, "Q"))
    starts = {sid: r[r.id == sid].Date.dt.strftime("%m-%d").iloc[0]
              for sid in ("S1", "S2")}
    # les deux stations n'ont pas le même mois de départ
    assert starts["S1"] != starts["S2"]
    assert all(s.endswith("-01") for s in starts.values())


# ── sorties dynamiques time_step 'none' ─────────────────────────────────────

def test_transform_full_length():
    data = daily()

    def roll5(x):
        return pd.Series(np.asarray(x, dtype=float)).rolling(
            5, center=True, min_periods=5).mean().to_numpy()

    r = process_extraction(data, funct={"VC5": (roll5, "Q")},
                           time_step="none", keep="all")
    assert len(r) == len(data)
    assert set(data.columns) <= set(r.columns)
    manual = roll5(data[data.id == "S1"].Q)[10]
    assert r.VC5.iloc[10] == pytest.approx(manual)


def test_ragged_output():
    data = daily()

    def q10(x):
        return np.quantile(np.asarray(x, dtype=float), np.linspace(0, 1, 10))

    r = process_extraction(
        data,
        funct={"p": (lambda x: np.linspace(0, 1, 10), "Q"),
               "Qc": (q10, "Q")},
        time_step="none",
    )
    assert len(r) == 10
    assert list(r.columns) == ["id", "p", "Qc"]
    assert r.Qc.is_monotonic_increasing


def test_scalar_broadcast_keep_all():
    data = daily()
    r = process_extraction(data, funct={"m": (np.nanmax, "Q")},
                           time_step="none", keep="all")
    assert len(r) == len(data)
    assert r.m.nunique() == 1


# ── littéraux, kwargs-colonnes, alias date ──────────────────────────────────

def test_positional_literal():
    data = daily()

    def scaled_mean(x, factor):
        return float(np.nanmean(np.asarray(x, dtype=float)) * factor)

    r = process_extraction(data, funct={"Q2": (scaled_mean, "Q", 2.0)},
                           time_step="year", sampling_period="01-01")
    base = process_extraction(data, funct={"Q1": (np.nanmean, "Q")},
                              time_step="year", sampling_period="01-01")
    assert r.Q2.iloc[1] == pytest.approx(2 * base.Q1.iloc[1])


def test_kwarg_column_reference():
    data = daily()
    data["lim"] = 10.0

    def n_above(x, lim=None):
        return float(np.sum(np.asarray(x) > np.asarray(lim)[0]))

    r = process_extraction(data, funct={"n": (n_above, "Q", {"lim": "lim"})},
                           time_step="year", sampling_period="01-01")
    manual = (data[data.date.dt.year == 2001].Q > 10).sum()
    assert r[r.Date == "2001-01-01"].n.iloc[0] == manual


def test_date_column_alias():
    data = daily()

    def last_ts(x, dates=None):
        return float(pd.Series(dates).dt.dayofyear.iloc[-1])

    # "date" en minuscule dans le tuple, colonne réelle "date" — puis test
    # de l'alias sur une colonne "Date" (sortie EXstat standard)
    r = process_extraction(data, funct={"t": (last_ts, "Q",
                                              {"dates": "date"})},
                           time_step="year", sampling_period="01-01")
    assert r.t.iloc[1] == 365.0 or r.t.iloc[1] == 366.0


# ── keep ────────────────────────────────────────────────────────────────────

def test_keep_list_selects_columns():
    data = daily()

    def roll5(x):
        return pd.Series(np.asarray(x, dtype=float)).rolling(
            5, center=True, min_periods=5).mean().to_numpy()

    r = process_extraction(data, funct={"VC5": (roll5, "Q")},
                           time_step="none", keep=["VC5"])
    assert list(r.columns) == ["id", "date", "VC5"]


# ── colonnes creuses (fan-out) ──────────────────────────────────────────────

def test_sparse_fanout_then_compact():
    data = daily()
    # P1 : moyenne mensuelle en fan-out → colonne creuse marquée
    p1 = process_extraction(data, funct={"QM": (np.nanmean, "Q")},
                            time_step="year-month", keep="all")
    assert p1.attrs.get(_SPARSE_ATTR) == ["QM"]
    assert p1.QM.isna().mean() > 0.9
    # P2 : agrégation annuelle sur la colonne creuse — sans compaction,
    # NApct serait ~97 % et tout serait filtré
    p2 = process_extraction(p1, funct={"QMNA": (np.nanmin, "QM")},
                            time_step="year", sampling_period="01-01",
                            NApct_lim=3)
    vals = p2[p2.Date == "2001-01-01"].QMNA
    assert not np.isnan(vals.iloc[0])


# ── NAyear_lim ──────────────────────────────────────────────────────────────

def test_nayear_lim_truncates():
    data = daily(end="2010-12-31")
    gap = (data.date >= "2003-01-01") & (data.date <= "2005-12-31")
    data.loc[gap, "Q"] = np.nan
    r = process_extraction(data, funct={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period="01-01",
                           NAyear_lim=2)
    # la portion la plus courte (avant la lacune de 3 ans) est masquée
    assert np.isnan(r[r.Date == "2001-01-01"].QA.iloc[0])
    assert not np.isnan(r[r.Date == "2008-01-01"].QA.iloc[0])
