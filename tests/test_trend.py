"""Tests de process_trend — goldens R + cas limites.

Goldens : tests/data/ref_trend/pt_sc*.csv, générés par le package R EXstat
(compare_process_trend.R d'EXstat_Claude) — 16 séries × 2 variables,
1990-2019. Tolérance 1e-10 (INDE/AR1 concordent exactement avec R).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stase import process_trend

REF = Path(__file__).parent / "data" / "ref_trend"

NUM_BASE = ["p", "a", "b", "mean_period_trend", "a_normalise",
            "a_normalise_min", "a_normalise_max"]
DATE_BASE = ["period_trend_start", "period_trend_end"]


@pytest.fixture(scope="module")
def raw():
    df = pd.read_csv(REF / "process_trend_input.csv")
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def assert_matches_ref(py, ref_name, numeric_cols, date_cols=(), atol=1e-10):
    ref = pd.read_csv(REF / f"{ref_name}.csv")
    key = ["ID", "variable_en"]
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
    py = process_trend(raw, MK_level=0.1, time_dependency_option="INDE",
                       to_normalise=True, verbose=False)
    assert_matches_ref(py, "pt_sc1_inde_norm", NUM_BASE, DATE_BASE)


def test_sc2_ar1_no_normalise(raw):
    py = process_trend(raw, MK_level=0.1, time_dependency_option="AR1",
                       to_normalise=False, verbose=False)
    assert_matches_ref(py, "pt_sc2_ar1_nonorm",
                       ["p", "a", "b", "a_normalise",
                        "a_normalise_min", "a_normalise_max"],
                       DATE_BASE)


def test_sc3_inde_period_trend(raw):
    py = process_trend(raw, MK_level=0.1, time_dependency_option="INDE",
                       to_normalise=True,
                       period_trend=["1995-01-01", "2010-12-31"],
                       verbose=False)
    assert_matches_ref(py, "pt_sc3_inde_period", NUM_BASE, DATE_BASE)


def test_sc4_inde_period_change(raw):
    py = process_trend(raw, MK_level=0.1, time_dependency_option="INDE",
                       to_normalise=True,
                       period_change=[["1990-01-01", "2004-12-31"],
                                      ["2005-01-01", "2019-12-31"]],
                       verbose=False)
    assert_matches_ref(
        py, "pt_sc4_inde_change",
        NUM_BASE + ["change", "change_min", "change_max",
                    "mean_period_change_1", "mean_period_change_2"],
        DATE_BASE + ["period_change_start_1", "period_change_end_1",
                     "period_change_start_2", "period_change_end_2"],
    )


def test_sc5_extreme_no_signif(raw):
    py = process_trend(raw, MK_level=0.1, time_dependency_option="INDE",
                       to_normalise=True,
                       extreme_take_not_signif_into_account=False,
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


def test_period_trend_outside_data_returns_empty():
    with pytest.warns(UserWarning):
        t = process_trend(_yearly(), period_trend=["2050-01-01", "2060-12-31"],
                          verbose=False)
    assert len(t) == 0


def test_empty_input_returns_empty():
    with pytest.warns(UserWarning):
        t = process_trend(pd.DataFrame({"ID": [], "Date": [], "X": []})
                          .astype({"Date": "datetime64[ns]"}))
    assert len(t) == 0
