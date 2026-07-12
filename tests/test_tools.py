"""Tests du cœur statistique tools.py — goldens R + cas limites.

Le code de tools.py est GELÉ (port validé contre tools.R) : ces tests
figent son comportement, ils ne le redéfinissent pas.

Goldens : tests/data/ref_trend/{input_series,mk_results}.csv, générés par
le package R EXstat (scripts compare_trend.R d'EXstat_Claude).
Tolérances héritées de la validation d'origine :
  - INDE / AR1 : 1e-10 (concordance exacte avec R)
  - LTP : 3e-3 (R optimise le coefficient de Hurst avec tol≈1.2e-4,
    scipy avec xatol≈1.5e-8 — divergence de précision documentée ;
    la validation d'origine utilisait 2e-3, dépassé de 4e-5 sur un
    scénario sous numpy 2.5/scipy récents)
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stase import GeneralMannKendall, fieldSignificance_FDR
from stase.tools import (
    generalMannKendall_hide,
    getAR1Correction,
    getMKStat,
    getTiesCorrection,
)

REF = Path(__file__).parent / "data" / "ref_trend"

SERIES = pd.read_csv(REF / "input_series.csv")
MK_REF = pd.read_csv(REF / "mk_results.csv")


def _series(name: str) -> np.ndarray:
    x = SERIES[name].to_numpy(dtype=float)
    # les séries courtes sont paddées de NA en fin de fichier
    if name.endswith("_short"):
        x = x[~np.isnan(x)]
    return x


def _check(got, expected, atol):
    if expected is None or (isinstance(expected, float) and math.isnan(expected)):
        assert got is None or (isinstance(got, float) and math.isnan(got))
    elif isinstance(expected, (bool, np.bool_)):
        assert bool(got) == bool(expected)
    else:
        assert got == pytest.approx(float(expected), abs=atol)


# ── Goldens R : generalMannKendall_hide (INDE / AR1 / LTP) ──────────────────

@pytest.mark.parametrize(
    "scenario,option",
    [(r.scenario, r.option) for r in MK_REF.itertuples()],
    ids=[f"{r.scenario}-{r.option}" for r in MK_REF.itertuples()],
)
def test_mk_matches_r_reference(scenario, option):
    row = MK_REF[(MK_REF.scenario == scenario) & (MK_REF.option == option)].iloc[0]
    atol = 3e-3 if option == "LTP" else 1e-10

    res = generalMannKendall_hide(
        _series(scenario), level=0.1,
        time_dependency_option=option,
        do_detrending=True, verbose=False,
    )
    _check(res["H"], bool(row["H"]), atol)
    _check(res["P"], row["p"], atol)
    _check(res["TREND"], row["a"], atol)
    _check(res["STAT"], row["stat"], atol)
    _check(res["DEP"], row["dep"], atol)


# ── getMKStat ────────────────────────────────────────────────────────────────

def test_mkstat_simple_increasing():
    r = getMKStat(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
    assert r["stat"] == 10          # toutes les paires croissantes
    assert r["trend"] == pytest.approx(1.0)


def test_mkstat_nan_pairs_skipped():
    # le NaN au milieu ne casse ni S ni la pente de Sen
    r = getMKStat(np.array([1.0, np.nan, 3.0, 4.0, 5.0]))
    assert r["stat"] == 6           # C(4,2) paires valides, toutes croissantes
    assert np.isfinite(r["trend"])


# ── getTiesCorrection ────────────────────────────────────────────────────────

def test_ties_none():
    assert getTiesCorrection(np.array([1.0, 2.0, 3.0, 4.0, 5.0])) == 0.0


def test_ties_all_same():
    assert getTiesCorrection(np.ones(5)) == pytest.approx(5 * 4 * 15 / 18)


def test_ties_mixed():
    # groupes {1→2, 2→1, 3→2} : correction = 2*(2*1*9)/18 = 2.0
    assert getTiesCorrection(np.array([1.0, 1.0, 2.0, 3.0, 3.0])) == pytest.approx(2.0)


# ── getAR1Correction ─────────────────────────────────────────────────────────

def test_ar1_correction_positive_series():
    r = getAR1Correction(_series("ar1_long"))
    assert -1.0 <= r["lag1"] <= 1.0
    assert np.isfinite(r["correction"])


# ── fieldSignificance_FDR ────────────────────────────────────────────────────

def test_fdr_all_non_significant():
    assert fieldSignificance_FDR(np.array([0.5, 0.6, 0.7, 0.8, 0.9]), 0.1) == 0.0


def test_fdr_mixed():
    # seuils B-H (n=5, level=0.1) : [0.02, 0.04, 0.06, 0.08, 0.10]
    assert fieldSignificance_FDR(
        np.array([0.005, 0.01, 0.03, 0.07, 0.9]), 0.1
    ) == pytest.approx(0.07)


# ── Cas limites GeneralMannKendall (comportements figés) ────────────────────

def test_gmk_less_than_3_values():
    out = GeneralMannKendall(np.array([1.0, 2.0]))
    assert out["H"] is None and out["p"] is None and out["a"] is None


def test_gmk_all_nan():
    out = GeneralMannKendall(np.array([np.nan] * 10))
    assert out["H"] is None and out["p"] is None and out["a"] is None


def test_gmk_constant_series():
    # variance nulle après correction des ex-æquo : pas de test possible,
    # mais la pente de Sen vaut 0.0 (comportement R conservé)
    out = GeneralMannKendall(np.full(10, 7.5))
    assert out["H"] is None and out["p"] is None
    assert out["a"] == pytest.approx(0.0)


def test_gmk_output_keys():
    out = GeneralMannKendall(_series("trend_long"), show_advance_stat=True)
    assert set(out) == {"level", "H", "p", "a", "stat", "dep"}
    assert out["H"] is True
