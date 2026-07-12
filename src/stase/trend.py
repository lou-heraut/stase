# Copyright 2021-2026 Louis Héraut <louis.heraut@inrae.fr>*1
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
EXstat — process_trend (faithful Python conversion of process_trend.R)

Takes the output of process_extraction (one row per series×date) and runs
Mann-Kendall + Sen-Theil per series and per variable.

Usage
-----
from stase import process_trend
trendEX = process_trend(dataEX, MK_level=0.1, time_dependency_option="INDE")
"""

import warnings

import numpy as np
import pandas as pd

from .tools import GeneralMannKendall

# Séparateur interne pour unir plusieurs colonnes identifiantes en une
# clé de groupement unique. Caractère de contrôle ASCII (unit separator) :
# ne peut pas apparaître dans un identifiant réel, le split retour est
# donc sans ambiguïté même si les identifiants contiennent '_'.
_ID_SEP = "\x1f"


# ── Verbose helper (same style as process_extraction._verbose_box) ────────────

def _verbose_box(title: str, rows: list, width: int = 66) -> None:
    inner = width - 2
    bar = "─" * max(0, inner - len(title) - 3)
    print(f"┌─ {title} {bar}┐")
    for r in rows:
        print("│  " + r.ljust(inner - 2) + "│")
    print("└" + "─" * inner + "┘")


# ── Per-series helpers ───────────────────────────────────────────────────────

def _mk_series(grp, var, date_col, MK_level, option, show_advance_stat, to_norm):
    """MK test + intercept b + period range + normalised slope for one series."""
    grp = grp.sort_values(date_col)
    X = grp[var].values.astype(float)
    dates_ns = grp[date_col].values

    # Mann-Kendall
    mk = GeneralMannKendall(
        X, level=MK_level,
        time_dependency_option=option,
        do_detrending=True,
        show_advance_stat=show_advance_stat,
    )

    # Intercept: b = mean(X) - mu_t * a
    # mu_t = mean(date_days) / mean(diff(date_days))   — matches R's get_intercept
    dates_days = dates_ns.astype(np.int64) / 86_400_000_000_000.0   # ns → days
    b = np.nan
    if len(dates_days) > 1:
        mean_interval = float(np.mean(np.diff(dates_days)))
        if mean_interval != 0.0 and np.isfinite(mean_interval):
            mu_t = float(np.mean(dates_days)) / mean_interval
            a_val = mk.get("a")
            if a_val is not None and np.isfinite(a_val):
                mu_X = float(np.nanmean(X))
                b = mu_X - mu_t * a_val
                if not np.isfinite(b):
                    b = np.nan

    # Period range: R uses min/max of the DATE column regardless of NA in X
    period_start = pd.Timestamp(dates_ns.min()) if len(dates_ns) > 0 else pd.NaT
    period_end   = pd.Timestamp(dates_ns.max()) if len(dates_ns) > 0 else pd.NaT

    # Normalised slope
    valid = ~np.isnan(X)
    mean_val = float(np.nanmean(X)) if valid.any() else np.nan
    a_val = mk.get("a")
    if to_norm:
        if (a_val is not None and np.isfinite(float(a_val))
                and np.isfinite(mean_val) and mean_val != 0.0):
            a_normalise = float(a_val) / mean_val * 100.0
        else:
            a_normalise = np.nan
        mean_period_trend = mean_val if np.isfinite(mean_val) else np.nan
    else:
        a_normalise = (float(a_val) if (a_val is not None and np.isfinite(float(a_val)))
                       else np.nan)
        mean_period_trend = np.nan

    out = dict(mk)
    out.update({
        "b":                  b,
        "period_trend_start": period_start,
        "period_trend_end":   period_end,
        "mean_period_trend":  mean_period_trend,
        "a_normalise":        a_normalise,
    })
    return pd.Series(out)


def _change_series(grp, var, date_col, period_change, to_norm):
    """Mean change between two periods for one series."""
    grp = grp.sort_values(date_col)
    dates = grp[date_col]
    X = grp[var].values.astype(float)

    pc1_s, pc1_e = period_change[0]
    pc2_s, pc2_e = period_change[1]

    d_min, d_max = dates.min(), dates.max()
    s1, e1 = max(pc1_s, d_min), min(pc1_e, d_max)
    s2, e2 = max(pc2_s, d_min), min(pc2_e, d_max)

    m1 = (dates >= s1) & (dates <= e1)
    m2 = (dates >= s2) & (dates <= e2)
    mean_1 = float(np.nanmean(X[m1.values])) if m1.any() else np.nan
    mean_2 = float(np.nanmean(X[m2.values])) if m2.any() else np.nan

    if (to_norm and np.isfinite(mean_1) and mean_1 != 0.0 and np.isfinite(mean_2)):
        change = (mean_2 - mean_1) / mean_1 * 100.0
    elif np.isfinite(mean_1) and np.isfinite(mean_2):
        change = mean_2 - mean_1
    else:
        change = np.nan

    return pd.Series({
        "period_change_start_1":  s1,    "period_change_end_1":  e1,
        "period_change_start_2":  s2,    "period_change_end_2":  e2,
        "mean_period_change_1":   mean_1,
        "mean_period_change_2":   mean_2,
        "change":                 change,
    })


# ── Main function ─────────────────────────────────────────────────────────────

def process_trend(
    dataEX,
    MK_level=0.1,
    time_dependency_option="INDE",
    suffix=None,
    suffix_delimiter="_",
    to_normalise=True,
    metaEX=None,
    extreme_take_not_signif_into_account=True,
    extreme_take_only_series=None,
    extreme_by_suffix=True,
    period_trend=None,
    period_change=None,
    extreme_prob=0.01,
    show_advance_stat=False,
    verbose=True,
):
    """Run Mann-Kendall + Sen-Theil trend analysis on process_extraction output.

    Parameters
    ----------
    dataEX : DataFrame
        Output of process_extraction — one row per (series, date), numeric columns
        are the variables to analyse.
    MK_level : float
        Significance level for the Mann-Kendall test (default 0.1).
    time_dependency_option : str
        'INDE' (standard), 'AR1' (Hamed & Rao 1998), or 'LTP' (Hamed 2008).
    suffix : list[str] | None
        Variable-name suffixes to strip when grouping extremes and when
        looking up normalisation info in metaEX.
    suffix_delimiter : str
        Delimiter prepended to each suffix element (default '_').
    to_normalise : bool | dict[str, bool]
        Whether to compute a_normalise = a/mean(X)*100.
        True/False applied to all variables; dict for per-variable control.
    metaEX : DataFrame | None
        Metadata table with columns {'variable_en', 'to_normalise'} overriding
        to_normalise when provided.
    extreme_take_not_signif_into_account : bool
        If False, only significant series (H=True) contribute to the
        a_normalise quantile bounds.
    extreme_take_only_series : list | None
        Subset of series IDs to use for quantile computation (None = all).
    extreme_by_suffix : bool
        If True, quantiles are grouped by full variable name; if False, by
        the suffix-stripped base name.
    period_trend : list | None
        [start, end] or list of [start, end] pairs to restrict the analysis.
        None = use all available data.
    period_change : list | None
        List of exactly 2 [start, end] pairs; triggers mean-change computation.
    extreme_prob : float
        Probability for extreme quantile bounds (default 0.01).
    show_advance_stat : bool
        If True, include 'stat' and 'dep' columns in the output.
    verbose : bool
        Print progress to stdout.

    Returns
    -------
    DataFrame with columns:
        {id_col}, variable_en, [variable_no_suffix_en], level, H, p, a, b,
        period_trend_start, period_trend_end, mean_period_trend, a_normalise,
        a_normalise_min, a_normalise_max,
        [period_change_start_1, period_change_end_1, period_change_start_2,
         period_change_end_2, mean_period_change_1, mean_period_change_2,
         change, change_min, change_max]
    Sorted by (id_col, variable_en).

    Notes
    -----
    Python vs R divergences:
    - period_trend / period_change stored as separate _start/_end columns
      (R uses list columns).
    - mean_period_change stored as mean_period_change_1 / _2 (R: list column).
    - Hurst MLE precision (LTP): Python uses xatol≈1.5e-8 vs R's ≈1.2e-4,
      producing slightly more accurate results.
    """
    # ── 1. Validate ───────────────────────────────────────────────────────────
    if not isinstance(dataEX, pd.DataFrame):
        raise TypeError(
            f"dataEX doit être un DataFrame pandas, reçu {type(dataEX).__name__}."
        )
    if len(dataEX) == 0:
        warnings.warn("dataEX est vide (0 lignes). Retour d'un DataFrame vide.", UserWarning)
        return pd.DataFrame()
    if time_dependency_option not in ("INDE", "AR1", "LTP"):
        raise ValueError(
            f"time_dependency_option='{time_dependency_option}' invalide. "
            "Valeurs acceptées : 'INDE', 'AR1', 'LTP'."
        )
    if not (0 < MK_level < 1):
        raise ValueError(f"MK_level={MK_level} doit être dans (0, 1).")
    if not (0 < extreme_prob < 0.5):
        raise ValueError(
            f"extreme_prob={extreme_prob} invalide : doit être dans (0, 0.5)."
        )

    # ── 2. Detect columns ─────────────────────────────────────────────────────
    date_col = None
    id_cols  = []
    var_cols = []
    for col in dataEX.columns:
        if pd.api.types.is_datetime64_any_dtype(dataEX[col]):
            if date_col is not None:
                raise ValueError(
                    "dataEX contient plusieurs colonnes datetime. Une seule est attendue."
                )
            date_col = col
        elif (pd.api.types.is_string_dtype(dataEX[col])
              or dataEX[col].dtype == object):
            id_cols.append(col)
        elif pd.api.types.is_numeric_dtype(dataEX[col]):
            var_cols.append(col)

    if date_col is None:
        raise ValueError(
            "dataEX ne contient aucune colonne datetime. "
            "Vérifiez que votre sortie de process_extraction est correcte."
        )
    if len(var_cols) == 0:
        raise ValueError(
            "dataEX ne contient aucune colonne numérique (variable à analyser)."
        )

    # ── 3. Normalize ID column(s) ─────────────────────────────────────────────
    original_id_cols = list(id_cols)
    dataEX = dataEX.copy()

    if len(id_cols) == 0:
        # No ID: add synthetic column if dates are unique → single series
        if dataEX[date_col].nunique() == len(dataEX):
            warnings.warn(
                "Aucune colonne identifiant (str) trouvée. "
                "Une colonne 'ID' synthétique 'time serie' est ajoutée.",
                UserWarning,
            )
            dataEX["ID"] = "time serie"
            id_col = "ID"
        else:
            raise ValueError(
                "Aucune colonne identifiant (str) trouvée et les dates ne sont "
                "pas uniques. Ajoutez une colonne identifiant à votre DataFrame."
            )
    elif len(id_cols) == 1:
        id_col = id_cols[0]
    else:
        # Multiple ID cols: unite them into a single grouping key. The
        # separator is a control character that cannot appear in real IDs,
        # so the split back at the end is lossless even when IDs contain
        # the display delimiter (e.g. "S_1"). R's tidyr::unite uses "_"
        # and has the ambiguity; we don't reproduce it.
        dataEX["_ID_united"] = (
            dataEX[id_cols].astype(str).agg(_ID_SEP.join, axis=1)
        )
        dataEX = dataEX.drop(columns=id_cols)
        id_col = "_ID_united"

    # Check date uniqueness per series (vectorized)
    dup_mask = dataEX.duplicated(subset=[id_col, date_col])
    if dup_mask.any():
        bad = dataEX.loc[dup_mask, id_col].unique().tolist()[:5]
        bad = [str(b).replace(_ID_SEP, "_") for b in bad]
        raise ValueError(
            f"Dates dupliquées dans les séries : {bad}. "
            "Utilisez rm_duplicates=True dans process_extraction."
        )

    # ── 4. Build suffix list ───────────────────────────────────────────────────
    if suffix is not None:
        if isinstance(suffix, str):
            suffix = [suffix]
        if suffix_delimiter is None:
            raise ValueError("suffix_delimiter requis quand suffix est fourni.")
        suffix_full = [suffix_delimiter + s for s in suffix]
    else:
        suffix_full = None

    def _strip_suffix(var):
        """Strip all suffixes from variable name (for base-name grouping)."""
        name = var
        if suffix_full:
            for sf in suffix_full:
                name = name.replace(sf, "")
        return name

    # ── 5. Resolve to_normalise per variable ──────────────────────────────────
    if isinstance(to_normalise, dict) and metaEX is None:
        if len(to_normalise) == 1:
            single_val = next(iter(to_normalise.values()))
            warnings.warn(
                f"to_normalise est une valeur unique ({single_val}), "
                f"appliquée à toutes les variables : {var_cols}",
                UserWarning,
            )
        else:
            missing = [v for v in var_cols
                       if v not in to_normalise and _strip_suffix(v) not in to_normalise]
            if missing:
                raise ValueError(
                    f"to_normalise ne couvre pas toutes les variables : {missing}."
                )

    def _get_to_normalise(var):
        if metaEX is not None:
            base = _strip_suffix(var)
            row = metaEX[metaEX["variable_en"] == base]
            if len(row) > 0:
                return bool(row["to_normalise"].iloc[0])
            return True
        if isinstance(to_normalise, dict):
            if var in to_normalise:
                return bool(to_normalise[var])
            base = _strip_suffix(var)
            if base in to_normalise:
                return bool(to_normalise[base])
            # Single-value dict → use it for all
            if len(to_normalise) == 1:
                return bool(next(iter(to_normalise.values())))
            return True
        return bool(to_normalise)

    # ── 6. Normalize period_trend ─────────────────────────────────────────────
    if period_trend is not None:
        # Accept flat [start, end] or list of lists
        if (not isinstance(period_trend[0], (list, tuple))
                and not isinstance(period_trend[0], pd.Timestamp)):
            # It's already a flat pair
            period_trend = [period_trend]
        periods = []
        for pt in period_trend:
            p0 = pd.Timestamp(pt[0]) if pt[0] is not None else None
            p1 = pd.Timestamp(pt[1]) if pt[1] is not None else None
            if p0 is not None and p1 is not None and p0 > p1:
                warnings.warn(
                    "period_trend : dates dans l'ordre décroissant, "
                    "réordonnement automatique.",
                    UserWarning,
                )
                p0, p1 = p1, p0
            periods.append((p0, p1))
    else:
        periods = [(None, None)]

    # ── 7. Normalize period_change ────────────────────────────────────────────
    pc_pairs = None
    if period_change is not None:
        if (not isinstance(period_change[0], (list, tuple))
                and not isinstance(period_change[0], pd.Timestamp)):
            period_change = [period_change]
        if len(period_change) != 2:
            warnings.warn(
                f"period_change doit contenir exactement 2 sous-périodes "
                f"(reçu {len(period_change)}). Calcul du changement ignoré.",
                UserWarning,
            )
        else:
            pc_pairs = [
                [pd.Timestamp(pc[0]), pd.Timestamp(pc[1])]
                for pc in period_change
            ]

    # ── 8. Main loop ──────────────────────────────────────────────────────────
    if verbose:
        n_st = dataEX[id_col].nunique()
        _ids = dataEX[id_col].unique()
        _preview = ", ".join(str(s).replace(_ID_SEP, "_") for s in _ids[:3])
        if n_st > 3:
            _preview += f", … (+{n_st - 3})"
        _d0 = dataEX[date_col].min().date()
        _d1 = dataEX[date_col].max().date()
        _rows = [
            f"option     {time_dependency_option:<8}  level  {MK_level}",
            f"séries     {n_st}  ({_preview})",
            f"variables  {', '.join(var_cols)}",
            f"période    {_d0} → {_d1}  [{len(periods)} fenêtre(s)]",
        ]
        _verbose_box("process_trend", _rows)

    all_results = []

    for j, (p0, p1) in enumerate(periods):
        real_p0 = p0 if p0 is not None else dataEX[date_col].min()
        real_p1 = p1 if p1 is not None else dataEX[date_col].max()
        mask = (dataEX[date_col] >= real_p0) & (dataEX[date_col] <= real_p1)
        data_j = dataEX[mask]

        if verbose:
            print(f"  Période {j + 1}/{len(periods)} : "
                  f"{real_p0.date()} → {real_p1.date()}")

        if len(data_j) == 0:
            warnings.warn(
                f"Période {j + 1} : aucune donnée dans la plage "
                f"{real_p0.date()} → {real_p1.date()}. "
                f"Données disponibles : {dataEX[date_col].min().date()} "
                f"→ {dataEX[date_col].max().date()}.",
                UserWarning,
            )
            continue

        period_rows = []

        for var in var_cols:
            to_norm = _get_to_normalise(var)
            var_no_suffix = _strip_suffix(var)
            var_data = data_j[[id_col, date_col, var]]

            # ── MK + intercept + normalise per series ────────────────────────
            mk_df = (
                var_data
                .groupby(id_col, observed=True)
                .apply(
                    _mk_series,
                    var=var,
                    date_col=date_col,
                    MK_level=MK_level,
                    option=time_dependency_option,
                    show_advance_stat=show_advance_stat,
                    to_norm=to_norm,
                    include_groups=False,
                )
                .reset_index()
            )
            mk_df["variable_en"] = var
            if suffix_full is not None:
                mk_df["variable_no_suffix_en"] = var_no_suffix

            # ── Change between two periods ────────────────────────────────────
            if pc_pairs is not None:
                ch_df = (
                    var_data
                    .groupby(id_col, observed=True)
                    .apply(
                        _change_series,
                        var=var,
                        date_col=date_col,
                        period_change=pc_pairs,
                        to_norm=to_norm,
                        include_groups=False,
                    )
                    .reset_index()
                )
                mk_df = mk_df.merge(ch_df, on=id_col)

            period_rows.append(mk_df)

            if verbose:
                n_sig = int(mk_df["H"].fillna(False).sum())
                print(f"    '{var}' : {len(mk_df)} séries, "
                      f"{n_sig} tendances significatives")

        period_df = pd.concat(period_rows, ignore_index=True)

        # ── Extreme trend quantiles per variable group ───────────────────────
        group_var = ("variable_no_suffix_en"
                     if (not extreme_by_suffix and suffix_full is not None
                         and "variable_no_suffix_en" in period_df.columns)
                     else "variable_en")

        if extreme_take_only_series is None:
            in_series = period_df[id_col].notna()   # all rows
        else:
            in_series = period_df[id_col].isin(extreme_take_only_series)

        # Temporarily mask non-significant slopes if requested
        if not extreme_take_not_signif_into_account:
            saved_a_norm = period_df["a_normalise"].copy()
            period_df.loc[~period_df["H"].fillna(False), "a_normalise"] = np.nan

        for var_grp, grp_idx in period_df.groupby(group_var, observed=True).groups.items():
            grp_mask = period_df.index.isin(grp_idx)          # boolean mask for this group
            sel_mask = grp_mask & in_series.values
            a_vals = period_df.loc[sel_mask, "a_normalise"].dropna()
            q_min = float(a_vals.quantile(extreme_prob))       if len(a_vals) > 0 else np.nan
            q_max = float(a_vals.quantile(1 - extreme_prob))   if len(a_vals) > 0 else np.nan
            period_df.loc[grp_mask, "a_normalise_min"] = q_min
            period_df.loc[grp_mask, "a_normalise_max"] = q_max

        if not extreme_take_not_signif_into_account:
            period_df["a_normalise"] = saved_a_norm

        # ── Extreme change quantiles ─────────────────────────────────────────
        if pc_pairs is not None and "change" in period_df.columns:
            for var_grp, grp_idx in period_df.groupby(group_var, observed=True).groups.items():
                grp_mask = period_df.index.isin(grp_idx)
                sel_mask = grp_mask & in_series.values
                ch_vals = period_df.loc[sel_mask, "change"].dropna()
                c_min = float(ch_vals.quantile(extreme_prob))     if len(ch_vals) > 0 else np.nan
                c_max = float(ch_vals.quantile(1 - extreme_prob)) if len(ch_vals) > 0 else np.nan
                period_df.loc[grp_mask, "change_min"] = c_min
                period_df.loc[grp_mask, "change_max"] = c_max

        all_results.append(period_df)

    # ── 9. Assemble and return ────────────────────────────────────────────────
    if not all_results:
        warnings.warn(
            "Aucune donnée dans les périodes spécifiées. Retour d'un DataFrame vide.",
            UserWarning,
        )
        return pd.DataFrame()

    result = pd.concat(all_results, ignore_index=True)
    result = result.sort_values([id_col, "variable_en"]).reset_index(drop=True)

    # Restore original ID column name(s)
    if len(original_id_cols) > 1:
        # Split united ID back into original columns — the control-char
        # separator makes this lossless even if IDs contain "_"
        split = result[id_col].str.split(_ID_SEP, expand=True)
        loc = result.columns.get_loc(id_col)
        for i, col_name in enumerate(original_id_cols):
            result.insert(loc + i, col_name, split[i])
        result = result.drop(columns=[id_col])
    elif len(original_id_cols) == 1 and id_col != original_id_cols[0]:
        result = result.rename(columns={id_col: original_id_cols[0]})
    elif len(original_id_cols) == 0:
        pass   # synthetic "ID" stays as-is

    # Nullable boolean H: with too few valid values the MK test yields
    # None — without this the column would silently become object dtype
    # and boolean filtering (trendEX[trendEX.H]) would break
    if "H" in result.columns:
        result["H"] = pd.array(result["H"], dtype="boolean")

    if verbose:
        n_sig = int(result["H"].fillna(False).sum())
        n_vars = result["variable_en"].nunique()
        print(f"  → {len(result)} résultats ({n_vars} variables × "
              f"{len(result) // max(n_vars, 1)} séries) · "
              f"{n_sig} tendances H=True")

    return result
