"""Goldens R de process_extraction : 11 scénarios, tous les time_steps.

Références : tests/data/ref_extraction/*.csv, générées par le package R
EXstat (ref_extraction.R d'EXstat_Claude) sur un même jeu d'entrée de
3 séries journalières synthétiques (2001-2015, lacunes comprises).

Les valeurs extraites doivent concorder avec R à 1e-8. NApct n'est
comparé strictement que là où Python et R utilisent le même dénominateur :
les divergences NApct connues et intentionnelles (dénominateur en jours
calendaires réels côté Python vs 365.25/30.4375 côté R) sont couvertes
par napct_strict=False, comme dans la validation d'origine (22/22).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stase import process_extraction

REF = Path(__file__).parent / "data" / "ref_extraction"
TOL = 1e-8


def _load(name):
    df = pd.read_csv(REF / f"{name}.csv")
    for col in df.columns:
        if col == "Date" or "date" in col.lower():
            df[col] = pd.to_datetime(df[col])
    return df


@pytest.fixture(scope="module")
def data():
    return _load("input_common")


def assert_matches_r(py_out, ref_name, value_col, merge_on=("ID", "Date"),
                     napct_strict=True, rename=None):
    r_out = _load(ref_name)
    if rename:
        r_out = r_out.rename(columns=rename)
    # noms de sortie Python : snake_case (la colonne de date garde le nom
    # d'entrée, ici 'Date' comme dans les CSVs de référence R)
    r_out = r_out.rename(columns={"NApct": "na_pct", "Month": "month",
                                  "Season": "season", "Yearday": "yearday",
                                  "YearSeason": "year_season"})
    merge_on = list(merge_on)

    merged = r_out[merge_on + [value_col, "na_pct"]].rename(
        columns={value_col: "R_val", "na_pct": "R_NApct"}
    ).merge(
        py_out[merge_on + [value_col, "na_pct"]].rename(
            columns={value_col: "Py_val", "na_pct": "Py_NApct"}
        ),
        on=merge_on, how="outer",
    )
    assert len(merged) == len(r_out), (
        f"{ref_name}: {len(merged)} lignes après merge, {len(r_out)} attendues"
    )

    one_nan = merged["R_val"].isna() ^ merged["Py_val"].isna()
    assert not one_nan.any(), (
        f"{ref_name}: NA d'un seul côté\n"
        f"{merged[one_nan][merge_on + ['R_val', 'Py_val']].head().to_string()}"
    )
    both = merged["R_val"].notna()
    np.testing.assert_allclose(
        merged.loc[both, "Py_val"], merged.loc[both, "R_val"],
        atol=TOL, rtol=0, err_msg=f"{ref_name}: valeurs {value_col}",
    )
    if napct_strict:
        np.testing.assert_allclose(
            merged["Py_NApct"], merged["R_NApct"], atol=1.0, rtol=0,
            err_msg=f"{ref_name}: NApct",
        )


# ── time_step = 'year' ───────────────────────────────────────────────────────

def test_sc1_year_default(data):
    py = process_extraction(data, func={"QA": (np.mean, "Q", {"skipna": True})},
                            time_step="year", drop_na_pct=False)
    assert_matches_r(py, "sc1_year_default_output", "QA")


def test_sc2_year_hydro_september(data):
    py = process_extraction(data, func={"QJXA": (np.max, "Q", {"skipna": True})},
                            time_step="year", sampling_period="09-01",
                            drop_na_pct=False)
    assert_matches_r(py, "sc2_year_hydro_sep_output", "QJXA")


def test_sc3_year_sub_window(data):
    py = process_extraction(data, func={"QA": (np.mean, "Q", {"skipna": True})},
                            time_step="year", sampling_period=["05-01", "11-30"],
                            drop_na_pct=False)
    assert_matches_r(py, "sc3_year_sub_window_output", "QA",
                     rename={"QMNA": "QA"})


def test_sc8_year_mid_month_start(data):
    py = process_extraction(data, func={"QA": (np.mean, "Q", {"skipna": True})},
                            time_step="year", sampling_period="03-15",
                            drop_na_pct=False)
    assert_matches_r(py, "sc8_year_march15_output", "QA")


def test_sc9_year_cross_sub_window(data):
    py = process_extraction(data, func={"QA": (np.mean, "Q", {"skipna": True})},
                            time_step="year", sampling_period=["11-01", "04-30"],
                            drop_na_pct=False)
    assert_matches_r(py, "sc9_year_cross_subwindow_output", "QA",
                     napct_strict=False)


# ── autres time_steps ────────────────────────────────────────────────────────

def test_sc11_year_month(data):
    py = process_extraction(data, func={"QM": (np.mean, "Q", {"skipna": True})},
                            time_step="year-month", drop_na_pct=False)
    assert_matches_r(py, "sc11_yearmonth_default_output", "QM",
                     napct_strict=False)


def test_sc12_month(data):
    py = process_extraction(data, func={"QM": (np.mean, "Q", {"skipna": True})},
                            time_step="month", drop_na_pct=False)
    assert_matches_r(py, "sc12_month_default_output", "QM",
                     merge_on=("ID", "Date"), napct_strict=False)


def test_sc13_year_season(data):
    py = process_extraction(data, func={"QS": (np.mean, "Q", {"skipna": True})},
                            time_step="year-season", drop_na_pct=False)
    assert_matches_r(py, "sc13_yearseason_default_output", "QS",
                     napct_strict=False)


def test_sc14_season(data):
    py = process_extraction(data, func={"QS": (np.mean, "Q", {"skipna": True})},
                            time_step="season", drop_na_pct=False)
    assert_matches_r(py, "sc14_season_default_output", "QS",
                     merge_on=("ID", "season"), napct_strict=False)


def test_sc15_yearday(data):
    py = process_extraction(data, func={"QJA": (np.mean, "Q", {"skipna": True})},
                            time_step="yearday", drop_na_pct=False)
    assert_matches_r(py, "sc15_yearday_default_output", "QJA",
                     merge_on=("ID", "yearday"), napct_strict=False)


def test_sc16_none(data):
    py = process_extraction(data, func={"QA": (np.mean, "Q", {"skipna": True})},
                            time_step="none", drop_na_pct=False)
    assert_matches_r(py, "sc16_none_default_output", "QA", merge_on=("ID",))
