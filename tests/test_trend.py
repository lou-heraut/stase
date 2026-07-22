"""Tests de process_trend : goldens R + cas limites.

Goldens : tests/data/ref_trend/pt_sc*.csv, générés par le package R EXstat
(compare_process_trend.R d'EXstat_Claude), 16 séries × 2 variables,
1990-2019. Tolérance 1e-10 (INDE/AR1 concordent exactement avec R).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stase import process_trend

REF = Path(__file__).parent / "data" / "ref_trend"

# les CSVs de référence R gardent les noms historiques : on les traduit
# vers les noms de sortie Python avant comparaison
_REF_RENAMES = {"variable_en": "variable",
                "a_normalise": "a_relative",
                "a_normalise_min": "a_relative_min",
                "a_normalise_max": "a_relative_max",
                "mean_period_trend": "mean_period",
                "period_trend_start": "period_start",
                "period_trend_end": "period_end"}
NUM_BASE = ["p", "a", "b", "mean_period", "a_relative",
            "a_relative_min", "a_relative_max"]
DATE_BASE = ["period_start", "period_end"]


@pytest.fixture(scope="module")
def raw():
    df = pd.read_csv(REF / "process_trend_input.csv")
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def assert_matches_ref(py, ref_name, numeric_cols, date_cols=(), atol=1e-10,
                       renames=None):
    """renames : surcharge de la table de traduction, pour les cas où une
    colonne R correspond à une AUTRE colonne Python que par défaut (une
    sortie R polymorphe est désormais scindée en absolu et relatif)."""
    ref = pd.read_csv(REF / f"{ref_name}.csv").rename(
        columns={**_REF_RENAMES, **(renames or {})})
    key = ["ID", "variable"]
    py = py.sort_values(key).reset_index(drop=True)
    ref = ref.sort_values(key).reset_index(drop=True)
    assert len(py) == len(ref), f"longueurs py={len(py)} R={len(ref)}"

    for g, e in zip(py["H"], ref["H"]):
        assert bool(g) == bool(e)

    for col in numeric_cols:
        got = pd.Series(py[col]).astype(float).to_numpy()
        exp = pd.Series(ref[col]).astype(float).to_numpy()
        assert np.array_equal(np.isnan(got), np.isnan(exp)), f"NA divergents ({col})"
        ok = ~np.isnan(exp)
        np.testing.assert_allclose(got[ok], exp[ok], atol=atol, rtol=0,
                                   err_msg=f"colonne {col}")

    for col in date_cols:
        got = pd.to_datetime(py[col]).dt.date.tolist()
        exp = pd.to_datetime(ref[col]).dt.date.tolist()
        assert got == exp, f"colonne {col}"


# ── Goldens R ────────────────────────────────────────────────────────────────

def test_sc1_inde_normalise(raw):
    py = process_trend(raw, level=0.1, dependency="INDE",
                       relative=True, verbose=False)
    assert_matches_ref(py, "pt_sc1_inde_norm", NUM_BASE, DATE_BASE)


def test_sc2_ar1_no_normalise(raw):
    """relative=False : divergence assumée avec R (cf. ORIGINE_R.md).

    R recopiait la pente absolue dans a_normalise, si bien qu'une même
    colonne portait des unités différentes selon la variable. Ici
    a_relative vaut NaN et l'absolu vit dans a / a_min / a_max, qui
    reprennent exactement les valeurs de référence R.
    """
    py = process_trend(raw, level=0.1, dependency="AR1",
                       relative=False, verbose=False)
    assert_matches_ref(py, "pt_sc2_ar1_nonorm", ["p", "a", "b"], DATE_BASE)
    assert_matches_ref(py, "pt_sc2_ar1_nonorm", ["a_min", "a_max"],
                       renames={"a_normalise_min": "a_min",
                                "a_normalise_max": "a_max"})
    assert py["a_relative"].isna().all()
    assert py["a_relative_min"].isna().all()
    # mean_period est désormais toujours calculée, R la laissait vide ici
    assert py["mean_period"].notna().all()


def test_sc3_inde_period_trend(raw):
    py = process_trend(raw, level=0.1, dependency="INDE",
                       relative=True,
                       period=["1995-01-01", "2010-12-31"],
                       verbose=False)
    assert_matches_ref(py, "pt_sc3_inde_period", NUM_BASE, DATE_BASE)


def test_sc4_inde_period_change(raw):
    py = process_trend(raw, level=0.1, dependency="INDE",
                       relative=True,
                       period_change=[["1990-01-01", "2004-12-31"],
                                      ["2005-01-01", "2019-12-31"]],
                       verbose=False)
    # Le 'change' de R est un pourcentage ici (relative=True) : c'est
    # notre change_relative. Notre 'change' porte l'écart absolu, que R
    # ne produisait pas.
    assert_matches_ref(
        py, "pt_sc4_inde_change",
        NUM_BASE + ["change_relative", "change_relative_min",
                    "change_relative_max",
                    "mean_period_change_1", "mean_period_change_2"],
        DATE_BASE + ["period_change_start_1", "period_change_end_1",
                     "period_change_start_2", "period_change_end_2"],
        renames={"change": "change_relative",
                 "change_min": "change_relative_min",
                 "change_max": "change_relative_max"},
    )
    absolute = py["mean_period_change_2"] - py["mean_period_change_1"]
    assert py["change"].to_numpy() == pytest.approx(absolute.to_numpy())


def test_sc5_extreme_no_signif(raw):
    py = process_trend(raw, level=0.1, dependency="INDE",
                       relative=True,
                       extremes_include_non_significant=False,
                       verbose=False)
    assert_matches_ref(py, "pt_sc5_extreme_nosignif", NUM_BASE)


# ── Cas limites ──────────────────────────────────────────────────────────────

def _yearly(slope=0.5, n=30, ids=("S1",), seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for sid in ids:
        dates = pd.date_range("1990-01-01", periods=n, freq="YS")
        x = 50 + slope * np.arange(n) + rng.normal(0, 0.5, n)
        frames.append(pd.DataFrame({"ID": sid, "Date": dates, "X": x}))
    return pd.concat(frames, ignore_index=True)


def test_single_series_slope_recovered():
    t = process_trend(_yearly(slope=0.5), verbose=False)
    assert len(t) == 1
    assert bool(t.H.iloc[0]) is True
    # pente de Sen par pas de temps (annuel ici) ≈ pente injectée
    assert t.a.iloc[0] == pytest.approx(0.5, rel=0.15)


def test_series_with_too_few_values_gives_na():
    data = pd.concat([
        _yearly(n=30, ids=("LONG",)),
        _yearly(n=2, ids=("COURT",)),
    ], ignore_index=True)
    t = process_trend(data, verbose=False).set_index("ID")
    assert bool(t.loc["LONG", "H"]) is True
    assert pd.isna(t.loc["COURT", "H"])
    assert pd.isna(t.loc["COURT", "p"])


def test_h_is_nullable_boolean():
    data = pd.concat([
        _yearly(n=30, ids=("LONG",)),
        _yearly(n=2, ids=("COURT",)),
    ], ignore_index=True)
    t = process_trend(data, verbose=False)
    assert t.H.dtype == "boolean"
    # le filtrage booléen fonctionne malgré le NA
    assert set(t[t.H == True].ID) == {"LONG"}          # noqa: E712


def test_multiple_id_columns_with_underscore_roundtrip():
    # les identifiants contenant '_' doivent ressortir intacts
    data = _yearly(n=30, ids=("S_1", "S_2"))
    data["model"] = "M_a"
    t = process_trend(data, verbose=False)
    assert set(t.ID) == {"S_1", "S_2"}
    assert set(t.model) == {"M_a"}
    assert list(t.columns[:2]) == ["ID", "model"]


def test_ltp_seed_reproducible_end_to_end():
    # données arrondies → ex-æquo ; seed fixe → process_trend rejouable
    data = _yearly(slope=0.2, n=35)
    data["X"] = data["X"].round(0)
    with pytest.warns(UserWarning, match="ex-æquo"):
        t_noseed = process_trend(data, dependency="LTP",
                                 verbose=False)
    assert len(t_noseed) == 1
    t1 = process_trend(data, dependency="LTP", seed=7,
                       verbose=False)
    t2 = process_trend(data, dependency="LTP", seed=7,
                       verbose=False)
    pd.testing.assert_frame_equal(t1, t2)


def test_ltp_long_series_warns():
    # 210 valeurs valides > seuil 200 → warning (le calcul aboutit quand
    # même : mémoire bornée par blocs, ~2 s)
    dates = pd.date_range("1990-01-01", periods=210, freq="D")
    rng = np.random.default_rng(0)
    data = pd.DataFrame({"ID": "S1", "Date": dates,
                         "X": rng.normal(10, 1, 210)})
    with pytest.warns(UserWarning, match="O\\(n⁴\\)"):
        t = process_trend(data, dependency="LTP",
                          seed=1, verbose=False)
    assert np.isfinite(t.p.iloc[0])


def test_period_trend_outside_data_returns_typed_empty():
    with pytest.warns(UserWarning):
        t = process_trend(_yearly(), period=["2050-01-01", "2060-12-31"],
                          verbose=False)
    assert len(t) == 0
    # colonnes standard présentes : les accès aval fonctionnent
    for c in ("ID", "variable", "H", "p", "a", "b",
              "period_start", "a_relative_min"):
        assert c in t.columns
    assert t.H.dtype == "boolean"
    assert len(t[t.H == True]) == 0                      # noqa: E712


def test_empty_input_returns_typed_empty():
    with pytest.warns(UserWarning):
        t = process_trend(pd.DataFrame({"ID": [], "Date": [], "X": []})
                          .astype({"Date": "datetime64[ns]"}))
    assert len(t) == 0
    assert "ID" in t.columns and "H" in t.columns


# ── Suffixes : nom de base, mise en commun des bornes, relative ──────────────

def _suffixed(cols, n=30, ids=("S1", "S2", "S3"), seed=1):
    """Une colonne par nom de variable demandé, même forme temporelle."""
    rng = np.random.default_rng(seed)
    frames = []
    for sid in ids:
        dates = pd.date_range("1990-01-01", periods=n, freq="YS")
        d = {"ID": sid, "Date": dates}
        for i, c in enumerate(cols):
            d[c] = 50 + (0.3 + 0.2 * i) * np.arange(n) + rng.normal(0, 0.5, n)
        frames.append(pd.DataFrame(d))
    return pd.concat(frames, ignore_index=True)


def test_suffix_is_stripped_only_at_the_end():
    """Un suffixe 'sim' ne doit pas amputer une variable 'QA_simple'."""
    t = process_trend(_suffixed(["QA_sim", "QA_simple"]),
                      suffix=["sim"], verbose=False)
    got = dict(zip(t["variable"], t["variable_no_suffix"]))
    assert got["QA_sim"] == "QA"
    assert got["QA_simple"] == "QA_simple"


def test_pool_suffixes_shares_the_extreme_bounds():
    data = _suffixed(["QA_obs", "QA_sim"])
    apart = process_trend(data, suffix=["obs", "sim"], verbose=False)
    pooled = process_trend(data, suffix=["obs", "sim"],
                           extremes_pool_suffixes=True, verbose=False)

    # Par défaut chaque variante a ses propres bornes...
    apart_bounds = apart.groupby("variable")["a_relative_min"].first()
    assert apart_bounds["QA_obs"] != apart_bounds["QA_sim"]
    # ...et mises en commun, les deux deviennent comparables.
    pooled_bounds = pooled.groupby("variable")["a_relative_min"].first()
    assert pooled_bounds["QA_obs"] == pooled_bounds["QA_sim"]


def test_relative_falls_back_on_the_base_name():
    """{'QA': False} couvre QA_obs et QA_sim sans les nommer un par un."""
    t = process_trend(_suffixed(["QA_obs", "QA_sim"]),
                      suffix=["obs", "sim"], relative={"QA": False},
                      verbose=False)
    assert t["a_relative"].isna().all()
    assert t["a"].notna().all()


def test_relative_dict_must_cover_every_variable():
    with pytest.raises(ValueError, match="ne couvre pas"):
        process_trend(_suffixed(["QA", "QJXA"]),
                      relative={"QA": True, "autre": False}, verbose=False)
