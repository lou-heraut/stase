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
trend = process_trend(data, level=0.1, dependency="INDE")
"""

import warnings

import numpy as np
import pandas as pd

from ._display import _verbose_box
from .tools import GeneralMannKendall

# Séparateur interne pour unir plusieurs colonnes identifiantes en une
# clé de groupement unique. Caractère de contrôle ASCII (unit separator) :
# ne peut pas apparaître dans un identifiant réel, le split retour est
# donc sans ambiguïté même si les identifiants contiennent '_'.
_ID_SEP = "\x1f"


# ── Per-series helpers ───────────────────────────────────────────────────────

def _mk_series(grp, var, date_col, level, option, advanced_stats, to_norm,
               rng=None):
    """MK test + intercept b + period range + normalised slope for one series."""
    grp = grp.sort_values(date_col)
    X = grp[var].values.astype(float)
    dates_ns = grp[date_col].values

    # Mann-Kendall
    mk = GeneralMannKendall(
        X, level=level,
        time_dependency_option=option,
        do_detrending=True,
        show_advance_stat=advanced_stats,
        rng=rng,
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

    # Pente relative. 'a' porte toujours la pente absolue ; 'a_relative'
    # ne porte QUE le pourcentage, et vaut NaN quand la variable ne
    # s'exprime pas relativement (une date, un compte). Le R recopiait
    # 'a' dans 'a_normalise' dans ce cas : deux variables d'une même
    # sortie s'y retrouvaient dans des unités différentes sous le même
    # nom de colonne, sans rien pour les distinguer.
    valid = ~np.isnan(X)
    mean_val = float(np.nanmean(X)) if valid.any() else np.nan
    a_val = mk.get("a")
    if (to_norm and a_val is not None and np.isfinite(float(a_val))
            and np.isfinite(mean_val) and mean_val != 0.0):
        a_relative = float(a_val) / mean_val * 100.0
    else:
        a_relative = np.nan

    out = dict(mk)
    out.update({
        "b":               b,
        "period_start":    period_start,
        "period_end":      period_end,
        # Toujours calculée : la moyenne de la période est définie que la
        # variable soit relative ou non.
        "mean_period":     mean_val if np.isfinite(mean_val) else np.nan,
        "a_relative":      a_relative,
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

    # Même séparation que pour la pente : 'change' est toujours la
    # différence absolue des moyennes, 'change_relative' toujours un
    # pourcentage, NaN si la variable n'est pas relative.
    if np.isfinite(mean_1) and np.isfinite(mean_2):
        change = mean_2 - mean_1
    else:
        change = np.nan

    if to_norm and np.isfinite(change) and mean_1 != 0.0:
        change_relative = change / mean_1 * 100.0
    else:
        change_relative = np.nan

    return pd.Series({
        "period_change_start_1":  s1,    "period_change_end_1":  e1,
        "period_change_start_2":  s2,    "period_change_end_2":  e2,
        "mean_period_change_1":   mean_1,
        "mean_period_change_2":   mean_2,
        "change":                 change,
        "change_relative":        change_relative,
    })


def _empty_trend_frame(id_cols, has_suffix, has_change, advanced_stats):
    """Retour vide typé : zéro ligne mais les colonnes standard de la
    sortie, pour que les filtres et merges aval fonctionnent uniformément."""
    cols: dict = {}
    for c in (id_cols or ["ID"]):
        cols[c] = pd.Series(dtype=object)
    cols["variable"] = pd.Series(dtype=object)
    if has_suffix:
        cols["variable_no_suffix"] = pd.Series(dtype=object)
    cols["level"] = pd.Series(dtype="float64")
    cols["H"] = pd.array([], dtype="boolean")
    cols["p"] = pd.Series(dtype="float64")
    cols["a"] = pd.Series(dtype="float64")
    if advanced_stats:
        cols["stat"] = pd.Series(dtype="float64")
        cols["dep"] = pd.Series(dtype="float64")
    cols["b"] = pd.Series(dtype="float64")
    cols["period_start"] = pd.Series(dtype="datetime64[ns]")
    cols["period_end"] = pd.Series(dtype="datetime64[ns]")
    for c in ("a_min", "a_max", "mean_period", "a_relative",
              "a_relative_min", "a_relative_max"):
        cols[c] = pd.Series(dtype="float64")
    if has_change:
        for c in ("period_change_start_1", "period_change_end_1",
                  "period_change_start_2", "period_change_end_2"):
            cols[c] = pd.Series(dtype="datetime64[ns]")
        for c in ("mean_period_change_1", "mean_period_change_2",
                  "change", "change_min", "change_max",
                  "change_relative", "change_relative_min",
                  "change_relative_max"):
            cols[c] = pd.Series(dtype="float64")
    return pd.DataFrame(cols)


# ── Main function ─────────────────────────────────────────────────────────────

def process_trend(
    data,
    level=0.1,
    dependency="INDE",
    suffix=None,
    suffix_delimiter="_",
    relative=True,
    extremes_include_non_significant=True,
    extremes_from_series=None,
    extremes_pool_suffixes=False,
    period=None,
    period_change=None,
    extremes_prob=0.01,
    advanced_stats=False,
    seed=None,
    verbose=False,
):
    """Analyse de tendance Mann-Kendall + pente de Sen sur la sortie de
    stase.extract.

    Paramètres
    ----------
    data : DataFrame
        Sortie de stase.extract : une ligne par (série, date), les
        colonnes numériques sont les variables à analyser.
    level : float
        Niveau de signification du test de Mann-Kendall (défaut 0.1).
    dependency : str
        'INDE' (test standard), 'AR1' (Hamed & Rao 1998) ou 'LTP'
        (Hamed 2008 ; prévu pour des séries annuelles).
    suffix : list[str] | None
        Suffixes de noms de variables (QA_obs, QA_sim). Sert à retrouver
        le nom de base : colonne de sortie 'variable_no_suffix',
        regroupement des extrêmes, et repli de `relative` sur le nom de
        base. Le suffixe est retiré en FIN de nom uniquement.
    suffix_delimiter : str
        Délimiteur préfixant chaque suffixe (défaut '_').
    relative : bool | dict[str, bool]
        La variable s'exprime-t-elle en % de sa moyenne ? Bool global ou
        dict par variable, auquel cas TOUTES les variables doivent être
        couvertes (par leur nom exact ou leur nom de base), sinon
        ValueError. Pilote a_relative et change_relative.
    extremes_include_non_significant : bool
        Si False, seules les séries significatives (H=True) contribuent
        aux bornes de quantiles.
    extremes_from_series : list | None
        Sous-ensemble d'identifiants de séries contribuant aux bornes de
        quantiles (None = toutes). Ne filtre pas les lignes de sortie.
    extremes_pool_suffixes : bool
        Si True, les bornes de quantiles sont mises en commun entre les
        variantes d'une même variable de base (QA_obs et QA_sim partagent
        leurs bornes, donc sont comparables). Défaut False : chaque
        variante a ses propres bornes. Sans effet si suffix est None.
    period : list | None
        [début, fin] ou liste de paires pour restreindre l'analyse.
    period_change : list | None
        Exactement 2 paires [début, fin] : déclenche le calcul du
        changement de moyenne entre les deux sous-périodes.
    extremes_prob : float
        Probabilité des bornes de quantiles extrêmes (défaut 0.01).
    advanced_stats : bool
        Si True, ajoute les colonnes 'stat' et 'dep' à la sortie.
    seed : int | None
        LTP uniquement : graine du tirage aléatoire qui départage les
        ex-æquo lors de l'estimation du coefficient de Hurst. None
        (défaut) : tirage non déterministe, comme en R. Un entier rend
        l'appel reproductible pour des données identiques. Sans effet
        pour INDE/AR1 et pour des séries sans ex-æquo.
    verbose : bool
        Messages de progression.

    Sortie
    ------
    DataFrame trié par (identifiant, variable). Chaque indicateur existe
    en deux colonnes d'unités DISTINCTES, jamais interchangeables :
    l'absolue est toujours renseignée, la relative vaut NaN quand la
    variable n'est pas relative.

        {id}, variable, [variable_no_suffix], level,
        H          test significatif (booléen nullable, NA si moins de
                   3 valeurs valides), p
        a          pente de Sen, en unité de la variable par pas de temps
        a_min/max  bornes de quantiles de a, même unité
        b          ordonnée à l'origine
        period_start, period_end, mean_period
        a_relative         pente en % de mean_period, ou NaN
        a_relative_min/max bornes de quantiles de a_relative, ou NaN

      avec period_change :
        period_change_start_1/end_1/start_2/end_2,
        mean_period_change_1/2
        change                     mean_2 - mean_1, unité de la variable
        change_min/max             bornes de quantiles de change
        change_relative            même écart en % de mean_1, ou NaN
        change_relative_min/max    bornes de quantiles, ou NaN

      avec advanced_stats : stat, dep.
    """
    # ── 1. Validate ───────────────────────────────────────────────────────────
    if not isinstance(data, pd.DataFrame):
        raise TypeError(
            f"data doit être un DataFrame pandas, reçu {type(data).__name__}."
        )
    if len(data) == 0:
        warnings.warn("data est vide (0 lignes). Retour d'un DataFrame vide.", UserWarning)
        _ids = [c for c in data.columns
                if pd.api.types.is_string_dtype(data[c])
                or data[c].dtype == object]
        return _empty_trend_frame(_ids, suffix is not None,
                                  period_change is not None,
                                  advanced_stats)
    if dependency not in ("INDE", "AR1", "LTP"):
        raise ValueError(
            f"dependency='{dependency}' invalide. "
            "Valeurs acceptées : 'INDE', 'AR1', 'LTP'."
        )
    if not (0 < level < 1):
        raise ValueError(f"level={level} doit être dans (0, 1).")
    if not (0 < extremes_prob < 0.5):
        raise ValueError(
            f"extremes_prob={extremes_prob} invalide : doit être dans (0, 0.5)."
        )

    # ── 2. Detect columns ─────────────────────────────────────────────────────
    from .extraction import _maybe_parse_iso_dates
    data = _maybe_parse_iso_dates(data)
    date_col = None
    id_cols  = []
    var_cols = []
    for col in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[col]):
            if date_col is not None:
                raise ValueError(
                    "data contient plusieurs colonnes datetime. Une seule est attendue."
                )
            date_col = col
        elif (pd.api.types.is_string_dtype(data[col])
              or data[col].dtype == object):
            id_cols.append(col)
        elif pd.api.types.is_numeric_dtype(data[col]):
            var_cols.append(col)

    if date_col is None:
        raise ValueError(
            "data ne contient aucune colonne datetime. "
            "Vérifiez que votre sortie de process_extraction est correcte."
        )
    if len(var_cols) == 0:
        raise ValueError(
            "data ne contient aucune colonne numérique (variable à analyser)."
        )

    # ── 3. Normalize ID column(s) ─────────────────────────────────────────────
    original_id_cols = list(id_cols)
    data = data.copy()

    if len(id_cols) == 0:
        # No ID: add synthetic column if dates are unique → single series
        if data[date_col].nunique() == len(data):
            warnings.warn(
                "Aucune colonne identifiant (texte) trouvée. "
                "Une colonne 'id' synthétique 'time serie' est ajoutée.",
                UserWarning,
            )
            data["id"] = "time serie"
            id_col = "id"
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
        data["_ID_united"] = (
            data[id_cols].astype(str).agg(_ID_SEP.join, axis=1)
        )
        data = data.drop(columns=id_cols)
        id_col = "_ID_united"

    # Check date uniqueness per series (vectorized)
    dup_mask = data.duplicated(subset=[id_col, date_col])
    if dup_mask.any():
        bad = data.loc[dup_mask, id_col].unique().tolist()[:5]
        bad = [str(b).replace(_ID_SEP, "_") for b in bad]
        raise ValueError(
            f"Dates dupliquées dans les séries : {bad}. "
            "Utilisez rm_duplicates=True dans process_extraction."
        )

    # ── 3bis. Grille temporelle régulière par série ───────────────────────────
    # La statistique S de Mann-Kendall ne dépend que de l'ordre des
    # observations, mais la pente de Sen (indices de lignes = axe
    # temporel) et les corrections AR1/LTP supposent un pas régulier :
    # les pas de temps manquants sont insérés en NaN, par série (une
    # entrée issue de process_extraction est déjà complète, l'opération
    # est alors sans effet).
    from .extraction import _complete_grid, _series_resolutions
    data = data.sort_values([id_col, date_col]).reset_index(drop=True)
    _res_by_id = _series_resolutions(data, id_col, date_col)
    data, _n_added, _off_grid = _complete_grid(data, id_col, date_col,
                                                 _res_by_id)
    if _off_grid:
        _preview = ", ".join(str(s).replace(_ID_SEP, "_")
                             for s in _off_grid[:5])
        if len(_off_grid) > 5:
            _preview += f", … (+{len(_off_grid) - 5})"
        warnings.warn(
            f"{len(_off_grid)} série(s) à dates hors de leur grille "
            f"régulière : {_preview}. La pente de Sen y est estimée par "
            "rang et non par temps réel, et les corrections AR1/LTP y "
            "sont approximatives.",
            UserWarning,
        )
    if _n_added:
        warnings.warn(
            f"{_n_added} pas de temps manquants insérés (valeurs NaN) : "
            "la pente de Sen et les corrections AR1/LTP supposent une "
            "grille régulière.",
            UserWarning,
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
        """Retire le suffixe TERMINAL d'un nom de variable, s'il en porte un.

        Ancré en fin de nom : un suffixe 'sim' ne doit pas amputer une
        variable nommée 'QA_simple'. Un seul suffixe est retiré, celui
        qui termine le nom.
        """
        if suffix_full:
            for sf in suffix_full:
                if var.endswith(sf):
                    return var[:-len(sf)]
        return var

    # ── 5. Resolve relative per variable ──────────────────────────────────
    if isinstance(relative, dict):
        if len(relative) == 1:
            single_val = next(iter(relative.values()))
            warnings.warn(
                f"relative est une valeur unique ({single_val}), "
                f"appliquée à toutes les variables : {var_cols}",
                UserWarning,
            )
        else:
            missing = [v for v in var_cols
                       if v not in relative and _strip_suffix(v) not in relative]
            if missing:
                raise ValueError(
                    f"relative ne couvre pas toutes les variables : {missing}."
                )

    def _is_relative(var):
        """Cette variable s'exprime-t-elle en % de sa moyenne ?

        Nom exact d'abord, nom de base ensuite : une extraction suffixée
        peut donner {'QA': True} pour QA_obs comme pour QA_sim.
        """
        if isinstance(relative, dict):
            if var in relative:
                return bool(relative[var])
            base = _strip_suffix(var)
            if base in relative:
                return bool(relative[base])
            # Dict à valeur unique → appliquée à toutes (cf. warning ci-dessus)
            if len(relative) == 1:
                return bool(next(iter(relative.values())))
            return True
        return bool(relative)

    # ── 6. Normalize period ─────────────────────────────────────────────
    if period is not None:
        # Accept flat [start, end] or list of lists
        if (not isinstance(period[0], (list, tuple))
                and not isinstance(period[0], pd.Timestamp)):
            # It's already a flat pair
            period = [period]
        periods = []
        for pt in period:
            p0 = pd.Timestamp(pt[0]) if pt[0] is not None else None
            p1 = pd.Timestamp(pt[1]) if pt[1] is not None else None
            if p0 is not None and p1 is not None and p0 > p1:
                warnings.warn(
                    "period : dates dans l'ordre décroissant, "
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

    # ── 7bis. Garde-fous LTP ──────────────────────────────────────────────────
    _rng = None
    if dependency == "LTP":
        _rng = np.random.default_rng(seed)
        # séries longues : le calcul de variance LTP est en O(n⁴)
        # (mémoire bornée par blocs, mais temps de calcul important)
        _n_max = int(data.groupby(id_col, observed=True)[var_cols]
                     .count().max().max())
        if _n_max > 200:
            warnings.warn(
                f"LTP avec des séries de {_n_max} valeurs : le calcul de "
                "variance est en O(n⁴) — temps potentiellement très long. "
                "LTP est prévu pour des séries agrégées (annuelles "
                "typiquement, n ≤ ~100).",
                UserWarning,
            )
        # ex-æquo sans seed : résultats non reproductibles
        if seed is None:
            _has_ties = any(
                data[[id_col, v]].dropna(subset=[v])
                .duplicated([id_col, v]).any()
                for v in var_cols
            )
            if _has_ties:
                warnings.warn(
                    "LTP : des ex-æquo sont présents dans les séries — le "
                    "tirage aléatoire des rangs (ties.method='random', "
                    "hérité de tools.R) rend les résultats non "
                    "reproductibles d'un appel à l'autre. Passez seed=<int> "
                    "pour des résultats rejouables.",
                    UserWarning,
                )

    # ── 8. Main loop ──────────────────────────────────────────────────────────
    if verbose:
        n_st = data[id_col].nunique()
        _ids = data[id_col].unique()
        _preview = ", ".join(str(s).replace(_ID_SEP, "_") for s in _ids[:3])
        if n_st > 3:
            _preview += f", … (+{n_st - 3})"
        _d0 = data[date_col].min().date()
        _d1 = data[date_col].max().date()
        _rows = [
            f"option     {dependency:<8}  level  {level}",
            f"séries     {n_st}  ({_preview})",
            f"variables  {', '.join(var_cols)}",
            f"période    {_d0} → {_d1}  [{len(periods)} fenêtre(s)]",
        ]
        _verbose_box("process_trend", _rows)

    all_results = []

    for j, (p0, p1) in enumerate(periods):
        real_p0 = p0 if p0 is not None else data[date_col].min()
        real_p1 = p1 if p1 is not None else data[date_col].max()
        mask = (data[date_col] >= real_p0) & (data[date_col] <= real_p1)
        data_j = data[mask]

        if verbose:
            print(f"  Période {j + 1}/{len(periods)} : "
                  f"{real_p0.date()} → {real_p1.date()}")

        if len(data_j) == 0:
            warnings.warn(
                f"Période {j + 1} : aucune donnée dans la plage "
                f"{real_p0.date()} → {real_p1.date()}. "
                f"Données disponibles : {data[date_col].min().date()} "
                f"→ {data[date_col].max().date()}.",
                UserWarning,
            )
            continue

        period_rows = []

        for var in var_cols:
            to_norm = _is_relative(var)
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
                    level=level,
                    option=dependency,
                    advanced_stats=advanced_stats,
                    to_norm=to_norm,
                    rng=_rng,
                    include_groups=False,
                )
                .reset_index()
            )
            mk_df["variable"] = var
            if suffix_full is not None:
                mk_df["variable_no_suffix"] = var_no_suffix

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

        # ── Bornes de quantiles par groupe de variables ──────────────────────
        # Chaque indicateur a les siennes, dans SON unité : 'a' et
        # 'change' en absolu, 'a_relative' et 'change_relative' en %.
        # Une variable non relative a donc des bornes absolues utilisables
        # et des bornes relatives à NaN, au lieu de bornes muettes sur
        # leur unité.
        group_var = ("variable_no_suffix"
                     if (extremes_pool_suffixes and suffix_full is not None
                         and "variable_no_suffix" in period_df.columns)
                     else "variable")

        if extremes_from_series is None:
            in_series = period_df[id_col].notna().to_numpy()   # toutes
        else:
            in_series = period_df[id_col].isin(extremes_from_series).to_numpy()

        # Séries non significatives exclues du calcul des bornes plutôt
        # que masquées puis restaurées : même résultat, pas d'état à
        # rétablir.
        if not extremes_include_non_significant:
            in_series = in_series & period_df["H"].fillna(False).to_numpy()

        pairs = [("a", "a_min", "a_max"),
                 ("a_relative", "a_relative_min", "a_relative_max")]
        if pc_pairs is not None and "change" in period_df.columns:
            pairs += [("change", "change_min", "change_max"),
                      ("change_relative", "change_relative_min",
                       "change_relative_max")]

        for grp_idx in period_df.groupby(group_var, observed=True).groups.values():
            grp_mask = period_df.index.isin(grp_idx)
            sel_mask = grp_mask & in_series
            for src, col_min, col_max in pairs:
                vals = period_df.loc[sel_mask, src].dropna()
                if len(vals) > 0:
                    q_min = float(vals.quantile(extremes_prob))
                    q_max = float(vals.quantile(1 - extremes_prob))
                else:
                    q_min = q_max = np.nan
                period_df.loc[grp_mask, col_min] = q_min
                period_df.loc[grp_mask, col_max] = q_max

        all_results.append(period_df)

    # ── 9. Assemble and return ────────────────────────────────────────────────
    if not all_results:
        warnings.warn(
            "Aucune donnée dans les périodes spécifiées. Retour d'un DataFrame vide.",
            UserWarning,
        )
        return _empty_trend_frame(original_id_cols or ["ID"],
                                  suffix_full is not None,
                                  pc_pairs is not None,
                                  advanced_stats)

    result = pd.concat(all_results, ignore_index=True)
    result = result.sort_values([id_col, "variable"]).reset_index(drop=True)

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
        n_vars = result["variable"].nunique()
        print(f"  → {len(result)} résultats ({n_vars} variables × "
              f"{len(result) // max(n_vars, 1)} séries) · "
              f"{n_sig} tendances H=True")

    return result
