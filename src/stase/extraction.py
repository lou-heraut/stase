# Copyright 2021-2026 Louis Héraut <louis.heraut@inrae.fr>*1
#           2023      Éric Sauquet <eric.sauquet@inrae.fr>*1
#                     Jean-Philippe Vidal <jean-philippe.vidal@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
# *2 INRAE, RECOVER, Aix-Marseille Université, Aix-en-Provence, France
#
# This file is part of the stase Python package (Python port of the
# EXstat R package).
#
# stase is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.
#
# stase is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.

"""
process_extraction — Python implementation of R/process_extraction.R

Optimisations vs implémentation naïve :
  - Comptage NA : size() - count() (C-level pandas), pas de boucle Python par groupe
  - Application de funct séparée du comptage NA (groupby().agg())
  - Mapping saison/yearday : indexage numpy (zéro loop sur les lignes)
  - NApct : calcul vectoriel numpy, pas de apply(axis=1)
  - Pas de duplication de tableau (pas d'équivalent purrr::reduce)

Corrections vs R :
  - Filtrage par date calendaire pure (plus de comptage de jours)
  - Tolérance aux trous dans les chroniques
  - NApct : dénominateur = jours calendaires réels (pas 365.25/30.4375)
"""

from __future__ import annotations

import calendar
import warnings
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

import numpy as np
import pandas as pd

from ._display import _verbose_box


@dataclass(frozen=True)
class Adaptive:
    """sampling_period adaptatif par série.

    L'année hydrologique de chaque série démarre au premier jour du mois
    où `funct` (ex. np.nanmax, np.nanmin) est atteint sur les moyennes
    mensuelles inter-annuelles de la colonne `col`. Équivalent du
    `sampling_period = list(max, list("Q", na.rm=TRUE))` du EXstat R.

    default : mois de repli 'MM-DD' si la série est vide ou toute-NaN.
    """
    funct: Callable
    col: str
    default: str = "09-01"


# Clé DataFrame.attrs par laquelle process_extraction signale les colonnes
# « creuses » produites par un fan-out keep='all' (valeur sur la première
# ligne de chaque groupe, NaN ailleurs). À l'appel suivant, si les colonnes
# utilisées sont toutes creuses, les lignes de remplissage sont compactées
# afin que NApct mesure la complétude réelle (en R, ces NaN de construction
# sont invisibles au comptage via is.na_not_nan — distinction NA/NaN
# impossible en pandas).
_SPARSE_ATTR = "stase_sparse"

# Clé DataFrame.attrs interne : sortie 'transform' de time_step 'none'
# dont l'index correspond aux positions des lignes d'entrée — autorise le
# fan-out keep='all' par simple alignement d'index au lieu d'un merge.
_ALIGNED_ATTR = "stase_row_aligned"

# Alias Cython pandas pour les fonctions d'agrégation courantes.
# Quand funct est dans ce dict et qu'il n'y a pas de kwargs, on passe une
# chaîne à .agg() → chemin Cython (zéro appel Python par groupe).
#
# np.argmax / np.argmin sont intentionnellement absents :
#   pandas.Series.idxmax() retourne le LABEL d'index, pas la position 0-based.
#   Il n'existe pas d'alias Cython pour un argmax positionnel en pandas.
_PANDAS_AGG_ALIASES: dict = {
    np.mean:   "mean",
    np.max:    "max",
    np.min:    "min",
    np.sum:    "sum",
    np.std:    "std",
    np.median: "median",
    np.var:    "var",
    max:       "max",
    min:       "min",
    sum:       "sum",
    # variantes nan* : les agrégations pandas sont skipna par défaut,
    # valeurs identiques (all-NaN → NaN, sauf sum → 0.0 des deux côtés)
    np.nanmean:   "mean",
    np.nanmax:    "max",
    np.nanmin:    "min",
    np.nansum:    "sum",
    np.nanmedian: "median",
    np.nanstd:    "std",
}

# Colonnes structurelles (hors id et valeurs) par time_step.
_STRUCT_COLS: dict[str, list[str]] = {
    "year":        ["Date"],
    "year-month":  ["Date"],
    "month":       ["Date", "Month"],
    "year-season": ["Date", "YearSeason"],
    "season":      ["Date", "Season"],
    "yearday":     ["Date", "Yearday"],
    "none":        [],
}

# Dtypes des colonnes structurelles pour les retours vides typés.
_STRUCT_DTYPES: dict[str, str] = {
    "Date":       "datetime64[ns]",
    "Month":      "int64",
    "Yearday":    "int64",
    "Season":     "object",
    "YearSeason": "object",
}


def _empty_extraction_frame(
    id_col: str,
    time_step: str,
    var_names: list[str],
    rmNApct: bool,
) -> pd.DataFrame:
    """Retour vide typé : zéro ligne mais les colonnes attendues de la
    sortie standard, pour que filtres / merges / accès aval fonctionnent
    uniformément (r[r.Date > ...], r.QA, r.merge(...))."""
    cols: dict = {id_col: pd.Series(dtype=object)}
    for c in _STRUCT_COLS.get(time_step, []):
        cols[c] = pd.Series(dtype=_STRUCT_DTYPES[c])
    for v in var_names:
        cols[v] = pd.Series(dtype="float64")
    if not rmNApct:
        if len(var_names) == 1:
            cols["NApct"] = pd.Series(dtype="float64")
        else:
            for v in var_names:
                cols[f"NApct_{v}"] = pd.Series(dtype="float64")
    return pd.DataFrame(cols)


# ---------------------------------------------------------------------------
# Helpers calendaires
# ---------------------------------------------------------------------------

def _detect_columns(data: pd.DataFrame) -> tuple[str, str | None, list[str]]:
    """Retourne (date_col, id_col, value_cols)."""
    date_col = None
    id_col = None
    value_cols = []
    for col in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[col]):
            if date_col is not None:
                raise ValueError("Plus d'une colonne datetime trouvée.")
            date_col = col
        elif data[col].dtype == object or pd.api.types.is_string_dtype(data[col]):
            if id_col is None:
                id_col = col
        elif pd.api.types.is_numeric_dtype(data[col]):
            value_cols.append(col)
    if not value_cols:
        raise ValueError("Aucune colonne numérique trouvée dans data.")
    return date_col, id_col, value_cols


def _parse_mmdd(s: str) -> tuple[int, int]:
    parts = s.split("-")
    return int(parts[0]), int(parts[1])


def _validate_mmdd(s) -> str:
    """Valide un élément de sampling_period au format 'MM-DD'.

    Sans cette validation, un format invalide finirait en erreur pandas
    obscure au fond de l'attribution des années hydrologiques.
    """
    msg = (
        f"sampling_period invalide : {s!r}. Format attendu 'MM-DD' "
        "(ex. '09-01'), ou [début, fin], ou un objet Adaptive."
    )
    if not isinstance(s, str):
        raise ValueError(msg)
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(msg)
    try:
        m, d = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(msg) from None
    if not (1 <= m <= 12 and 1 <= d <= 31):
        raise ValueError(
            f"sampling_period invalide : {s!r} — mois hors [01, 12] "
            "ou jour hors [01, 31]."
        )
    return s


def _resolve_sampling_period(
    sampling_period: str | list | None, ref_year: int = 1972,
) -> tuple[str, str]:
    """Normalise sampling_period en (spStart, spEnd) au format 'MM-DD'."""
    if sampling_period is None:
        return "01-01", "12-31"
    if isinstance(sampling_period, str):
        sp = _validate_mmdd(sampling_period)
        start_date = pd.Timestamp(year=ref_year, month=int(sp[:2]), day=int(sp[3:]))
        end_date = start_date - timedelta(days=1)
        return sp, end_date.strftime("%m-%d")
    if isinstance(sampling_period, (list, tuple)):
        if len(sampling_period) == 1:
            return _resolve_sampling_period(sampling_period[0], ref_year)
        sp0, sp1 = sampling_period[0], sampling_period[1]
        sp0_missing = sp0 is None or (isinstance(sp0, float) and np.isnan(sp0))
        sp1_missing = sp1 is None or (isinstance(sp1, float) and np.isnan(sp1))
        if sp0_missing and sp1_missing:
            return "01-01", "12-31"
        if sp0_missing:
            end_d = pd.Timestamp(f"{ref_year}-{_validate_mmdd(sp1)}")
            return (end_d + timedelta(days=1)).strftime("%m-%d"), sp1
        if sp1_missing:
            start_d = pd.Timestamp(f"{ref_year}-{_validate_mmdd(sp0)}")
            return sp0, (start_d - timedelta(days=1)).strftime("%m-%d")
        return _validate_mmdd(str(sp0)), _validate_mmdd(str(sp1))
    raise ValueError(f"sampling_period invalide : {sampling_period!r}")


def _safe_date(year: int, month: int, day: int) -> pd.Timestamp:
    try:
        return pd.Timestamp(year=year, month=month, day=day)
    except ValueError:
        if month == 2 and day == 29:
            return pd.Timestamp(year=year, month=2, day=28)
        raise


def _assign_hydro_year(dates: pd.Series, sp_start: str, sp_end: str, dt2add: int) -> pd.Series:
    """Attribue un label d'année hydrologique (int) à chaque date. Hors fenêtre → NaN."""
    mS, dS = _parse_mmdd(sp_start)
    mE, dE = _parse_mmdd(sp_end)
    month = dates.dt.month.to_numpy()
    day   = dates.dt.day.to_numpy()
    year  = dates.dt.year.to_numpy()
    md    = month * 100 + day
    is_leap = ((year % 4 == 0) & (year % 100 != 0)) | (year % 400 == 0)
    mdS = np.where((mS == 2) & (dS == 29) & ~is_leap, 228, mS * 100 + dS)
    mdE = np.where((mE == 2) & (dE == 29) & ~is_leap, 228, mE * 100 + dE)
    hydro = np.full(len(dates), np.nan)
    if dt2add == 0:
        mask = (md >= mdS) & (md <= mdE)
        hydro[mask] = year[mask].astype(float)
    else:
        after = md >= mdS
        before = md <= mdE
        hydro[after] = year[after].astype(float)
        hydro[before & ~after] = (year[before & ~after] - 1).astype(float)
    return pd.Series(hydro, index=dates.index, dtype=float)


def _window_ndays(hy: int, sp_start: str, sp_end: str, dt2add: int) -> int:
    mS, dS = _parse_mmdd(sp_start)
    mE, dE = _parse_mmdd(sp_end)
    return (_safe_date(hy + dt2add, mE, dE) - _safe_date(hy, mS, dS)).days + 1


def _month_days(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _season_ndays(year: int, start_month: int, season_len: int) -> int:
    """Nombre de jours dans une saison (plusieurs mois consécutifs)."""
    total = 0
    for k in range(season_len):
        m = (start_month - 1 + k) % 12 + 1
        y = year + (start_month - 1 + k) // 12
        total += _month_days(y, m)
    return total


def _build_season_map(seasons: list[str]) -> tuple[list[str], list[int]]:
    """
    Construit le mapping mois→saison depuis ["DJF","MAM","JJA","SON"].
    Retourne (get_season[12], sub_seasons[12]) indexés 0=Jan…11=Dec.
    """
    expanded: list[tuple[str, int]] = []
    for s in seasons:
        for i in range(len(s)):
            expanded.append((s, i))
    # 'D'=Décembre est à l'index 0 ; Janvier est à l'index 1
    expanded = expanded[1:] + expanded[:1]
    return [e[0] for e in expanded], [e[1] for e in expanded]


def _circular_mean_months(months: np.ndarray) -> float:
    """Circular mean of fractional month values [0, 12) — equivalent to CircStats::circ.mean in R."""
    valid = months[~np.isnan(months)]
    if len(valid) == 0:
        return 0.0
    angles = 2.0 * np.pi * valid / 12.0
    mean_angle = np.arctan2(float(np.sin(angles).sum()), float(np.cos(angles).sum()))
    return float((mean_angle * 12.0 / (2.0 * np.pi) + 12.0) % 12.0)


def _apply_is_date(
    ext: pd.DataFrame,
    data_with_hy: pd.DataFrame,
    id_col: str,
    date_col: str,
) -> pd.DataFrame:
    """
    Converts a raw 0-based position index (e.g., np.argmax output) into a
    circular-corrected 0-based day-of-year. Mirrors R's convert_dateEX +
    convert_data_hide logic.

    Steps:
      1. Shift = yday(first real date in window) - 1  →  0-based yday of window start
      2. yday_raw = argmax_0based + Shift
      3. Per-series circular mean of month_frac = (yday_raw+1) / (365.25/12)
      4. Values > mean+6 months → subtract nDay (leap-aware, based on _hy label year)
         Values < mean-6 months → add nDay
    Output _value may be negative or >365 — this is intentional for trend analysis.
    """
    min_dates = (
        data_with_hy.groupby([id_col, "_hy"], observed=True)[date_col].min()
        .rename("_rss").reset_index()
    )
    ext = ext.merge(min_dates, on=[id_col, "_hy"], how="left")

    shift = (ext["_rss"].dt.day_of_year - 1).to_numpy(dtype=np.float64)

    # np.argmax (0-based) + shift = 0-based yday
    # Equivalent to R: which.max (1-based) + shift → 1-based yday → -1 → 0-based yday
    raw_index = ext["_value"].to_numpy(dtype=np.float64)
    yday_raw = raw_index + shift

    # month_frac: R divides the 1-based yday by (365.25/12)
    month_frac = (yday_raw + 1.0) / (365.25 / 12.0)

    # nDay: based on _hy label year (matches R's check_leapYear(year(Date)))
    hy_arr = ext["_hy"].to_numpy()
    n_day = np.array([366 if calendar.isleap(int(y)) else 365 for y in hy_arr],
                     dtype=np.float64)

    ids = ext[id_col].to_numpy()
    result = yday_raw.copy()

    for uid in pd.unique(ids):
        mask = ids == uid
        mf = month_frac[mask]
        yr = yday_raw[mask].copy()
        nd = n_day[mask]
        valid = ~np.isnan(mf)

        mm = _circular_mean_months(mf[valid])
        up_lim = round(mm + 6, 2)
        lo_lim = round(mm - 6, 2)

        above = valid & (mf > up_lim)
        below = valid & (mf < lo_lim)
        yr[above] -= nd[above]
        yr[below] += nd[below]
        result[mask] = yr

    ext = ext.drop(columns=["_rss"])
    # Convert to nullable Int64: integers for non-NA, pd.NA where NaN
    # (float NaN cannot coexist with int in standard numpy/pandas dtypes)
    ext["_value"] = (
        pd.array(
            np.where(np.isnan(result), None, np.round(result).astype(np.int64)),
            dtype=pd.Int64Dtype(),
        )
    )
    return ext


def _detect_resolution(data: pd.DataFrame, date_col: str, id_col: str) -> str:
    """
    Détecte la résolution temporelle de l'entrée par l'espacement médian
    entre dates consécutives dans la première série.
    Retourne : 'day', 'month', 'season', 'year'.
    """
    first_id = data[id_col].iloc[0]
    dates = (data[data[id_col] == first_id][date_col]
             .sort_values().drop_duplicates().reset_index(drop=True))
    if len(dates) < 2:
        return "day"
    med = float(dates.diff().dropna().dt.days.median())
    if med <= 1.5:
        return "day"
    elif med <= 35:
        return "month"
    elif med <= 100:
        return "season"
    return "year"


def _window_nmonths(sp_start: str, sp_end: str, dt2add: int) -> int:
    """
    Nombre de mois calendaires dans la fenêtre d'échantillonnage,
    en utilisant la même logique que _assign_hydro_year
    (date représentative d'un mois = le 1er).
    """
    mS, dS = _parse_mmdd(sp_start)
    mE, dE = _parse_mmdd(sp_end)
    mdS, mdE = mS * 100 + dS, mE * 100 + dE
    count = 0
    for m in range(1, 13):
        md_m = m * 100 + 1          # premier jour du mois
        if dt2add == 0:
            count += mdS <= md_m <= mdE
        else:
            count += (md_m >= mdS) or (md_m <= mdE)
    return count


# Argmax/argmin positionnels par groupe en Cython pur.
# np.nanargmax(groupe) = position 0-based du max en ignorant les NaN —
# reproductible avec idxmax (label du max, skipna, premier ex-æquo comme
# numpy) + cumcount (position dans le groupe). np.argmax/np.argmin ne sont
# PAS mappés : leur sémantique NaN diffère (argmax voit NaN comme max).
_POSITIONAL_AGGS: dict = {
    np.nanargmax: "idxmax",
    np.nanargmin: "idxmin",
}


def _positional_agg(data, g, grp_keys, primary_col, method, skip_na, out_index):
    """Position 0-based de l'extremum par groupe, sans appel Python par
    groupe : cumcount + idxmax/idxmin (Cython). Équivalent exact de
    .agg(np.nanargmax) / .agg(np.nanargmin) — vérifié par test dédié."""
    if skip_na:
        frame = data.loc[data[primary_col].notna()]
        gg = frame.groupby(grp_keys, sort=True, observed=True)
    else:
        frame = data
        gg = g
    # position de chaque ligne dans son groupe (ordre des lignes = ordre
    # que recevrait np.nanargmax)
    pos_in_group = gg.cumcount().to_numpy()
    # idxmax lève sur les groupes tout-NaN → on les écarte (résultat NaN)
    valid_rows = gg[primary_col].transform("count").to_numpy() > 0
    sub = frame.loc[valid_rows]
    labels = getattr(
        sub.groupby(grp_keys, sort=True, observed=True)[primary_col], method
    )()
    # label (RangeIndex → position globale) → position dans le groupe
    pos_map = pd.Series(pos_in_group, index=frame.index)
    values = pos_map.reindex(labels.to_numpy()).astype("float64")
    values.index = labels.index
    values = values.reindex(out_index).rename("_value")
    if not values.isna().any():
        # même dtype que .agg(np.nanargmax) quand aucun groupe n'est vide
        values = values.astype("int64")
    return values


# ---------------------------------------------------------------------------
# Noyau d'agrégation vectorisé
# ---------------------------------------------------------------------------

def _groupby_agg(
    data: pd.DataFrame,
    grp_keys: list[str],
    col_names: str | list[str],
    funct: Callable,
    funct_kwargs: dict,
    skip_na: bool,
) -> pd.DataFrame:
    """
    Agrégation optimisée mémoire + vitesse.

    col_names : colonne unique (str) ou liste de colonnes (multi-colonnes).
    - Mono-colonne : chemin Cython si funct dans _PANDAS_AGG_ALIASES et pas de kwargs.
    - Multi-colonnes : groupby.apply — funct(*[Series_col1, ...], **kwargs).
      Le comptage NA (_nPresent, _nNA) est basé sur la première colonne.

    Retourne un DataFrame [*grp_keys, _nPresent, _nNA, _value].
    """
    if isinstance(col_names, str):
        col_names = [col_names]
    primary_col = col_names[0]
    is_single = len(col_names) == 1

    g = data.groupby(grp_keys, sort=True, observed=True)

    # Comptage C-level sur la colonne primaire
    n_present = g[primary_col].size().rename("_nPresent")
    n_valid_c = g[primary_col].count()
    n_na = (n_present - n_valid_c).rename("_nNA")

    if is_single:
        # Chemin optimisé mono-colonne : Cython si disponible, zéro appel Python par groupe
        if (not funct_kwargs and funct in _POSITIONAL_AGGS
                and data.index.is_unique):
            values = _positional_agg(data, g, grp_keys, primary_col,
                                     _POSITIONAL_AGGS[funct], skip_na,
                                     n_present.index)
            return pd.concat([n_present, n_na, values], axis=1).reset_index()

        if not funct_kwargs and funct in _PANDAS_AGG_ALIASES:
            agg_fn = _PANDAS_AGG_ALIASES[funct]
        elif funct_kwargs:
            agg_fn = lambda x: funct(x, **funct_kwargs)
        else:
            agg_fn = funct

        if skip_na:
            is_na = data[primary_col].isna()
            values = (
                data.loc[~is_na]
                .groupby(grp_keys, sort=True, observed=True)[primary_col]
                .agg(agg_fn)
                .rename("_value")
                .reindex(n_present.index)
            )
        else:
            if isinstance(agg_fn, str):
                # Cython path: pandas handles all-NA groups gracefully (returns NaN)
                values = g[primary_col].agg(agg_fn).rename("_value")
            else:
                # Guard against functions (e.g. np.argmax) that raise on all-NA groups
                def _agg_safe(x, _fn=agg_fn):
                    if x.isna().all():
                        return np.nan
                    return _fn(x)
                values = g[primary_col].agg(_agg_safe).rename("_value")
    else:
        # Chemin multi-colonnes : groupby.apply
        # funct reçoit (*Series_par_colonne, **kwargs) — une Series par colonne listée
        _cols = col_names
        _fn   = funct
        _kw   = funct_kwargs
        _skip = skip_na

        def _multi_apply(sub_df: pd.DataFrame) -> float:
            if _skip:
                mask = sub_df[_cols].notna().all(axis=1)
                sub_df = sub_df.loc[mask]
            if len(sub_df) == 0:
                return np.nan
            return _fn(*[sub_df[c] for c in _cols], **_kw)

        try:
            values = g.apply(_multi_apply, include_groups=False).rename("_value")
        except TypeError:
            # pandas < 2.2 : pas d'include_groups — les clés de groupe sont
            # incluses dans sub_df mais _multi_apply n'accède qu'à _cols
            values = g.apply(_multi_apply).rename("_value")

    return pd.concat([n_present, n_na, values], axis=1).reset_index()


# ---------------------------------------------------------------------------
# NApct vectorisé
# ---------------------------------------------------------------------------

def _napct_vec(n_present: np.ndarray, n_na: np.ndarray, n_expected: np.ndarray) -> np.ndarray:
    """Calcule NApct vectoriellement (pas de apply/loop Python)."""
    n_valid = (n_present - n_na).astype(np.float64)
    ne = n_expected.astype(np.float64)
    return np.where(ne > 0, np.round(np.maximum(0.0, (1.0 - n_valid / ne) * 100.0), 1), 0.0)


# ---------------------------------------------------------------------------
# Helpers multi-fonctions, compress, expand
# ---------------------------------------------------------------------------

def _wrap_literals(fn: Callable, pos_spec: list[tuple]) -> Callable:
    """Réinsère les littéraux positionnels (fn, "col", 2, ...) : l'appelant
    ne passe que les colonnes, le wrapper reconstruit la séquence complète."""
    n_cols = sum(1 for t, _ in pos_spec if t == "col")

    def wrapped(*args, **kwargs):
        it = iter(args[:n_cols])
        extra = args[n_cols:]
        full = [next(it) if t == "col" else v for t, v in pos_spec]
        return fn(*full, *extra, **kwargs)
    return wrapped


def _parse_funct_tuple(t: tuple) -> tuple[Callable, list[str], dict, bool, bool]:
    """
    Parse (fn, *args, kwargs?, is_date?) en
    (fn, col_names, kwargs, skip_na, is_date).

    Règles non ambiguës :
      - dernier élément = is_date   ssi c'est un bool
      - avant-dernier  = kwargs     ssi c'est un dict (après retrait du bool éventuel)
      - str restants                = noms de colonnes
      - numériques restants         = littéraux positionnels, réinsérés à
        leur position par un wrapper (ex. (divided, "dQXA", 2, {...}))
    """
    fn = t[0]
    rest = list(t[1:])

    is_date = False
    if rest and isinstance(rest[-1], bool):
        is_date = rest.pop()

    kwargs: dict = {}
    if rest and isinstance(rest[-1], dict):
        kwargs = rest.pop().copy()

    pos_spec: list[tuple] = []
    for item in rest:
        if isinstance(item, str):
            pos_spec.append(("col", item))
        elif isinstance(item, (int, float)):
            pos_spec.append(("lit", item))
        else:
            raise ValueError(
                f"Élément inattendu dans le tuple funct : {item!r}. "
                "Format attendu : (fn, *col_names_ou_littéraux, kwargs?, is_date?)"
            )
    col_names = [v for t_, v in pos_spec if t_ == "col"]
    if any(t_ == "lit" for t_, _ in pos_spec):
        fn = _wrap_literals(fn, pos_spec)

    skip_na = bool(
        kwargs.pop("skipna", False)
        or kwargs.pop("na_rm", False)
        or kwargs.pop("na.rm", False)
    )
    return fn, col_names, kwargs, skip_na, is_date


def _normalize_funct(
    funct, funct_args, nameEX: str, is_date_global: bool = False
) -> list[tuple]:
    """
    Normalise funct en liste de (name, callable, col_names, kwargs, skip_na, is_date).

    Interface courante (tuples) :
      funct = np.mean                                        → col auto, is_date=is_date_global
      funct = (np.mean, "Q", {"skipna": True})              → col="Q", is_date=False
      funct = {"QA": (np.mean, "Q"), "tQ": (np.argmax, "Q", True)}
      funct = {"QA": np.mean}                               → col auto, is_date=False

    Interface legacy (funct_args) :
      funct = np.mean,         funct_args = ["Q", {"skipna": True}]
      funct = {"QA": np.mean}, funct_args = [["Q"], ["Q"]]
    """

    def _from_tuple(name: str, t: tuple) -> tuple:
        if not callable(t[0]):
            raise ValueError(
                f"Premier élément de funct['{name}'] doit être callable, reçu {type(t[0])}"
            )
        fn, col_names, kwargs, skip_na, is_date = _parse_funct_tuple(t)
        return (name, fn, col_names, kwargs, skip_na, is_date)

    def _from_callable_args(name: str, fn, args) -> tuple:
        col_names: list[str] = []
        kwargs: dict = {}
        for arg in (args or []):
            if isinstance(arg, str):
                col_names.append(arg)
            elif isinstance(arg, dict):
                kwargs = arg.copy()
        skip_na = bool(
            kwargs.pop("skipna", False)
            or kwargs.pop("na_rm", False)
            or kwargs.pop("na.rm", False)
        )
        return (name, fn, col_names, kwargs, skip_na, is_date_global)

    # ── tuple (fn, *cols, ...) ───────────────────────────────────────────────
    if isinstance(funct, tuple):
        return [_from_tuple(nameEX, funct)]

    # ── callable simple ──────────────────────────────────────────────────────
    if callable(funct):
        if funct_args is None:
            return [(nameEX, funct, [], {}, False, is_date_global)]
        return [_from_callable_args(nameEX, funct, funct_args)]

    # ── dict {name: callable | tuple} ───────────────────────────────────────
    if isinstance(funct, dict):
        names = list(funct.keys())
        vals  = list(funct.values())
        entries = []
        for i, (name, val) in enumerate(zip(names, vals)):
            if isinstance(val, tuple):
                entries.append(_from_tuple(name, val))
            elif callable(val):
                if not funct_args:
                    args_i: list = []
                elif (isinstance(funct_args, list) and len(funct_args) == len(names)
                      and all(isinstance(a, list) for a in funct_args)):
                    args_i = funct_args[i]
                else:
                    args_i = funct_args if isinstance(funct_args, list) else []
                entries.append(_from_callable_args(name, val, args_i))
            else:
                raise ValueError(
                    f"funct['{name}'] doit être callable ou tuple, reçu {type(val)}"
                )
        return entries

    raise ValueError(
        f"funct doit être un callable, un tuple ou un dict, reçu {type(funct)}"
    )


def _resolve_column_references(
    funct_list: list[tuple],
    data: pd.DataFrame,
    date_col: str | None,
    verbose: bool = False,
) -> list[tuple]:
    """Résolution des références de colonnes, comme les funct_args du R :

    - colonne positionnelle absente mais égale (insensible à la casse) au
      nom de la colonne datetime → colonne datetime (ex. "date" → "Date") ;
    - kwarg dont la valeur str correspond à un nom de colonne des données
      → la colonne est passée à la fonction, alignée sur le groupe
      (ex. lim="upLim") ; les valeurs comme "longest" ou "<=" ne matchent
      jamais une colonne et restent des kwargs statiques.
    """
    def _resolve(col: str) -> str:
        if col in data.columns:
            return col
        if date_col is not None and col.lower() == date_col.lower():
            return date_col
        raise ValueError(
            f"Colonne '{col}' introuvable dans data. "
            f"Colonnes disponibles : {list(data.columns)}"
        )

    resolved = []
    for (name, fn, col_names, kwargs, skip_na, is_date) in funct_list:
        cols = [_resolve(c) for c in col_names]

        ref_names, ref_cols = [], []
        static_kwargs = {}
        for k, v in kwargs.items():
            if isinstance(v, str):
                if v in data.columns:
                    ref_names.append(k)
                    ref_cols.append(v)
                    continue
                if date_col is not None and v.lower() == date_col.lower():
                    ref_names.append(k)
                    ref_cols.append(date_col)
                    continue
            static_kwargs[k] = v

        if ref_names:
            if verbose:
                for k, c in zip(ref_names, ref_cols):
                    print(f"  '{name}' : kwarg {k}='{c}' interprété comme "
                          f"référence à la colonne '{c}' (alignée sur le groupe)")
            n_base = len(cols)

            def wrapped(*args, _fn=fn, _n=n_base, _refs=tuple(ref_names),
                        **kw):
                kw = {**kw, **dict(zip(_refs, args[_n:]))}
                return _fn(*args[:_n], **kw)

            fn = wrapped
            cols = cols + ref_cols
            kwargs = static_kwargs
        else:
            kwargs = static_kwargs

        resolved.append((name, fn, cols, kwargs, skip_na, is_date))
    return resolved


_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]


def _apply_compress(
    result: pd.DataFrame,
    time_step: str,
    id_col: str,
    value_names: list[str],
) -> pd.DataFrame:
    """Pivot long → wide : place les étiquettes mois/saison en colonnes."""
    vn = value_names  # liste des noms de colonnes valeur présents dans result

    def _pivot(df, index_cols, col_key, val_cols):
        pt = df.pivot_table(index=index_cols, columns=col_key, values=val_cols, aggfunc="first")
        if isinstance(pt.columns, pd.MultiIndex):
            pt.columns = [f"{v}_{c}" for v, c in pt.columns]
        else:
            # Une seule valeur → préfixe = val_cols[0]
            pt.columns = [f"{val_cols[0]}_{c}" for c in pt.columns]
        return pt.reset_index()

    result = result.copy()

    if time_step == "year-month":
        result["_ref"] = [_MONTH_ABBR[m - 1] for m in result["Date"].dt.month]
        result["Date"] = result["Date"].dt.year
        out = _pivot(result, [id_col, "Date"], "_ref", vn)
        out["Date"] = pd.to_datetime(out["Date"].astype(str) + "-01-01")
        return _reorder_value_cols(out, id_col, vn, _MONTH_ABBR)

    elif time_step == "year-season":
        result["_ref"] = [s.split("-")[-1] for s in result["YearSeason"]]
        result["Date"] = result["Date"].dt.year
        result = result.drop(columns=["YearSeason"])
        out = _pivot(result, [id_col, "Date"], "_ref", vn)
        out["Date"] = pd.to_datetime(out["Date"].astype(str) + "-01-01")
        return _reorder_value_cols(out, id_col, vn, None)

    elif time_step == "season":
        result = result.drop(columns=["Date"])
        out = _pivot(result, [id_col], "Season", vn)
        return _reorder_value_cols(out, id_col, vn, None)

    elif time_step == "month":
        result["_ref"] = [_MONTH_ABBR[m - 1] for m in result["Month"]]
        result = result.drop(columns=["Date", "Month"])
        out = _pivot(result, [id_col], "_ref", vn)
        return _reorder_value_cols(out, id_col, vn, _MONTH_ABBR)

    return result


def _reorder_value_cols(
    df: pd.DataFrame,
    id_col: str,
    value_names: list[str],
    month_order: list[str] | None,
) -> pd.DataFrame:
    """Réordonne les colonnes valeur dans l'ordre naturel mois/saison."""
    struct = [c for c in df.columns if not any(
        c.startswith(v + "_") or c == v for v in value_names
    )]
    if month_order is not None:
        # Tri par position dans la liste de référence (mois ou saisons)
        def _sort_key(col):
            for v in value_names:
                if col.startswith(v + "_"):
                    suffix = col[len(v) + 1:]
                    if suffix in month_order:
                        return month_order.index(suffix)
            return 999
        val_cols = sorted(
            [c for c in df.columns if c not in struct],
            key=_sort_key,
        )
    else:
        val_cols = [c for c in df.columns if c not in struct]
    return df[struct + val_cols]


def _apply_expand(
    result,
    time_step: str,
    id_col: str,
    value_names: list[str],
    compressed: bool,
) -> dict[str, pd.DataFrame]:
    """Éclate le DataFrame en dict {name: DataFrame} — un par variable extraite."""
    if not isinstance(result, pd.DataFrame):
        return result

    struct_cols = [c for c in result.columns if not any(
        c == v or c.startswith(v + "_") for v in value_names
    )]
    out = {}
    for name in value_names:
        var_cols = [c for c in result.columns if c == name or c.startswith(name + "_")]
        out[name] = result[struct_cols + var_cols].copy()
    return out


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def process_extraction(
    data: pd.DataFrame,
    funct: Callable | dict,
    funct_args: list | None = None,
    time_step: str = "year",
    sampling_period: str | list | None = None,
    period: list | None = None,
    NApct_lim: float | None = None,
    rmNApct: bool = True,
    nameEX: str = "X",
    Seasons: list[str] | None = None,
    compress: bool = False,
    expand: bool = False,
    is_date: bool = False,
    suffix: list[str] | None = None,
    suffix_delimiter: str = "_",
    rm_duplicates: bool = False,
    keep: str | None = None,
    NAyear_lim: float | None = None,
    verbose: bool = False,
) -> pd.DataFrame | dict:
    """
    Extrait une ou plusieurs variables agrégées depuis une chronique journalière.

    Paramètres
    ----------
    data         : DataFrame avec colonne datetime, colonne str (id), colonne(s) numérique(s).
    funct        : Callable ou dict {name: callable | tuple} pour plusieurs variables.
                   Tuple : (fn, *colonnes_ou_littéraux, kwargs?, is_date?).
                   Attention à l'ambiguïté bool : un bool en DERNIÈRE position
                   est toujours is_date — (fn, "Q", True) signifie is_date=True ;
                   pour passer un littéral booléen positionnel à fn, ajoutez le
                   dict kwargs après : (fn, "Q", True, {}) → fn(Q, True).
                   Un kwarg str égal à un nom de colonne des données devient une
                   référence : la colonne, alignée sur le groupe, est passée à fn
                   (ex. {"lim": "upLim"}) ; visible avec verbose=True.
    funct_args   : DÉPRÉCIÉ — intégrer colonnes et kwargs dans funct via tuple.
    time_step    : 'year' | 'year-month' | 'month' | 'year-season' | 'season' | 'yearday' | 'none'.
    sampling_period : fenêtre 'MM-DD' ou ['MM-DD','MM-DD'], utilisée pour time_step='year'.
    period       : [date_debut, date_fin] pour restreindre la période.
    NApct_lim    : seuil de lacunes (%). Au-delà, valeur mise à NA.
    rmNApct      : supprime la/les colonne(s) NApct si True.
    nameEX       : nom de colonne de sortie (funct callable sans dict uniquement).
    Seasons      : découpage saisonnier ex. ["DJF","MAM","JJA","SON"].
    compress     : pivot long→large (mois/saisons en colonnes).
                   Disponible pour time_step 'month','year-month','season','year-season'.
    expand       : retourne un dict {name: DataFrame} au lieu d'un seul DataFrame.
    is_date      : DÉPRÉCIÉ — utiliser is_date=True dans le tuple funct.
    suffix       : liste de suffixes à appliquer par produit cartésien avec funct.
                   Ex: funct={"QA": (np.mean, "Q")}, suffix=["obs","sim"]
                   → colonnes QA_obs (sur Q_obs) et QA_sim (sur Q_sim).
                   Si la colonne de base n'est pas spécifiée dans le tuple, la première
                   colonne numérique se terminant par suffix_delimiter+suffix est utilisée.
    suffix_delimiter : délimiteur entre le nom de la variable et le suffix (défaut "_").
    rm_duplicates : si True, supprime les lignes dupliquées (même série × même date),
                   en gardant la première occurrence. Si False (défaut), lève une ValueError
                   explicite dès qu'un doublon est détecté.
    keep         : None (défaut) ou 'all'. Avec 'all', la sortie a le même nombre de lignes
                   que l'entrée : la valeur agrégée est assignée à la première ligne du groupe,
                   NaN aux autres. Toutes les colonnes d'origine sont conservées. NApct est
                   toujours supprimé. Non supporté pour month/season/yearday.
    NAyear_lim   : nombre maximal d'années consécutives manquantes autorisé. Si ce seuil est
                   dépassé pour une série, celle-ci est tronquée autour de la lacune : seule
                   la portion la plus longue (avant ou après) est conservée. Appliqué aux
                   données brutes avant agrégation. Conçu pour des données journalières.
    verbose      : messages de progression.
    """
    if not isinstance(data, pd.DataFrame):
        raise TypeError(
            f"data doit être un DataFrame pandas, reçu {type(data).__name__}."
        )

    if isinstance(sampling_period, Adaptive):
        if expand:
            raise ValueError(
                "sampling_period adaptatif incompatible avec expand=True."
            )
        _kw = dict(funct=funct, funct_args=funct_args, time_step=time_step,
                   period=period, NApct_lim=NApct_lim, rmNApct=rmNApct,
                   nameEX=nameEX, Seasons=Seasons, compress=compress,
                   expand=expand, is_date=is_date, suffix=suffix,
                   suffix_delimiter=suffix_delimiter,
                   rm_duplicates=rm_duplicates, keep=keep,
                   NAyear_lim=NAyear_lim, verbose=verbose)
        return _process_adaptive(data, sampling_period, _kw)

    VALID = {"year", "year-month", "month", "year-season", "season", "yearday", "none"}
    if time_step not in VALID:
        raise ValueError(
            f"time_step='{time_step}' invalide. "
            f"Valeurs acceptées : {sorted(VALID)}."
        )

    if funct_args is not None:
        warnings.warn(
            "funct_args est déprécié. Intégrez colonnes et kwargs dans funct : "
            "funct=(fn, 'col', {kwargs}) ou funct={'name': (fn, 'col', {kwargs})}.",
            FutureWarning, stacklevel=2,
        )
    if is_date:
        warnings.warn(
            "Le paramètre is_date est déprécié. "
            "Utilisez is_date=True dans le tuple : funct=(np.argmax, 'col', True) "
            "ou funct={'name': (np.argmax, 'col', True)}.",
            FutureWarning, stacklevel=2,
        )

    if NApct_lim is not None:
        if not isinstance(NApct_lim, (int, float)) or not (0.0 <= NApct_lim <= 100.0):
            raise ValueError(
                f"NApct_lim={NApct_lim!r} invalide : doit être un nombre entre 0 et 100."
            )

    if sampling_period is not None and time_step not in {"year", "none"}:
        warnings.warn(
            f"sampling_period ignoré pour time_step='{time_step}'. "
            "Ce paramètre n'est pris en compte que pour time_step='year' ou 'none'."
        )

    if period is not None:
        if not hasattr(period, "__len__") or len(period) != 2:
            raise ValueError(
                f"period doit être [date_début, date_fin] (2 éléments), "
                f"reçu {period!r}."
            )
        try:
            _p0, _p1 = pd.Timestamp(period[0]), pd.Timestamp(period[1])
        except Exception as _exc:
            raise ValueError(
                f"period invalide — impossible de convertir en dates : {_exc}"
            ) from _exc
        if _p0 > _p1:
            raise ValueError(
                f"period invalide : date_début ({_p0.date()}) > date_fin ({_p1.date()}). "
                "Inversez les deux bornes."
            )

    if Seasons is None:
        Seasons = ["DJF", "MAM", "JJA", "SON"]

    _total_season_months = sum(len(s) for s in Seasons)
    if _total_season_months != 12:
        raise ValueError(
            f"Seasons invalide : la somme des longueurs doit être 12 "
            f"(un caractère par mois), reçu {Seasons!r} (total={_total_season_months})."
        )

    if is_date and time_step != "year":
        warnings.warn("is_date=True ignoré : disponible uniquement pour time_step='year'.")
        is_date = False

    if compress and time_step not in {"month", "year-month", "season", "year-season"}:
        warnings.warn("compress=True ignoré : disponible uniquement pour month/year-month/season/year-season.")
        compress = False

    if compress and expand and time_step in {"year-month", "year-season"}:
        warnings.warn("compress=False : compress et expand ne peuvent être tous les deux True pour year-month/year-season.")
        compress = False

    # keep peut être une liste de colonnes à conserver en sortie
    # (sélection finale, sans fan-out — équivalent R keep=c("QJC10"))
    keep_cols: list | None = None
    if isinstance(keep, (list, tuple)):
        keep_cols = [str(c) for c in keep]
        keep = None

    if keep is not None:
        if keep != "all":
            raise ValueError(
                f"keep='{keep}' invalide. Valeurs acceptées : None, 'all' "
                "ou une liste de noms de colonnes."
            )
        if time_step in {"month", "season", "yearday"}:
            warnings.warn(
                f"keep='all' ignoré : non supporté pour time_step='{time_step}'. "
                "Disponible uniquement pour year, year-month, year-season, none."
            )
            keep = None
        else:
            if compress:
                warnings.warn("compress=True ignoré : non compatible avec keep='all'.")
                compress = False
            if expand:
                warnings.warn("expand=True ignoré : non compatible avec keep='all'.")
                expand = False

    if NAyear_lim is not None:
        if not isinstance(NAyear_lim, (int, float)) or NAyear_lim <= 0:
            raise ValueError("NAyear_lim doit être un nombre strictement positif.")

    if len(data) == 0:
        # Retour vide typé (meilleur effort) : colonnes attendues de la
        # sortie standard. Chemins non définissables sans données
        # (compress, expand, keep='all') → DataFrame nu.
        if compress or expand or keep == "all":
            return pd.DataFrame()
        try:
            _, _id, _ = _detect_columns(data)
            _names = [n for (n, *_) in
                      _normalize_funct(funct, funct_args, nameEX,
                                       is_date_global=is_date)]
            if suffix:
                _d = suffix_delimiter or "_"
                _names = [f"{n}{_d}{s}" for n in _names for s in suffix]
            return _empty_extraction_frame(_id if _id is not None else "ID",
                                           time_step, _names, rmNApct)
        except Exception:
            return pd.DataFrame()

    data = data.copy()

    # --- Noms de colonnes dupliqués ---
    seen_cols: set = set()
    dup_col_names = [c for c in data.columns if c in seen_cols or seen_cols.add(c)]  # type: ignore[func-returns-value]
    if dup_col_names:
        raise ValueError(
            f"data contient des colonnes avec noms dupliqués : "
            f"{list(dict.fromkeys(dup_col_names))}. "
            "Renommez-les avant d'appeler process_extraction."
        )

    date_col, id_col, value_cols = _detect_columns(data)

    # --- Colonne date stockée comme string ? ---
    if date_col is None:
        for _col in data.columns:
            if pd.api.types.is_string_dtype(data[_col]) or data[_col].dtype == object:
                _sample = data[_col].dropna().head(5)
                if len(_sample) == 0:
                    continue
                try:
                    pd.to_datetime(_sample)
                    warnings.warn(
                        f"La colonne '{_col}' (type '{data[_col].dtype}') ressemble à des "
                        f"dates (ex: {_sample.iloc[0]!r}) mais n'est pas de type datetime. "
                        f"Convertissez-la : data['{_col}'] = pd.to_datetime(data['{_col}'])",
                        UserWarning, stacklevel=2,
                    )
                    break
                except Exception:
                    pass

    # --- Colonne date requise ---
    if date_col is None and time_step != "none":
        raise ValueError(
            f"Aucune colonne datetime trouvée dans data, requise pour "
            f"time_step='{time_step}'. "
            f"Colonnes disponibles : {list(data.columns)}. "
            "Convertissez votre colonne de dates : "
            "data['Date'] = pd.to_datetime(data['Date'])."
        )

    if id_col is None:
        data["_id"] = "time serie"
        id_col = "_id"

    # Convertir la colonne ID en Categorical si nécessaire — accélère groupby + tri
    if not isinstance(data[id_col].dtype, pd.CategoricalDtype):
        data[id_col] = data[id_col].astype("category")

    # Tri (id, date) dès maintenant : requis par l'extraction de toute
    # façon (les filtres en aval préservent l'ordre), et il rend le
    # contrôle des doublons vectoriel — comparaison de voisins au lieu
    # d'un hachage complet du tableau (~2× moins cher au total).
    # Le tri multi-clés pandas est stable : « première occurrence » garde
    # le même sens qu'avant pour rm_duplicates.
    data = (data.sort_values([id_col] + ([date_col] if date_col else []))
            .reset_index(drop=True))

    # --- Dates dupliquées (données triées : doublons adjacents) ---
    if date_col is not None:
        _ids_c = data[id_col].cat.codes.to_numpy()
        _dts_i = data[date_col].to_numpy().view("i8")
        _same = (_ids_c[1:] == _ids_c[:-1]) & (_dts_i[1:] == _dts_i[:-1])
        if _same.any():
            # True = doublon de la ligne précédente
            dup_prev = np.concatenate([[False], _same])
            if rm_duplicates:
                data = data[~dup_prev]
            else:
                # dup_any = toutes les lignes impliquées (y c. la première
                # de chaque groupe), comme duplicated(keep=False)
                dup_any = dup_prev | np.concatenate([_same, [False]])
                n_dup = int(dup_any.sum())
                sample = (
                    data[dup_any]
                    .groupby([id_col, date_col], sort=False, observed=True)
                    .size()
                    .reset_index(name="n")
                    .head(5)
                )
                hint = ""
                if id_col == "_id":
                    hint = (
                        "\nAucune colonne texte n'a été détectée comme "
                        "identifiant de série : toutes les lignes sont "
                        "traitées comme une seule série, ce qui peut "
                        "expliquer ces doublons. Si une de vos colonnes "
                        "numériques identifie vos séries, convertissez-la "
                        "en texte : data['code'] = data['code'].astype(str)."
                    )
                raise ValueError(
                    f"{n_dup} lignes avec dates dupliquées (série × date). "
                    f"Premiers cas :\n{sample.to_string(index=False)}\n"
                    "Utilisez rm_duplicates=True pour supprimer automatiquement "
                    "(première occurrence conservée)." + hint
                )

    # Normalise funct en liste de (name, callable, col_names, kwargs, skip_na, is_date)
    funct_list = _normalize_funct(funct, funct_args, nameEX, is_date_global=is_date)

    # --- Expansion suffix (produit cartésien funct × suffix) ---
    if suffix:
        delim = suffix_delimiter or "_"
        expanded = []
        for (var_name, fn, col_names, funct_kwargs, skip_na, var_is_date) in funct_list:
            for s in suffix:
                full_s = f"{delim}{s}"
                new_name = f"{var_name}{full_s}"
                if col_names:
                    new_col_names = [f"{c}{full_s}" for c in col_names]
                else:
                    # Auto-détection : colonne numérique se terminant par full_s
                    matches = [c for c in value_cols if c.endswith(full_s)]
                    if len(matches) == 0:
                        raise ValueError(
                            f"suffix='{s}' : aucune colonne numérique ne se termine par "
                            f"'{full_s}'. Colonnes disponibles : {value_cols}. "
                            "Spécifiez la colonne de base : funct={'nom': (fn, 'col', ...)}."
                        )
                    if len(matches) > 1:
                        raise ValueError(
                            f"suffix='{s}' : colonnes ambiguës se terminant par "
                            f"'{full_s}': {matches}. "
                            "Spécifiez la colonne de base dans le tuple funct."
                        )
                    new_col_names = matches
                expanded.append((new_name, fn, new_col_names, funct_kwargs, skip_na, var_is_date))
        funct_list = expanded

    # Résolution des références de colonnes (kwargs-colonnes, alias date)
    funct_list = _resolve_column_references(funct_list, data, date_col,
                                            verbose=verbose)

    # Compaction des colonnes creuses issues d'un fan-out keep='all' d'un
    # appel précédent (cf. _SPARSE_ATTR) — uniquement si toutes les
    # colonnes utilisées sont creuses et qu'on ne refait pas de fan-out
    sparse_in = set(data.attrs.get(_SPARSE_ATTR, []))
    if sparse_in and keep != "all":
        used_values = {c for (_, _, cols, _, _, _) in funct_list
                       for c in cols if c != date_col}
        if used_values and used_values <= sparse_in:
            data = data.dropna(subset=sorted(used_values), how="all")

    # --- NAyear_lim : troncature des séries avec lacunes annuelles consécutives trop longues ---
    if NAyear_lim is not None and date_col is not None:
        data = _apply_nayear_lim(data, id_col, date_col, value_cols, NAyear_lim)

    # --- Filtre period ---
    if period is not None and date_col is not None:
        p0, p1 = pd.Timestamp(period[0]), pd.Timestamp(period[1])
        _d_min = data[date_col].min()
        _d_max = data[date_col].max()
        data = data[(data[date_col] >= p0) & (data[date_col] <= p1)]
        if len(data) == 0:
            warnings.warn(
                f"Aucune donnée dans la période spécifiée [{p0.date()} → {p1.date()}]. "
                f"Plage des données : {_d_min.date()} → {_d_max.date()}."
            )
            if compress or expand or keep == "all":
                return pd.DataFrame()
            return _empty_extraction_frame(
                "ID" if id_col == "_id" else id_col, time_step,
                [n for (n, *_) in funct_list], rmNApct,
            )

    # (données déjà triées en amont ; period/NAyear préservent l'ordre)
    data = data.reset_index(drop=True)

    # Détection de la résolution temporelle de l'entrée pour adapter NApct
    resolution = _detect_resolution(data, date_col, id_col) if date_col else "day"

    # Snapshot avant que les _extract_* ajoutent des colonnes internes (_hy, _ym…)
    data_for_keep = data.copy() if keep == "all" else None

    # --- Verbose header ---
    if verbose:
        _var_names_str = [n for (n, *_) in funct_list]
        _sp_s, _sp_e = _resolve_sampling_period(sampling_period)
        _rows: list[str] = []
        _ts_line = f"time_step  {time_step}"
        if (_sp_s, _sp_e) != ("01-01", "12-31") and time_step in {"year", "none"}:
            _ts_line += f"     sampling  {_sp_s} → {_sp_e}"
        _rows.append(_ts_line)
        if date_col is not None:
            _dmin = data[date_col].min().date()
            _dmax = data[date_col].max().date()
            _n_days = (data[date_col].max() - data[date_col].min()).days + 1
            _rows.append(f"période    {_dmin} → {_dmax}  [{_n_days:,} j]")
        _ids = data[id_col].unique()
        _ns = len(_ids)
        _preview = ", ".join(str(s) for s in _ids[:3])
        if _ns > 3:
            _preview += f", … (+{_ns - 3})"
        _rows.append(f"séries     {_ns}  ({_preview})")
        _rows.append(f"variables  {', '.join(_var_names_str)}")
        _verbose_box("process_extraction", _rows)

    # --- Extraction une fois par fonction ---
    results: list[tuple[str, pd.DataFrame]] = []
    _verbose_stats: list[tuple[str, int, float, float, int]] = []  # (name, n_gr, mean, max, n_fil)
    _n_vars = len(funct_list)
    for _var_idx, (var_name, fn, col_names, funct_kwargs, skip_na, var_is_date) in enumerate(funct_list):
        # Résolution de la colonne source
        if not col_names:
            col_name = value_cols[0]
        elif len(col_names) == 1:
            col_name = col_names[0]
            if col_name not in data.columns:
                raise ValueError(
                    f"Variable '{var_name}' : colonne '{col_name}' introuvable dans data. "
                    f"Colonnes numériques disponibles : {value_cols}."
                )
        else:
            for c in col_names:
                if c not in data.columns:
                    raise ValueError(
                        f"Variable '{var_name}' : colonne '{c}' introuvable dans data. "
                        f"Colonnes numériques disponibles : {value_cols}."
                    )
            col_name = col_names  # list[str] passé tel quel à _groupby_agg

        if var_is_date and time_step != "year":
            warnings.warn(
                f"is_date=True ignoré pour '{var_name}' : "
                "disponible uniquement pour time_step='year'."
            )
            var_is_date = False

        kw = dict(
            data=data, id_col=id_col, date_col=date_col, col_name=col_name,
            funct=fn, funct_kwargs=funct_kwargs, skip_na=skip_na,
            NApct_lim=NApct_lim, rmNApct=False,
            nameEX=var_name, resolution=resolution,
        )
        if time_step == "year":
            res = _extract_year(**kw, sampling_period=sampling_period, verbose=False,
                                is_date=var_is_date)
        elif time_step == "year-month":
            res = _extract_year_month(**kw)
        elif time_step == "month":
            res = _extract_month(**kw)
        elif time_step == "year-season":
            res = _extract_year_season(**kw, seasons=Seasons)
        elif time_step == "season":
            res = _extract_season(**kw, seasons=Seasons)
        elif time_step == "yearday":
            res = _extract_yearday(**kw)
        elif time_step == "none":
            res = _extract_none(**kw, sampling_period=sampling_period)
        results.append((var_name, res))

        # Verbose per-variable progress
        if verbose:
            _n_gr = len(res)
            if "NApct" in res.columns and _n_gr > 0:
                _na = res["NApct"].dropna()
                _mean_na = float(_na.mean()) if len(_na) > 0 else 0.0
                _max_na  = float(_na.max())  if len(_na) > 0 else 0.0
                _n_fil   = int((_na > NApct_lim).sum()) if NApct_lim is not None else 0
                _verbose_stats.append((var_name, _n_gr, _mean_na, _max_na, _n_fil))
                _pref = f"[{_var_idx+1}/{_n_vars}]" if _n_vars > 1 else "   "
                _na_str = f"NApct  moy={_mean_na:.1f}%  max={_max_na:.1f}%"
                _fil_str = f"  [{_n_fil} filtrés]" if NApct_lim is not None else ""
                print(f"  {_pref} {var_name:<14} {_n_gr:>4} groupes   {_na_str}{_fil_str}")
            else:
                print(f"  [{_var_idx+1}/{_n_vars}] {var_name}   {_n_gr} groupes")

    # --- Jointure des résultats ---
    var_names = [n for n, _ in results]
    if len(results) == 1:
        result = results[0][1]
        if rmNApct:
            result = result.drop(columns=["NApct"], errors="ignore")
    else:
        key_cols = [id_col] + [c for c in _STRUCT_COLS.get(time_step, [])
                               if c in results[0][1].columns]
        # sorties vectorielles de time_step 'none' : jointure aussi sur la
        # colonne date (transform) ou le rang (ragged)
        for extra in (date_col, "_rank"):
            if extra and all(extra in r.columns for _, r in results):
                key_cols.append(extra)
        # Renomme NApct en NApct_{name} pour chaque résultat
        result = results[0][1].rename(columns={"NApct": f"NApct_{results[0][0]}"})
        for var_name, res_i in results[1:]:
            merge_on = [c for c in key_cols if c in result.columns and c in res_i.columns]
            result = result.merge(
                res_i.rename(columns={"NApct": f"NApct_{var_name}"}),
                on=merge_on, how="outer",
            )
        if rmNApct:
            napct_cols = [c for c in result.columns if c.startswith("NApct_")]
            result = result.drop(columns=napct_cols)

    # --- Verbose footer ---
    if verbose and _verbose_stats:
        _all_means = [s[2] for s in _verbose_stats]
        _all_maxes = [s[3] for s in _verbose_stats]
        _total_fil = sum(s[4] for s in _verbose_stats)
        _n_out = len(result)
        _nv = len(var_names)
        _footer = f"✓ {_n_out} lignes"
        if _nv > 1:
            _footer += f"  ·  {_nv} variables"
        if _all_means:
            _footer += (f"  ·  NApct combinée  "
                        f"moy={sum(_all_means)/_nv:.1f}%  "
                        f"max={max(_all_maxes):.1f}%")
            if NApct_lim is not None:
                _footer += f"  [{_total_fil} filtrés]"
        print(f"  {_footer}")

    # --- Renommage id fictif ---
    if id_col == "_id" and "_id" in result.columns:
        result = result.rename(columns={"_id": "ID"})
        if data_for_keep is not None and "_id" in data_for_keep.columns:
            data_for_keep = data_for_keep.rename(columns={"_id": "ID"})
        id_col = "ID"

    # --- keep="all" : fan-out vers le nombre de lignes d'origine ---
    if keep == "all" and data_for_keep is not None:
        result = _apply_keep_all(
            data_for_keep=data_for_keep,
            data_with_keys=data,
            result=result,
            time_step=time_step,
            id_col=id_col,
            date_col=date_col,
            var_names=var_names,
            sampling_period=sampling_period,
        )

    # --- Compress ---
    if compress:
        result = _apply_compress(result, time_step, id_col, var_names)

    # --- Expand ---
    if expand:
        result = _apply_expand(result, time_step, id_col, var_names, compress)

    if isinstance(result, pd.DataFrame):
        # marqueur interne + index de travail : ne pas exposer
        result.attrs.pop(_ALIGNED_ATTR, None)
        if not result.index.equals(pd.RangeIndex(len(result))):
            result = result.reset_index(drop=True)

        # rang interne des sorties ragged : purement technique
        if "_rank" in result.columns:
            result = result.drop(columns=["_rank"])

        # keep=[colonnes] : sélection finale
        if keep_cols is not None:
            struct = [c for c in result.columns
                      if c == id_col
                      or c in ("Date", "Month", "Season", "YearSeason", "Yearday")
                      or (date_col is not None and c == date_col)]
            result = result[struct
                            + [c for c in keep_cols if c in result.columns]]

        # marquage des colonnes creuses produites par le fan-out keep='all'
        # (time_step 'none' diffuse/aligne les valeurs : sortie dense)
        if keep == "all":
            out_sparse = set(sparse_in)
            if time_step != "none":
                out_sparse |= set(var_names)
            if out_sparse:
                result.attrs[_SPARSE_ATTR] = sorted(out_sparse)

    return result


# ---------------------------------------------------------------------------
# NAyear_lim — troncature des séries avec lacunes consécutives trop longues
# ---------------------------------------------------------------------------

def _missing_year_hide(values: np.ndarray, dates: np.ndarray, nayear_lim: float) -> np.ndarray:
    """
    Pour une série triée (dates, valeurs), masque la portion la plus courte
    autour de tout bloc de NaN continus ≥ nayear_lim années.
    Fidèle à R missing_year_hide() : détection par diff des dates NA (=1 jour
    pour des dates quotidiennes consécutives).
    """
    values = values.copy().astype(float)
    na_mask = np.isnan(values)
    na_dates = dates[na_mask]

    if len(na_dates) == 0:
        return values

    # Différences entre dates NA consécutives (en jours entiers)
    d_na = np.diff(na_dates.astype("datetime64[D]").astype(np.int64))
    d_na = np.concatenate([[10], d_na])   # premier élément toujours "saut"

    jump_idx = np.where(d_na != 1)[0]   # débuts de blocs contigus
    n_jump = len(jump_idx)

    start_all = dates.min()
    end_all   = dates.max()

    for i in range(n_jump):
        id_s = jump_idx[i]
        id_e = jump_idx[i + 1] - 1 if i < n_jump - 1 else len(na_dates) - 1

        start_na = na_dates[id_s]
        end_na   = na_dates[id_e]

        duration = float((end_na - start_na) / np.timedelta64(1, "D")) / 365.25

        if duration >= nayear_lim:
            before = float((start_na - start_all) / np.timedelta64(1, "D"))
            after  = float((end_all  - end_na)    / np.timedelta64(1, "D"))
            if before < after:
                values[dates <= start_na] = np.nan
            else:
                values[dates >= end_na] = np.nan

    return values


def _apply_nayear_lim(data: pd.DataFrame, id_col: str, date_col: str,
                      value_cols: list[str], nayear_lim: float) -> pd.DataFrame:
    """Applique _missing_year_hide par (série, variable) sur les données brutes."""
    data = data.copy()
    for _, grp in data.groupby(id_col, sort=False, observed=True):
        grp_s = grp.sort_values(date_col)
        dates_np = grp_s[date_col].to_numpy()
        idx = grp_s.index
        for col in value_cols:
            if col not in data.columns:
                continue
            new_vals = _missing_year_hide(
                grp_s[col].to_numpy().astype(float), dates_np, nayear_lim
            )
            data.loc[idx, col] = new_vals
    return data


# ---------------------------------------------------------------------------
# keep="all" — fan-out vers lignes d'origine
# ---------------------------------------------------------------------------

def _apply_keep_all(data_for_keep, data_with_keys, result, time_step, id_col,
                    date_col, var_names, sampling_period):
    """
    Étend le résultat agrégé (1 ligne/groupe) au nombre de lignes d'origine.
    La valeur agrégée est placée sur la première ligne de chaque groupe ; les
    autres lignes reçoivent NaN. Pour time_step='none', toutes les lignes du
    groupe (= la série entière) reçoivent la valeur. NApct toujours supprimé.
    """
    agg_cols = var_names

    if time_step == "none":
        if date_col is not None and date_col in result.columns:
            if result.attrs.get(_ALIGNED_ATTR) and result.index.is_unique:
                # sortie transform à index préservé : assignation alignée
                # sur l'index (O(N)), pas de merge 5M×5M
                base = data_for_keep.copy()
                for col in agg_cols:
                    base[col] = result[col]
                return base
            # repli : jointure alignée sur (id, date)
            base = data_for_keep.merge(
                result[[id_col, date_col] + agg_cols],
                on=[id_col, date_col],
                how="left",
            )
        else:
            # sortie scalaire : toutes les lignes de chaque ID reçoivent
            # la valeur agrégée — map (clés uniques) plutôt que merge
            base = data_for_keep.copy()
            for col in agg_cols:
                mapping = pd.Series(result[col].to_numpy(),
                                    index=result[id_col].to_numpy())
                base[col] = base[id_col].map(mapping)
        return base

    # Calcul de la date représentative du groupe pour chaque ligne
    if time_step == "year":
        sp_start, _ = _resolve_sampling_period(sampling_period)
        mS, dS = _parse_mmdd(sp_start)
        hy_col = data_with_keys.get("_hy") if hasattr(data_with_keys, "get") else data_with_keys["_hy"]
        group_date = pd.array(
            [_safe_date(int(hy), mS, dS) if pd.notna(hy) else pd.NaT
             for hy in hy_col],
            dtype="datetime64[ns]",
        )

    elif time_step == "year-month":
        ym_col = data_with_keys["_ym"]
        group_date = pd.array(
            [pd.Timestamp(year=p.year, month=p.month, day=1) if not pd.isna(p) else pd.NaT
             for p in ym_col],
            dtype="datetime64[ns]",
        )

    elif time_step == "year-season":
        sym_col = data_with_keys["_season_ym"]
        group_date = pd.array(
            [pd.Timestamp(year=int(s[:4]), month=int(s[5:]), day=1) if not pd.isna(s) else pd.NaT
             for s in sym_col],
            dtype="datetime64[ns]",
        )

    else:
        return data_for_keep  # ne devrait pas arriver

    # Prépare le résultat pour la jointure
    result_m = result[[id_col, "Date"] + agg_cols].copy()
    result_m = result_m.rename(columns={"Date": "_group_date"})

    base = data_for_keep.copy()
    base["_group_date"] = group_date

    base = base.merge(result_m, on=[id_col, "_group_date"], how="left")

    # Première ligne de chaque (id, groupe) garde la valeur ; les autres → NaN
    is_first = ~base.duplicated(subset=[id_col, "_group_date"], keep="first")
    for col in agg_cols:
        if col in base.columns:
            base.loc[~is_first, col] = np.nan

    base = base.drop(columns=["_group_date"])
    return base


# ---------------------------------------------------------------------------
# time_step = "year"
# ---------------------------------------------------------------------------

def _extract_year(data, id_col, date_col, col_name, funct, funct_kwargs, skip_na,
                  NApct_lim, rmNApct, nameEX, sampling_period, verbose, resolution="day",
                  is_date=False):
    sp_start, sp_end = _resolve_sampling_period(sampling_period)
    ref_year = 1972
    ref_start = pd.Timestamp(f"{ref_year}-{sp_start}")
    ref_end   = pd.Timestamp(f"{ref_year}-{sp_end}")
    dt2add    = 1 if ref_start > ref_end else 0

    # _hy calculé une seule fois par appel : les variables suivantes du
    # multi-funct réutilisent la colonne (même sampling_period pour toutes)
    if "_hy" not in data.columns:
        data["_hy"] = _assign_hydro_year(data[date_col], sp_start, sp_end, dt2add)
    data = data.dropna(subset=["_hy"])
    data["_hy"] = data["_hy"].astype(np.int32)

    if len(data) == 0:
        warnings.warn("Aucune donnée dans la fenêtre d'échantillonnage.")
        return _empty_extraction_frame(id_col, "year", [nameEX], rmNApct)

    ext = _groupby_agg(data, [id_col, "_hy"], col_name, funct, funct_kwargs, skip_na)

    if is_date:
        ext = _apply_is_date(ext, data, id_col, date_col)

    # NApct : dénominateur adapté à la résolution de l'entrée
    hy_arr = ext["_hy"].to_numpy()
    if resolution == "day":
        # Cache par année unique : évite ~14k appels _safe_date répétés
        _hy_int = hy_arr.astype(int)
        _ndays_cache = {y: _window_ndays(y, sp_start, sp_end, dt2add)
                        for y in np.unique(_hy_int)}
        n_expected = np.array([_ndays_cache[y] for y in _hy_int], dtype=np.int64)
    else:
        nm = _window_nmonths(sp_start, sp_end, dt2add)
        if resolution == "month":
            n_expected = np.full(len(hy_arr), nm, dtype=np.int64)
        elif resolution == "season":
            n_expected = np.full(len(hy_arr), max(1, round(nm / 3)), dtype=np.int64)
        else:   # "year"
            n_expected = np.ones(len(hy_arr), dtype=np.int64)
    ext["NApct"] = _napct_vec(ext["_nPresent"].to_numpy(), ext["_nNA"].to_numpy(), n_expected)

    if NApct_lim is not None:
        ext.loc[ext["NApct"] > NApct_lim, "_value"] = np.nan

    mS, dS = _parse_mmdd(sp_start)
    # Cache les Timestamps par année unique (évite ~14k pd.Timestamp() répétés)
    _hy_int = hy_arr.astype(int)
    _date_cache = {y: _safe_date(y, mS, dS) for y in np.unique(_hy_int)}
    ext["Date"] = [_date_cache[y] for y in _hy_int]
    ext = ext.rename(columns={"_value": nameEX})

    cols = [id_col, "Date", nameEX] + ([] if rmNApct else ["NApct"])
    return ext[cols].sort_values([id_col, "Date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# time_step = "year-month"
# ---------------------------------------------------------------------------

def _extract_year_month(data, id_col, date_col, col_name, funct, funct_kwargs, skip_na,
                         NApct_lim, rmNApct, nameEX, resolution="day"):
    if "_ym" not in data.columns:
        data["_ym"] = data[date_col].dt.to_period("M")

    ext = _groupby_agg(data, [id_col, "_ym"], col_name, funct, funct_kwargs, skip_na)

    ym_arr = ext["_ym"].to_numpy()
    if resolution == "day":
        n_expected = np.array([calendar.monthrange(p.year, p.month)[1] for p in ym_arr])
    else:
        n_expected = np.ones(len(ym_arr), dtype=np.int64)
    ext["NApct"] = _napct_vec(ext["_nPresent"].to_numpy(), ext["_nNA"].to_numpy(), n_expected)

    if NApct_lim is not None:
        ext.loc[ext["NApct"] > NApct_lim, "_value"] = np.nan

    ext["Date"] = [pd.Timestamp(year=p.year, month=p.month, day=1) for p in ym_arr]
    ext = ext.rename(columns={"_value": nameEX})

    cols = [id_col, "Date", nameEX] + ([] if rmNApct else ["NApct"])
    return ext[cols].sort_values([id_col, "Date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# time_step = "month"
# ---------------------------------------------------------------------------

def _extract_month(data, id_col, date_col, col_name, funct, funct_kwargs, skip_na,
                    NApct_lim, rmNApct, nameEX, resolution="day"):
    if "_month" not in data.columns:
        data["_month"] = data[date_col].dt.month.astype(np.int8)

    ext = _groupby_agg(data, [id_col, "_month"], col_name, funct, funct_kwargs, skip_na)

    yr = data.groupby(id_col, observed=True)[date_col].agg(
        _min_year=lambda s: s.dt.year.min(),
        _nyears=lambda s: s.dt.year.max() - s.dt.year.min() + 1,
    )
    ext = ext.join(yr, on=id_col)

    m_arr  = ext["_month"].to_numpy()
    my_arr = ext["_min_year"].to_numpy()
    ny_arr = ext["_nyears"].to_numpy()
    if resolution == "day":
        vfunc = np.vectorize(
            lambda m, my, ny: sum(calendar.monthrange(my + k, m)[1] for k in range(ny))
        )
        n_expected = vfunc(m_arr, my_arr, ny_arr)
    else:
        # Non-journalier : une entrée attendue par unité temporelle par année
        n_expected = ny_arr.astype(np.int64)
    ext["NApct"] = _napct_vec(ext["_nPresent"].to_numpy(), ext["_nNA"].to_numpy(), n_expected)

    if NApct_lim is not None:
        ext.loc[ext["NApct"] > NApct_lim, "_value"] = np.nan

    ext["Date"] = [pd.Timestamp(year=int(my), month=int(m), day=1)
                   for my, m in zip(my_arr, m_arr)]
    ext = ext.rename(columns={"_value": nameEX, "_month": "Month"})

    cols = [id_col, "Date", "Month", nameEX] + ([] if rmNApct else ["NApct"])
    return ext[cols].sort_values([id_col, "Date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# time_step = "year-season"
# ---------------------------------------------------------------------------

def _extract_year_season(data, id_col, date_col, col_name, funct, funct_kwargs, skip_na,
                          NApct_lim, rmNApct, nameEX, seasons, resolution="day"):
    get_season, sub_seasons = _build_season_map(seasons)
    sub_np = np.array(sub_seasons, dtype=np.int64)

    # Clés calculées une seule fois par appel (multi-funct : réutilisées)
    if "_season_ym" not in data.columns:
        # Mapping vectorisé : indexage numpy (zéro boucle Python sur les lignes)
        month_arr = data[date_col].dt.month.to_numpy()   # (N,) int64
        year_arr  = data[date_col].dt.year.to_numpy()    # (N,) int64
        get_season_np = np.array(get_season)

        sub_vals    = sub_np[month_arr - 1]              # vectorisé
        season_name = get_season_np[month_arr - 1]       # vectorisé

        raw      = month_arr.astype(np.int64) - 1 - sub_vals
        season_m = (raw % 12 + 1).astype(np.int64)
        season_y = year_arr + raw // 12

        # Clé groupe : liste python rapide (formatage compact)
        data["_season_ym"]   = [f"{y}-{m:02d}" for y, m in zip(season_y.tolist(), season_m.tolist())]
        data["_season_name"] = season_name

    ext = _groupby_agg(data, [id_col, "_season_ym"], col_name, funct, funct_kwargs, skip_na)

    # Récupère le nom de la saison depuis les données (déjà groupées)
    sname_map = (
        data[[id_col, "_season_ym", "_season_name"]]
        .drop_duplicates([id_col, "_season_ym"])
    )
    ext = ext.merge(sname_map, on=[id_col, "_season_ym"], how="left")

    ym_arr_ext = ext["_season_ym"].to_numpy()
    sname_arr  = ext["_season_name"].to_numpy()
    slen_map   = {s: len(s) for s in seasons}
    slen_arr   = np.array([slen_map.get(s, 3) for s in sname_arr])
    if resolution == "day":
        sy_arr = np.array([int(s[:4]) for s in ym_arr_ext])
        sm_arr = np.array([int(s[5:]) for s in ym_arr_ext])
        vfunc = np.vectorize(_season_ndays)
        n_expected = vfunc(sy_arr, sm_arr, slen_arr)
    elif resolution == "month":
        n_expected = slen_arr.astype(np.int64)
    else:   # "season" ou "year"
        n_expected = np.ones(len(sname_arr), dtype=np.int64)
    ext["NApct"] = _napct_vec(ext["_nPresent"].to_numpy(), ext["_nNA"].to_numpy(), n_expected)

    if NApct_lim is not None:
        ext.loc[ext["NApct"] > NApct_lim, "_value"] = np.nan

    _dcache = {s: pd.Timestamp(year=int(s[:4]), month=int(s[5:]), day=1)
               for s in set(ym_arr_ext)}
    ext["Date"] = [_dcache[s] for s in ym_arr_ext]
    ext["YearSeason"] = [f"{s[:4]}-{n}" for s, n in zip(ym_arr_ext, sname_arr)]
    ext = ext.rename(columns={"_value": nameEX})

    cols = [id_col, "Date", nameEX, "YearSeason"] + ([] if rmNApct else ["NApct"])
    return ext[cols].sort_values([id_col, "Date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# time_step = "season"
# ---------------------------------------------------------------------------

def _extract_season(data, id_col, date_col, col_name, funct, funct_kwargs, skip_na,
                     NApct_lim, rmNApct, nameEX, seasons, resolution="day"):
    get_season, sub_seasons = _build_season_map(seasons)
    sub_np = np.array(sub_seasons, dtype=np.int64)

    if "_season_name" not in data.columns or "_season_sm" not in data.columns:
        month_arr = data[date_col].dt.month.to_numpy()
        get_season_np = np.array(get_season)

        sub_vals    = sub_np[month_arr - 1]
        season_name = get_season_np[month_arr - 1]

        raw      = month_arr.astype(np.int64) - 1 - sub_vals
        season_m = (raw % 12 + 1).astype(np.int64)   # mois de début de saison (1-12)

        data["_season_name"] = season_name
        data["_season_sm"]   = season_m.astype(np.int8)

    ext = _groupby_agg(data, [id_col, "_season_name"], col_name, funct, funct_kwargs, skip_na)

    # Mois de début de saison par groupe
    sm_map = (data[[id_col, "_season_name", "_season_sm"]]
              .drop_duplicates([id_col, "_season_name"]))
    ext = ext.merge(sm_map, on=[id_col, "_season_name"], how="left")

    # year_ref = year(minSampleStart) — même logique que R
    # minSampleStart = premier jour de la saison contenant la première date de la série
    min_dates = data.groupby(id_col, observed=True)[date_col].min()
    mm_min = min_dates.dt.month.to_numpy()
    yy_min = min_dates.dt.year.to_numpy()
    sub_min = sub_np[mm_min - 1]
    raw_min = mm_min.astype(np.int64) - 1 - sub_min
    year_ref = yy_min + raw_min // 12
    year_ref_s = pd.Series(year_ref, index=min_dates.index, name="_year_ref")

    # Statistiques par id pour NApct
    yr = data.groupby(id_col, observed=True)[date_col].agg(
        _min_year=lambda s: s.dt.year.min(),
        _nyears=lambda s: s.dt.year.max() - s.dt.year.min() + 1,
    )
    ext = ext.join(yr, on=id_col).join(year_ref_s, on=id_col)

    slen_map  = {s: len(s) for s in seasons}
    sm_arr    = ext["_season_sm"].to_numpy()
    sname_arr = ext["_season_name"].to_numpy()
    slen_arr  = np.array([slen_map.get(s, 3) for s in sname_arr])
    my_arr    = ext["_min_year"].to_numpy()
    ny_arr    = ext["_nyears"].to_numpy()
    yref_arr  = ext["_year_ref"].to_numpy()

    if resolution == "day":
        vfunc = np.vectorize(
            lambda sm, slen, my, ny: sum(_season_ndays(my + k, sm, slen) for k in range(ny))
        )
        n_expected = vfunc(sm_arr, slen_arr, my_arr, ny_arr)
    elif resolution == "month":
        n_expected = (slen_arr * ny_arr).astype(np.int64)
    elif resolution == "season":
        n_expected = ny_arr.astype(np.int64)
    else:   # "year"
        n_expected = np.ones(len(sname_arr), dtype=np.int64)
    ext["NApct"] = _napct_vec(ext["_nPresent"].to_numpy(), ext["_nNA"].to_numpy(), n_expected)

    if NApct_lim is not None:
        ext.loc[ext["NApct"] > NApct_lim, "_value"] = np.nan

    ext["Date"] = [pd.Timestamp(year=int(yr), month=int(sm), day=1)
                   for yr, sm in zip(yref_arr, sm_arr)]
    ext = ext.rename(columns={"_value": nameEX, "_season_name": "Season"})

    cols = [id_col, "Date", "Season", nameEX] + ([] if rmNApct else ["NApct"])
    return ext[cols].sort_values([id_col, "Date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# time_step = "yearday"
# ---------------------------------------------------------------------------

def _extract_yearday(data, id_col, date_col, col_name, funct, funct_kwargs, skip_na,
                      NApct_lim, rmNApct, nameEX, resolution="day"):
    """
    Groupement par jour de l'année 1-365 (yday brut = comportement R).
    Le jour 366 (29 fév des années bissextiles) est exclu.
    """
    if "_yd" not in data.columns:
        yd = data[date_col].dt.day_of_year.to_numpy().astype(np.float32)
        yd[yd >= 366] = np.nan
        data["_yd"] = yd
    data = data.dropna(subset=["_yd"])
    data["_yd"] = data["_yd"].astype(np.int16)

    ext = _groupby_agg(data, [id_col, "_yd"], col_name, funct, funct_kwargs, skip_na)

    yr = data.groupby(id_col, observed=True)[date_col].agg(
        _min_year=lambda s: s.dt.year.min(),
        _nYear=lambda s: s.dt.year.max() - s.dt.year.min(),   # = R : max - min (pas +1)
    )
    ext = ext.join(yr, on=id_col)

    ny_arr = ext["_nYear"].to_numpy().astype(np.float64)
    ny_arr[ny_arr <= 0] = np.nan
    ext["NApct"] = _napct_vec(ext["_nPresent"].to_numpy(), ext["_nNA"].to_numpy(), ny_arr)
    ext.loc[ext["_nYear"] <= 0, "NApct"] = 0.0

    if NApct_lim is not None:
        ext.loc[ext["NApct"] > NApct_lim, "_value"] = np.nan

    my_arr = ext["_min_year"].to_numpy()
    yd_arr = ext["_yd"].to_numpy()
    ext["Date"] = [
        pd.Timestamp(year=int(y), month=1, day=1) + pd.Timedelta(days=int(d) - 1)
        for y, d in zip(my_arr, yd_arr)
    ]
    ext = ext.rename(columns={"_value": nameEX, "_yd": "Yearday"})

    cols = [id_col, "Date", "Yearday", nameEX] + ([] if rmNApct else ["NApct"])
    return ext[cols].sort_values([id_col, "Date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# time_step = "none"
# ---------------------------------------------------------------------------

def _extract_none(data, id_col, date_col, col_name, funct, funct_kwargs, skip_na,
                   NApct_lim, rmNApct, nameEX, sampling_period, resolution="day"):
    """time_step 'none' : la sortie de funct est classée dynamiquement,
    comme en R où le résultat peut être de longueur quelconque :

    - scalaire            → une ligne par série (+ NApct) ;
    - même longueur que   → « transform » : colonne alignée sur les lignes
      le groupe             d'entrée (ex. moyenne mobile) ;
    - autre longueur      → « ragged » : une ligne par élément du résultat
                            (ex. courbe des débits classés), avec un rang
                            interne '_rank' pour la jointure multi-functs.
    """
    if sampling_period is not None and date_col is not None:
        sp_start, sp_end = _resolve_sampling_period(sampling_period)
        ref_year = 1972
        dt2add = 1 if pd.Timestamp(f"{ref_year}-{sp_start}") > pd.Timestamp(f"{ref_year}-{sp_end}") else 0
        hydro = _assign_hydro_year(data[date_col], sp_start, sp_end, dt2add)
        data = data[hydro.notna()]

    col_names = [col_name] if isinstance(col_name, str) else list(col_name)
    primary = col_names[0]

    rows_scalar = []                      # (id, n_present, n_na, value)
    vec_results: list[tuple] = []         # (id, sub_df, vector | None)
    any_vector = False

    for gid, g in data.groupby(id_col, observed=True, sort=True):
        n_present = len(g)
        n_na = int(g[primary].isna().sum()) if n_present else 0
        sub = g
        if skip_na and n_present:
            sub = g[g[col_names].notna().all(axis=1)]
        if len(sub) == 0:
            rows_scalar.append((gid, n_present, n_na, np.nan))
            vec_results.append((gid, g, None))
            continue
        try:
            v = funct(*[sub[c] for c in col_names], **funct_kwargs)
        except Exception:
            if sub[primary].isna().all():
                v = np.nan
            else:
                raise
        if (isinstance(v, (pd.Series, np.ndarray, list, tuple))
                and np.ndim(v) >= 1 and np.size(v) != 1):
            any_vector = True
            vec_results.append((gid, sub, np.asarray(v)))
            rows_scalar.append((gid, n_present, n_na, np.nan))
        else:
            scalar = v if np.ndim(v) == 0 else np.asarray(v).reshape(-1)[0]
            rows_scalar.append((gid, n_present, n_na, scalar))
            vec_results.append((gid, sub, None))

    if any_vector:
        if NApct_lim is not None:
            warnings.warn(
                f"NApct_lim ignoré pour '{nameEX}' : sortie vectorielle "
                "(transform/ragged) en time_step 'none'."
            )
        parts = []
        all_aligned = True
        for gid, sub, v in vec_results:
            if v is None:
                continue    # série vide ou toute-NaN : absente de la sortie
            if len(v) == len(sub):
                cols_dict = {id_col: gid}
                if date_col is not None:
                    cols_dict[date_col] = sub[date_col].to_numpy()
                else:
                    cols_dict["_rank"] = np.arange(len(v))
                cols_dict[nameEX] = v
                # index d'origine préservé : permet le fan-out keep='all'
                # par alignement d'index (pas de merge 5M×5M)
                parts.append(pd.DataFrame(cols_dict, index=sub.index))
            else:
                all_aligned = False
                cols_dict = {id_col: gid,
                             "_rank": np.arange(len(v)),
                             nameEX: v}
                parts.append(pd.DataFrame(cols_dict))
        if not parts:
            # toutes les séries vides ou toutes-NaN : vide typé
            return pd.DataFrame({id_col: pd.Series(dtype=object),
                                 nameEX: pd.Series(dtype="float64")})
        out = pd.concat(parts, ignore_index=not all_aligned)
        if all_aligned:
            out.attrs[_ALIGNED_ATTR] = True
        return out

    ext = pd.DataFrame(rows_scalar,
                       columns=[id_col, "_nPresent", "_nNA", "_value"])

    if date_col is not None:
        dr = data.groupby(id_col, observed=True)[date_col].agg(
            _min_date=lambda s: s.min(),
            _max_date=lambda s: s.max(),
        )
        ext = ext.join(dr, on=id_col)
        if resolution == "day":
            n_expected = ((ext["_max_date"] - ext["_min_date"]).dt.days + 1).to_numpy()
        elif resolution == "month":
            n_expected = (
                (ext["_max_date"].dt.year - ext["_min_date"].dt.year) * 12
                + (ext["_max_date"].dt.month - ext["_min_date"].dt.month) + 1
            ).to_numpy()
        elif resolution == "season":
            nm = (
                (ext["_max_date"].dt.year - ext["_min_date"].dt.year) * 12
                + (ext["_max_date"].dt.month - ext["_min_date"].dt.month) + 1
            ).to_numpy()
            n_expected = np.maximum(1, np.round(nm / 3)).astype(np.int64)
        else:   # "year"
            n_expected = (
                ext["_max_date"].dt.year - ext["_min_date"].dt.year + 1
            ).to_numpy()
    else:
        n_expected = ext["_nPresent"].to_numpy()

    ext["NApct"] = _napct_vec(ext["_nPresent"].to_numpy(), ext["_nNA"].to_numpy(), n_expected)

    if NApct_lim is not None:
        ext.loc[ext["NApct"] > NApct_lim, "_value"] = np.nan

    ext = ext.rename(columns={"_value": nameEX})
    cols = [id_col, nameEX] + ([] if rmNApct else ["NApct"])
    return ext[cols].reset_index(drop=True)


def _process_adaptive(data: pd.DataFrame, spec: Adaptive, kwargs: dict):
    """sampling_period adaptatif : calcule le mois de début par série puis
    ré-appelle process_extraction par groupe de séries partageant le même
    mois (équivalent fix_sampling_period + boucle par Code en R)."""
    date_col, id_col, _ = _detect_columns(data)
    if date_col is None:
        raise ValueError(
            "sampling_period adaptatif : colonne datetime requise dans data."
        )
    if spec.col not in data.columns:
        raise ValueError(
            f"sampling_period adaptatif : colonne '{spec.col}' introuvable. "
            f"Colonnes disponibles : {list(data.columns)}"
        )

    fallback_ids: list = []

    def _start_month(g: pd.DataFrame, gid=None) -> str:
        monthly = g.groupby(g[date_col].dt.month)[spec.col].mean().dropna()
        if len(monthly) == 0:
            fallback_ids.append(gid)
            return spec.default
        target = spec.funct(monthly.to_numpy())
        matches = monthly.index[monthly == target]
        if len(matches) == 0:
            # funct n'a pas retourné une des moyennes mensuelles
            # (ex. np.nanmean) : impossible d'en déduire un mois
            fallback_ids.append(gid)
            return spec.default
        return f"{int(matches[0]):02d}-01"

    def _warn_fallbacks():
        if fallback_ids:
            _preview = ", ".join(str(i) for i in fallback_ids[:5])
            if len(fallback_ids) > 5:
                _preview += f", … (+{len(fallback_ids) - 5})"
            warnings.warn(
                f"sampling_period adaptatif : repli sur le mois par défaut "
                f"'{spec.default}' pour {len(fallback_ids)} série(s) "
                f"({_preview}) — série vide, toute-NaN, ou funct ne "
                "retournant pas une des moyennes mensuelles "
                "(utilisez p. ex. np.nanmax / np.nanmin).",
                UserWarning, stacklevel=3,
            )

    sparse_in = list(data.attrs.get(_SPARSE_ATTR, []))

    if id_col is None:
        sp = _start_month(data)
        _warn_fallbacks()
        return process_extraction(data, sampling_period=sp, **kwargs)

    groups: dict[str, list] = {}
    for gid, g in data.groupby(id_col, observed=True, sort=False):
        if len(g) == 0:
            continue
        groups.setdefault(_start_month(g, gid), []).append(gid)
    _warn_fallbacks()

    parts, out_sparse = [], set()
    for sp, ids in groups.items():
        subset = data[data[id_col].isin(ids)].copy()
        if isinstance(subset[id_col].dtype, pd.CategoricalDtype):
            # les catégories inutilisées créeraient des groupes fantômes
            subset[id_col] = subset[id_col].cat.remove_unused_categories()
        subset.attrs[_SPARSE_ATTR] = sparse_in
        res = process_extraction(subset, sampling_period=sp, **kwargs)
        out_sparse |= set(res.attrs.get(_SPARSE_ATTR, []))
        parts.append(res)

    if len(parts) == 1:
        return parts[0]
    result = pd.concat(parts, ignore_index=True)   # concat perd les attrs
    sort_cols = [c for c in (id_col, "Date", date_col)
                 if c in result.columns][:2]
    if sort_cols:
        result = result.sort_values(sort_cols).reset_index(drop=True)
    if out_sparse:
        result.attrs[_SPARSE_ATTR] = sorted(out_sparse)
    return result
