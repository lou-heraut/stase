"""Tests du moteur process_extraction."""

import warnings
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
    r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period="01-01")
    manual = data[data.date.dt.year == 2001].Q.mean()
    got = r[r.date == "2001-01-01"].QA.iloc[0]
    assert got == pytest.approx(manual)


def test_windowed_sampling_period():
    data = daily()
    r = process_extraction(data, func={"QS": (np.nanmean, "Q")},
                           time_step="year",
                           sampling_period=["06-01", "08-31"])
    mask = (data.date >= "2001-06-01") & (data.date <= "2001-08-31")
    assert r[r.date == "2001-06-01"].QS.iloc[0] == pytest.approx(
        data[mask].Q.mean())


def test_cross_year_window():
    data = daily()
    r = process_extraction(data, func={"QW": (np.nanmean, "Q")},
                           time_step="year",
                           sampling_period=["11-01", "04-30"])
    mask = (data.date >= "2001-11-01") & (data.date <= "2002-04-30")
    assert r[r.date == "2001-11-01"].QW.iloc[0] == pytest.approx(
        data[mask].Q.mean())


def test_napct_filters_gappy_year():
    data = daily()
    gap = (data.date >= "2002-03-01") & (data.date <= "2002-04-15")
    data.loc[gap, "Q"] = np.nan          # 46 jours ≈ 12.6 % > 3 %
    r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period="01-01",
                           max_na_pct=3)
    assert np.isnan(r[r.date == "2002-01-01"].QA.iloc[0])
    assert not np.isnan(r[r.date == "2001-01-01"].QA.iloc[0])


# ── sampling adaptatif ──────────────────────────────────────────────────────

def test_adaptive_starts_at_max_month():
    data = daily(ids=("S1", "S2"))     # phases décalées de 60 jours
    r = process_extraction(data, func={"QNA": (np.nanmin, "Q")},
                           time_step="year",
                           sampling_period=Adaptive(np.nanmax, "Q"))
    starts = {sid: r[r.id == sid].date.dt.strftime("%m-%d").iloc[0]
              for sid in ("S1", "S2")}
    # les deux séries n'ont pas le même mois de départ
    assert starts["S1"] != starts["S2"]
    assert all(s.endswith("-01") for s in starts.values())


# ── sorties dynamiques time_step 'none' ─────────────────────────────────────

def test_transform_full_length():
    data = daily()

    def roll5(x):
        return pd.Series(np.asarray(x, dtype=float)).rolling(
            5, center=True, min_periods=5).mean().to_numpy()

    r = process_extraction(data, func={"VC5": (roll5, "Q")},
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
        func={"p": (lambda x: np.linspace(0, 1, 10), "Q"),
               "Qc": (q10, "Q")},
        time_step="none",
    )
    assert len(r) == 10
    assert list(r.columns) == ["id", "p", "Qc"]
    assert r.Qc.is_monotonic_increasing


def test_scalar_broadcast_keep_all():
    data = daily()
    r = process_extraction(data, func={"m": (np.nanmax, "Q")},
                           time_step="none", keep="all")
    assert len(r) == len(data)
    assert r.m.nunique() == 1


# ── littéraux, kwargs-colonnes, alias date ──────────────────────────────────

def test_positional_literal():
    data = daily()

    def scaled_mean(x, factor):
        return float(np.nanmean(np.asarray(x, dtype=float)) * factor)

    r = process_extraction(data, func={"Q2": (scaled_mean, "Q", 2.0)},
                           time_step="year", sampling_period="01-01")
    base = process_extraction(data, func={"Q1": (np.nanmean, "Q")},
                              time_step="year", sampling_period="01-01")
    assert r.Q2.iloc[1] == pytest.approx(2 * base.Q1.iloc[1])


def test_kwarg_column_reference():
    data = daily()
    data["lim"] = 10.0

    def n_above(x, lim=None):
        return float(np.sum(np.asarray(x) > np.asarray(lim)[0]))

    r = process_extraction(data, func={"n": (n_above, "Q", {"lim": "lim"})},
                           time_step="year", sampling_period="01-01")
    manual = (data[data.date.dt.year == 2001].Q > 10).sum()
    assert r[r.date == "2001-01-01"].n.iloc[0] == manual


def test_date_column_alias():
    data = daily()

    def last_ts(x, dates=None):
        return float(pd.Series(dates).dt.dayofyear.iloc[-1])

    # "date" en minuscule dans le tuple, colonne réelle "date" — puis test
    # de l'alias sur une colonne "Date" (sortie EXstat standard)
    r = process_extraction(data, func={"t": (last_ts, "Q",
                                              {"dates": "date"})},
                           time_step="year", sampling_period="01-01")
    assert r.t.iloc[1] == 365.0 or r.t.iloc[1] == 366.0


# ── keep ────────────────────────────────────────────────────────────────────

def test_keep_list_selects_columns():
    data = daily()

    def roll5(x):
        return pd.Series(np.asarray(x, dtype=float)).rolling(
            5, center=True, min_periods=5).mean().to_numpy()

    r = process_extraction(data, func={"VC5": (roll5, "Q")},
                           time_step="none", keep=["VC5"])
    assert list(r.columns) == ["id", "date", "VC5"]


# ── colonnes creuses (fan-out) ──────────────────────────────────────────────

def test_sparse_fanout_then_compact():
    data = daily()
    # P1 : moyenne mensuelle en fan-out → colonne creuse marquée
    p1 = process_extraction(data, func={"QM": (np.nanmean, "Q")},
                            time_step="year-month", keep="all")
    assert p1.attrs.get(_SPARSE_ATTR) == ["QM"]
    assert p1.QM.isna().mean() > 0.9
    # P2 : agrégation annuelle sur la colonne creuse — sans compaction,
    # NApct serait ~97 % et tout serait filtré
    p2 = process_extraction(p1, func={"QMNA": (np.nanmin, "QM")},
                            time_step="year", sampling_period="01-01",
                            max_na_pct=3)
    vals = p2[p2.date == "2001-01-01"].QMNA
    assert not np.isnan(vals.iloc[0])


# ── séries fantômes : filtre period × catégories ────────────────────────────

@pytest.mark.parametrize("time_step", ["year", "year-month", "month",
                                       "year-season", "season", "yearday",
                                       "none"])
def test_no_ghost_series_after_period_filter(time_step):
    # S2 s'arrête fin 2001 ; period ne garde que 2003+ → S2 ne doit pas
    # apparaître dans la sortie (même pas en NaN), quel que soit time_step
    data = daily(ids=("S1", "S2"))
    data = data[(data.id == "S1") | (data.date < "2002-01-01")]
    r = process_extraction(data, func={"X": (np.nanmean, "Q")},
                           time_step=time_step,
                           period=["2003-01-01", "2004-12-31"])
    assert set(r[r.columns[0]].unique()) == {"S1"}


# ── retours vides typés ─────────────────────────────────────────────────────

@pytest.mark.parametrize("time_step,struct", [
    ("year", ["date"]), ("month", ["date", "month"]),
    ("season", ["date", "season"]), ("none", []),
])
def test_period_excluding_all_returns_typed_empty(time_step, struct):
    data = daily()
    with pytest.warns(UserWarning, match="Aucune donnée dans la période"):
        r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                               time_step=time_step,
                               period=["2050-01-01", "2060-12-31"])
    assert len(r) == 0
    assert list(r.columns) == ["id"] + struct + ["QA"]
    # les accès aval fonctionnent sur le vide
    assert len(r[r.QA > 0]) == 0
    if "Date" in r.columns:
        assert len(r[r.date >= "2055-01-01"]) == 0


def test_empty_input_returns_typed_empty():
    data = daily().iloc[0:0]
    r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year")
    assert len(r) == 0
    assert list(r.columns) == ["id", "date", "QA"]


def test_empty_extraction_chains_into_trend():
    from stase import process_trend
    data = daily()
    with pytest.warns(UserWarning):
        qa = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                                time_step="year",
                                period=["2050-01-01", "2060-12-31"])
        t = process_trend(qa)
    assert len(t) == 0
    assert "H" in t.columns


# ── argmax positionnel Cython : équivalence avec np.nanargmax générique ─────

@pytest.mark.parametrize("skipna", [False, True])
def test_positional_agg_matches_generic_nanargmax(skipna):
    # NaN épars, ex-æquo, années entièrement NaN, fenêtre hydrologique
    data = daily(ids=("S1", "S2"), end="2006-12-31")
    rng = np.random.default_rng(7)
    data.loc[rng.random(len(data)) < 0.15, "Q"] = np.nan
    data.loc[(data.id == "S2") & (data.date.dt.year == 2003), "Q"] = np.nan
    data.loc[data.date.dt.month == 6, "Q"] = 42.0        # ex-æquo massifs

    kw = {"skipna": True} if skipna else {}
    fast = process_extraction(
        data, func={"t": (np.nanargmax, "Q", kw)},
        time_step="year", sampling_period="09-01")
    generic = process_extraction(
        data, func={"t": (lambda x: np.nanargmax(x), "Q", kw)},
        time_step="year", sampling_period="09-01")
    pd.testing.assert_frame_equal(fast, generic)


def test_positional_agg_is_date_pipeline():
    data = daily(ids=("S1",))
    fast = process_extraction(data, func={"tQJXA": (np.nanargmax, "Q", True)},
                              time_step="year", sampling_period="09-01")
    generic = process_extraction(
        data, func={"tQJXA": (lambda x: np.nanargmax(x), "Q", True)},
        time_step="year", sampling_period="09-01")
    pd.testing.assert_frame_equal(fast, generic)
    assert fast.tQJXA.dtype == "Int64"


# ── conversion automatique des dates ISO ────────────────────────────────────

def test_iso_string_dates_auto_converted():
    data = daily()
    data["date"] = data["date"].dt.strftime("%Y-%m-%d")   # dates en texte
    with pytest.warns(UserWarning, match="convertie automatiquement"):
        r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                               time_step="year", sampling_period="01-01")
    ref = process_extraction(daily(), func={"QA": (np.nanmean, "Q")},
                             time_step="year", sampling_period="01-01")
    pd.testing.assert_frame_equal(r, ref)


def test_ambiguous_string_dates_still_raise():
    data = daily()
    data["date"] = data["date"].dt.strftime("%d/%m/%Y")   # format ambigu
    with pytest.raises(ValueError, match="datetime"):
        process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year")


def test_existing_datetime_column_untouched():
    data = daily()
    data["label"] = data["date"].dt.strftime("%Y-%m-%d")  # texte ISO en plus
    r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period="01-01")
    assert len(r) > 0    # la datetime existante est utilisée, pas de conflit


# ── validations d'entrée ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["9-1x", "13-01", "09-32", "0901", 901])
def test_invalid_sampling_period_raises(bad):
    data = daily()
    with pytest.raises(ValueError, match="sampling_period invalide"):
        process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period=bad)


def test_adaptive_fallback_warns():
    data = daily(ids=("S1", "S2"))
    data.loc[data.id == "S2", "Q"] = np.nan     # S2 toute-NaN → repli
    with pytest.warns(UserWarning, match="repli sur le mois par défaut"):
        r = process_extraction(data, func={"QNA": (np.nanmin, "Q")},
                               time_step="year",
                               sampling_period=Adaptive(np.nanmax, "Q"))
    assert set(r.id.unique()) == {"S1", "S2"}


# ── NAyear_lim ──────────────────────────────────────────────────────────────

def test_nayear_lim_truncates():
    data = daily(end="2010-12-31")
    gap = (data.date >= "2003-01-01") & (data.date <= "2005-12-31")
    data.loc[gap, "Q"] = np.nan
    r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           time_step="year", sampling_period="01-01",
                           max_na_years=2)
    # la portion la plus courte (avant la lacune de 3 ans) est masquée
    assert np.isnan(r[r.date == "2001-01-01"].QA.iloc[0])
    assert not np.isnan(r[r.date == "2008-01-01"].QA.iloc[0])


# ── alias d'agrégation Cython : jamais un autre résultat ─────────────────────

def test_agg_aliases_never_change_the_value():
    """Chaque alias doit donner exactement la valeur de la fonction
    passée par le chemin générique (sans alias). Ici avec des NaN et
    un groupe entièrement NaN."""
    from stase.extraction import _PANDAS_AGG_ALIASES

    dates = pd.date_range("2000-01-01", "2002-12-31", freq="D")
    rng = np.random.default_rng(5)
    q = rng.gamma(2.0, 5.0, len(dates))
    q[10:80] = np.nan
    q[dates.year == 2001] = np.nan              # année tout-NaN
    data = pd.DataFrame({"id": "S1", "date": dates, "Q": q})

    for fn in _PANDAS_AGG_ALIASES:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            via_alias = process_extraction(
                data, func={"X": (fn, "Q")}, time_step="year")
            generic = process_extraction(
                data, func={"X": (lambda s, _f=fn: _f(s), "Q")},
                time_step="year")
        pd.testing.assert_frame_equal(via_alias, generic,
                                      obj=f"alias {fn}")


def test_nanstd_keeps_numpy_ddof():
    """np.nanstd est ddof=0 ; l'alias pandas 'std' (ddof=1) le
    trahirait, il ne doit plus être dans la table."""
    dates = pd.date_range("2000-01-01", "2000-12-31", freq="D")
    q = np.arange(len(dates), dtype=float)
    data = pd.DataFrame({"id": "S1", "date": dates, "Q": q})
    r = process_extraction(data, func={"S": (np.nanstd, "Q")},
                           time_step="year")
    assert r["S"].iloc[0] == pytest.approx(np.nanstd(q))


def test_ambiguous_nan_functions_warn():
    dates = pd.date_range("2000-01-01", "2001-12-31", freq="D")
    data = pd.DataFrame({"id": "S1", "date": dates,
                         "Q": np.ones(len(dates))})
    with pytest.warns(UserWarning, match="nanmean"):
        process_extraction(data, func={"X": (np.mean, "Q")},
                           time_step="year")
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # nan* : aucun warning
        process_extraction(data, func={"X": (np.nanmean, "Q")},
                           time_step="year")
