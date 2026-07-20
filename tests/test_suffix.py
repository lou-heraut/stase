"""Tests du paramètre suffix de process_extraction.

Règle : une référence de colonne n'est suffixée que si la colonne suffixée
existe dans les données ; sinon la colonne de base est conservée. Une
fonction dont aucune référence n'a de variante suffixée est calculée une
seule fois, sans suffixe.
"""

import numpy as np
import pandas as pd
import pytest

from stase import process_extraction


def scenarios(start="2000-01-01", end="2004-12-31", seed=3):
    """Chronique avec deux variantes suffixées d'une même grandeur."""
    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    q = 10 + rng.normal(0, 1, len(dates))
    return pd.DataFrame({"id": "S1", "date": dates,
                         "Q_obs": q * 1.1, "Q_sim": q * 0.85})


# ── parité R : toutes les colonnes référencées ont une variante ─────────────

def test_suffix_equals_separate_calls():
    """Le produit cartésien reproduit deux appels individuels (SC20 du
    harnais R)."""
    data = scenarios()
    both = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                              suffix=["obs", "sim"], time_step="year")
    ref_obs = process_extraction(data, func={"QA_obs": (np.nanmean, "Q_obs")},
                                 time_step="year")
    ref_sim = process_extraction(data, func={"QA_sim": (np.nanmean, "Q_sim")},
                                 time_step="year")
    assert {"QA_obs", "QA_sim"} <= set(both.columns)
    pd.testing.assert_series_equal(both["QA_obs"], ref_obs["QA_obs"])
    pd.testing.assert_series_equal(both["QA_sim"], ref_sim["QA_sim"])


def test_suffix_auto_detects_column_when_none_given():
    data = scenarios()
    r = process_extraction(data, func={"QA": np.nanmean},
                           suffix=["obs"], time_step="year")
    ref = process_extraction(data, func={"QA_obs": (np.nanmean, "Q_obs")},
                             time_step="year")
    pd.testing.assert_series_equal(r["QA_obs"], ref["QA_obs"])


def test_suffix_auto_detection_reports_no_match():
    data = scenarios()
    with pytest.raises(ValueError, match="aucune colonne numérique"):
        process_extraction(data, func={"QA": np.nanmean},
                           suffix=["ref"], time_step="year")


# ── référence sans variante : colonne de base conservée ────────────────────

def test_function_without_suffixed_column_is_computed_once():
    """R n'a pas de variante R_obs/R_sim : RA sort une seule fois, nue."""
    data = scenarios().assign(R=lambda d: d["Q_obs"] / 3)
    r = process_extraction(data, func={"RA": (np.nanmean, "R")},
                           suffix=["obs", "sim"], time_step="year")
    assert "RA" in r.columns
    assert not {"RA_obs", "RA_sim"} & set(r.columns)
    ref = process_extraction(data, func={"RA": (np.nanmean, "R")},
                             time_step="year")
    pd.testing.assert_series_equal(r["RA"], ref["RA"])


def test_mixed_reference_suffixes_only_what_varies():
    """Un argument varie, l'autre est partagé : la sortie est suffixée et
    la colonne partagée reste la même pour tous les suffixes."""
    data = scenarios().assign(R=lambda d: d["Q_obs"] / 3)

    def ratio(shared, variant):
        return float(np.nanmean(shared) / np.nanmean(variant))

    r = process_extraction(data, func={"RAT": (ratio, "R", "Q")},
                           suffix=["obs", "sim"], time_step="year")
    assert {"RAT_obs", "RAT_sim"} <= set(r.columns)

    year = data[data.date.dt.year == 2001]
    assert r[r.date == "2001-01-01"]["RAT_obs"].iloc[0] == pytest.approx(
        np.nanmean(year["R"]) / np.nanmean(year["Q_obs"]))
    assert r[r.date == "2001-01-01"]["RAT_sim"].iloc[0] == pytest.approx(
        np.nanmean(year["R"]) / np.nanmean(year["Q_sim"]))


def test_base_column_loses_to_its_own_variant():
    """Si la colonne partagée s'appelle Q et que les variantes s'appellent
    Q_obs/Q_sim, alors Q EST suffixable : on ne peut pas à la fois nommer
    une série partagée Q et des scénarios Q_<suffixe>. C'est la raison pour
    laquelle une colonne de seuil doit s'appeler Q_lim_<suffixe> et non
    Q_<suffixe>, sans quoi elle se substituerait à la série de débit."""
    data = scenarios().assign(Q=lambda d: d["Q_obs"] / 1.1)
    r = process_extraction(data, func={"QA": (np.nanmean, "Q")},
                           suffix=["obs", "sim"], time_step="year")
    assert {"QA_obs", "QA_sim"} <= set(r.columns)
    assert "QA" not in r.columns


def test_kwarg_column_reference_follows_the_suffix():
    """Les kwargs-colonnes sont des références comme les autres : c'est le
    cas des seuils (threshold=Qlim → Qlim_DOE)."""
    dates = pd.date_range("2000-01-01", "2002-12-31", freq="D")
    data = pd.DataFrame({"id": "S1", "date": dates,
                         "Q": np.linspace(1, 20, len(dates)),
                         "Qlim_low": 5.0, "Qlim_high": 15.0})

    def share_below(q, threshold):
        return float(np.mean(q < np.nanmean(threshold)) * 100)

    r = process_extraction(
        data, func={"P": (share_below, "Q", {"threshold": "Qlim"})},
        suffix=["low", "high"], time_step="year")

    assert {"P_low", "P_high"} <= set(r.columns)
    year = data[data.date.dt.year == 2001]
    assert r[r.date == "2001-01-01"]["P_low"].iloc[0] == pytest.approx(
        float(np.mean(year["Q"] < 5.0) * 100))
    assert r[r.date == "2001-01-01"]["P_high"].iloc[0] == pytest.approx(
        float(np.mean(year["Q"] < 15.0) * 100))


def test_static_kwargs_are_left_alone():
    """Un kwarg qui ne désigne pas une colonne n'est jamais suffixé."""
    data = scenarios()

    def trimmed(q, side):
        return float(np.nanmax(q) if side == "high" else np.nanmin(q))

    r = process_extraction(data, func={"X": (trimmed, "Q", {"side": "high"})},
                           suffix=["obs", "sim"], time_step="year")
    year = data[data.date.dt.year == 2001]
    assert r[r.date == "2001-01-01"]["X_obs"].iloc[0] == pytest.approx(
        float(np.nanmax(year["Q_obs"])))


def test_shared_step_is_not_recomputed_per_suffix():
    """Une fonction non suffixable n'est évaluée qu'une fois, quel que soit
    le nombre de suffixes."""
    data = scenarios().assign(Q=lambda d: d["Q_obs"] / 1.1)
    calls = {"n": 0}

    def counted(q):
        calls["n"] += 1
        return float(np.nanmean(q))

    process_extraction(data, func={"QA": (counted, "Q")},
                       suffix=["a", "b", "c"], time_step="year")
    n_shared = calls["n"]

    calls["n"] = 0
    process_extraction(data, func={"QA": (counted, "Q")}, time_step="year")
    assert n_shared == calls["n"]
