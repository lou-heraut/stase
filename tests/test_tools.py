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


# ── LTP : variance par blocs — équivalence exacte ────────────────────────────

def _hurst_autocov(n, H):
    lam = np.arange(n + 1, dtype=float)
    return 0.5 * (np.abs(lam + 1) ** (2 * H)
                  - 2 * np.abs(lam) ** (2 * H)
                  + np.abs(lam - 1) ** (2 * H))


@pytest.mark.parametrize("n,H", [(5, 0.6), (10, 0.75), (15, 0.8)])
def test_ltp_variance_blocked_matches_naive(n, H):
    from stase.tools import _ltp_variance_naive, _ltp_variance_vectorized
    C = _hurst_autocov(n, H)
    assert _ltp_variance_vectorized(C, n) == pytest.approx(
        _ltp_variance_naive(C, n), abs=1e-10)


@pytest.mark.parametrize("n", [8, 30, 60])
def test_ltp_variance_block_size_invariant(n):
    # forcer plusieurs blocs minuscules doit donner la même somme que le
    # calcul en un seul bloc (mémoire bornée sans changer le résultat)
    from stase.tools import _ltp_variance_vectorized
    C = _hurst_autocov(n, 0.7)
    full = _ltp_variance_vectorized(C, n)
    tiny_blocks = _ltp_variance_vectorized(C, n, block_elems=64)
    assert tiny_blocks == pytest.approx(full, rel=1e-12)


# ── LTP : reproductibilité du tirage des ex-æquo ─────────────────────────────

def _series_with_ties(n=40, seed=3):
    rng = np.random.default_rng(seed)
    x = np.round(rng.gamma(2.0, 5.0, n), 0)   # arrondi entier → ex-æquo
    assert len(np.unique(x)) < n              # le test exige des ex-æquo
    return x


def test_ltp_seeded_is_reproducible_with_ties():
    x = _series_with_ties()
    r1 = GeneralMannKendall(x, time_dependency_option="LTP", rng=42)
    r2 = GeneralMannKendall(x, time_dependency_option="LTP", rng=42)
    assert r1 == r2
    assert np.isfinite(r1["p"]) and 0.0 <= r1["p"] <= 1.0


def test_ltp_rng_irrelevant_without_ties():
    # sans ex-æquo, le tirage n'intervient pas : tous les rng équivalents.
    # NB : les ex-æquo se jugent sur la série DÉTENDANCÉE (le détendançage
    # peut en créer sur des données arrondies) — stat_short est vérifiée
    # sans ex-æquo après détendançage.
    x = _series("stat_short")
    trend = getMKStat(x)["trend"]
    detrended = x - trend * np.arange(1, len(x) + 1)
    assert len(np.unique(detrended)) == len(detrended)
    r1 = GeneralMannKendall(x, time_dependency_option="LTP", rng=1)
    r2 = GeneralMannKendall(x, time_dependency_option="LTP", rng=2)
    r3 = GeneralMannKendall(x, time_dependency_option="LTP")
    assert r1 == r2 == r3


def test_ltp_does_not_touch_global_random_state():
    # l'appel LTP (même avec ex-æquo) ne consomme plus le RNG global numpy
    x = _series_with_ties()
    np.random.seed(123)
    expected = np.random.rand(3)
    np.random.seed(123)
    GeneralMannKendall(x, time_dependency_option="LTP")
    got = np.random.rand(3)
    np.testing.assert_array_equal(expected, got)


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
