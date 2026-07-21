"""Rôle « colonne de paramètre » (param_cols).

Une colonne fournie par l'appelant, souvent une date, constante par
série, qui n'est ni l'axe temporel, ni l'id, ni une mesure agrégée. Elle
est :
  - mise de côté à la détection (l'axe et l'id tombent par élimination) ;
  - référençable par une fonction (mécanisme kwarg existant, tout dtype) ;
  - exclue du canal numérique (value_cols, max_na_years) ;
  - suffixable (fan-out : réf partagée, variante éclatée) ;
  - CONSERVÉE dans la sortie, pour traverser un enchaînement de process.

Sans param_cols, comportement strictement inchangé (rétrocompat).
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from stase import process_extraction


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


def _param_year(X, p):
    """Année de la colonne-paramètre p (constante), en int."""
    return int(pd.to_datetime(pd.Series(p)).dropna().dt.year.iloc[0])


def _daily_with_param(id_="S1", start="2000-01-01", end="2009-12-31",
                      ref="1990-01-01", seed=0):
    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "id": id_,
        "date": dates,
        "Q": 10 + rng.gamma(2.0, 2.0, len(dates)),
        "ref_start": pd.Timestamp(ref),      # paramètre datetime, constant
    })


# ── détection : le paramètre n'entre pas en collision avec l'axe ──────────

def test_datetime_param_collides_without_tag():
    df = _daily_with_param()
    with pytest.raises(ValueError, match="datetime"):
        process_extraction(
            df, func={"y": (_param_year, "Q", {"p": "ref_start"})},
            time_step="none")


def test_datetime_param_ok_when_tagged():
    df = _daily_with_param(ref="1990-01-01")
    out = _quiet(process_extraction,
                 df, func={"y": (_param_year, "Q", {"p": "ref_start"})},
                 time_step="none", param_cols=["ref_start"])
    assert out["y"].iloc[0] == 1990


# ── exclusion du canal numérique + conservation ───────────────────────────

def test_param_excluded_from_value_machinery_and_carried():
    """Un paramètre datetime traverse max_na_years sans être converti en
    float ni tronqué : il ressort datetime, valeur intacte."""
    df = _daily_with_param(ref="1985-06-15")
    out = _quiet(process_extraction,
                 df, func={"y": (_param_year, "Q", {"p": "ref_start"})},
                 time_step="none", max_na_years=2, param_cols=["ref_start"])
    assert "ref_start" in out.columns
    assert pd.api.types.is_datetime64_any_dtype(out["ref_start"])
    assert out["ref_start"].iloc[0] == pd.Timestamp("1985-06-15")


def test_param_carried_even_when_unused_by_func():
    df = _daily_with_param(ref="1976-01-01")
    out = _quiet(process_extraction,
                 df, func={"QA": (np.nanmean, "Q")},
                 time_step="year", param_cols=["ref_start"])
    assert (out["ref_start"] == pd.Timestamp("1976-01-01")).all()


# ── traversée P1 -> P2 (le point de responsabilité) ───────────────────────

def test_param_threads_through_two_processes():
    df = _daily_with_param(ref="1976-01-01")
    p1 = _quiet(process_extraction,
                df, func={"QA": (np.nanmean, "Q")},
                time_step="year", param_cols=["ref_start"])
    # ref_start a survécu à P1 ; P2 le consomme
    p2 = _quiet(process_extraction,
                p1, func={"y": (_param_year, "QA", {"p": "ref_start"})},
                time_step="none", param_cols=["ref_start"])
    assert p2["y"].iloc[0] == 1976


# ── fan-out suffixe : réf partagée, horizon éclaté ────────────────────────

def _daily_shared_and_suffixed(id_="S1"):
    dates = pd.date_range("2000-01-01", "2009-12-31", freq="D")
    return pd.DataFrame({
        "id": id_,
        "date": dates,
        "Q": np.arange(len(dates), dtype=float),
        "ref_start": pd.Timestamp("1990-01-01"),         # partagé
        "horizon_start_H1": pd.Timestamp("2020-01-01"),  # éclaté
        "horizon_start_H2": pd.Timestamp("2040-01-01"),
    })


def test_suffix_shares_ref_and_fans_horizon():
    df = _daily_shared_and_suffixed()
    param_cols = ["ref_start", "horizon_start_H1", "horizon_start_H2"]

    def _pair(X, r, h):
        yr = int(pd.to_datetime(pd.Series(r)).dropna().dt.year.iloc[0])
        yh = int(pd.to_datetime(pd.Series(h)).dropna().dt.year.iloc[0])
        return yr * 10000 + yh

    out = _quiet(
        process_extraction, df,
        func={"d": (_pair, "Q", {"r": "ref_start", "h": "horizon_start"})},
        time_step="none", suffix=["H1", "H2"], param_cols=param_cols)

    codes = {c: int(out[c].iloc[0]) for c in out.columns if c.startswith("d")}
    assert set(codes) == {"d_H1", "d_H2"}
    assert codes["d_H1"] == 1990 * 10000 + 2020   # réf partagée, horizon H1
    assert codes["d_H2"] == 1990 * 10000 + 2040   # réf partagée, horizon H2


# ── contrat : constant par série ──────────────────────────────────────────

def test_param_must_be_constant_per_series():
    df = _daily_with_param()
    df.loc[df.index[:100], "ref_start"] = pd.Timestamp("1999-01-01")  # varie
    with pytest.raises(ValueError, match="constant"):
        _quiet(process_extraction,
               df, func={"y": (_param_year, "Q", {"p": "ref_start"})},
               time_step="none", param_cols=["ref_start"])


# ── rétrocompat : param_cols=None est un no-op ────────────────────────────

def test_no_param_cols_unchanged():
    dates = pd.date_range("2000-01-01", "2005-12-31", freq="D")
    df = pd.DataFrame({"id": "S1", "date": dates,
                       "Q": np.arange(len(dates), dtype=float)})
    a = _quiet(process_extraction, df, func={"QA": (np.nanmean, "Q")},
               time_step="year")
    b = _quiet(process_extraction, df, func={"QA": (np.nanmean, "Q")},
               time_step="year", param_cols=None)
    pd.testing.assert_frame_equal(a, b)
