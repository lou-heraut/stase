"""
Script de comparaison R vs Python pour process_extraction (time_step="year").

Workflow :
  1. Lancer d'abord le script R pour générer les fichiers de référence :
       Rscript EXstat_py/ref_extraction.R
  2. Puis lancer ce script :
       python EXstat_py/compare.py

Pour chaque scénario, le script :
  - Recharge les données input générées par R
  - Relance l'extraction Python avec les mêmes paramètres
  - Compare les résultats Python et R colonne par colonne
  - Affiche un résumé des différences (max abs, nb lignes discordantes)

Divergence intentionnelle sur NApct (fenêtres sous-annuelles)
--------------------------------------------------------------
Le code R calcule NApct avec un dénominateur fixe de 365.25 quelle que soit
la taille de la fenêtre. Python utilise le nombre de jours calendaires réels
de la fenêtre, ce qui est sémantiquement correct :
  R   : jours_manquants / 365.25 * 100

  Py  : jours_manquants / taille_fenetre * 100
Pour une fenêtre annuelle (~365 j) les deux sont quasi-identiques (< 0.1 pt).
Pour une fenêtre sous-annuelle la différence est proportionnelle.
Les scénarios concernés (SC6, SC7, SC9, SC10) désactivent donc la vérification
stricte de NApct et affichent l'écart à titre informatif uniquement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ajout du répertoire EXstat_py au path
BASE_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(BASE_DIR))
REF_DIR = BASE_DIR / "ref_output"

from process_extraction import process_extraction

# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def load_r_csv(name: str, subdir: str = "") -> pd.DataFrame:
    path = REF_DIR / subdir / f"{name}.csv" if subdir else REF_DIR / f"{name}.csv"
    df = pd.read_csv(path)
    # Convertit les colonnes de date
    for col in df.columns:
        if "date" in col.lower() or col == "Date":
            try:
                df[col] = pd.to_datetime(df[col])
            except Exception:
                pass
    return df


def compare_results(
    name: str,
    r_out: pd.DataFrame,
    py_out: pd.DataFrame,
    value_col: str,
    tol: float = 1e-6,
    napct_strict: bool = True,
    merge_on: list | None = None,
) -> bool:
    """
    Compare r_out et py_out. Retourne True si les résultats sont équivalents.

    napct_strict=False : écart NApct affiché à titre informatif, ne fait pas échouer.
    merge_on : clés de jointure (défaut : [id_col, "Date"]).
               Pour time_step="none", passer merge_on=[id_col].
    """
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  R  : {len(r_out)} lignes")
    print(f"  Py : {len(py_out)} lignes")

    # Détection de la colonne identifiant
    exclude = {value_col, "NApct", "Date", "Month", "Season", "YearSeason", "Yearday"}
    id_col = [c for c in r_out.columns if c not in exclude][0]

    r_out  = r_out.copy()
    py_out = py_out.copy()

    if "Date" in r_out.columns:
        r_out["Date"]  = pd.to_datetime(r_out["Date"])
        py_out["Date"] = pd.to_datetime(py_out["Date"])

    if merge_on is None:
        merge_on = [id_col, "Date"] if "Date" in r_out.columns else [id_col]

    merged = pd.merge(
        r_out[merge_on + [value_col, "NApct"]].rename(
            columns={value_col: "R_val", "NApct": "R_NApct"}
        ),
        py_out[merge_on + [value_col, "NApct"]].rename(
            columns={value_col: "Py_val", "NApct": "Py_NApct"}
        ),
        on=merge_on,
        how="outer",
    )

    if len(merged) != len(r_out):
        print(f"  ⚠ Nombre de lignes après merge : {len(merged)} "
              f"(attendu {len(r_out)})")

    # Comparaison valeurs
    both_nan = merged["R_val"].isna() & merged["Py_val"].isna()
    one_nan  = merged["R_val"].isna() ^ merged["Py_val"].isna()
    diff_val = np.abs(merged["R_val"] - merged["Py_val"])

    n_mismatch_nan = int(one_nan.sum())
    n_ok    = int(((diff_val <= tol) | both_nan).sum())
    n_total = len(merged)

    print(f"\n  Valeurs extraites ('{value_col}') :")
    if n_mismatch_nan > 0:
        print(f"    ⚠ {n_mismatch_nan} lignes avec NA d'un seul côté")
        disp_cols = merge_on + ["R_val", "Py_val"]
        print(merged[one_nan][disp_cols].to_string(index=False))
    max_diff = diff_val[~one_nan].max() if (~one_nan).any() else 0.0
    print(f"    Différence max : {max_diff:.2e}")
    print(f"    Lignes exactes (tol={tol:.0e}) : {n_ok}/{n_total}")

    # Comparaison NApct
    diff_napct = np.abs(merged["R_NApct"] - merged["Py_NApct"])
    max_napct  = diff_napct.max()
    napct_tag  = "" if napct_strict else "  [divergence intentionnelle, dénominateur réel vs approx. R]"
    print(f"\n  NApct :{napct_tag}")
    print(f"    Différence max : {max_napct:.2f} pts")
    if max_napct > 1.0:
        worst = merged.loc[diff_napct.idxmax()]
        loc_str = "  ".join(str(worst[k]) for k in merge_on)
        print(f"    Pire cas : {loc_str}  R={worst['R_NApct']}  Py={worst['Py_NApct']}")

    napct_ok = (max_napct <= 1.0) if napct_strict else True
    ok = (n_mismatch_nan == 0) and (max_diff <= tol) and napct_ok
    status = "✓ OK" if ok else "✗ DIFFÉRENCES"
    print(f"\n  → {status}")
    return ok


# ---------------------------------------------------------------------------
# Scénarios
# ---------------------------------------------------------------------------

def run_all():
    if not REF_DIR.exists():
        print(f"Dossier {REF_DIR} introuvable.")
        print("Lance d'abord :  Rscript EXstat_py/ref_extraction.R")
        sys.exit(1)

    results = []

    # ---- Scénario 1 : année civile, sampling_period=None, mean ----
    data = load_r_csv("sc1_year_default_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = None,
        rmNApct         = False,
    )
    r_out = load_r_csv("sc1_year_default_output")
    ok = compare_results("SC1 : year / sampling_period=None / mean", r_out, py_out, "QA")
    results.append(ok)

    # ---- Scénario 2 : année hydrologique (09-01), max ----
    data = load_r_csv("sc2_year_hydro_sep_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QJXA": (np.max, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = "09-01",
        rmNApct         = False,
    )
    r_out = load_r_csv("sc2_year_hydro_sep_output")
    ok = compare_results("SC2 : year / sampling_period='09-01' / max", r_out, py_out, "QJXA")
    results.append(ok)

    # ---- Scénario 3 : mean annuel sur fenêtre mai-nov (pas QMNA : pas d'enchaînement mensuel) ----
    data = load_r_csv("sc3_year_sub_window_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = ["05-01", "11-30"],
        rmNApct         = False,
    )
    r_out = load_r_csv("sc3_year_sub_window_output")
    r_out = r_out.rename(columns={"QMNA": "QA"})
    ok = compare_results("SC3 : year / sampling_period=['05-01','11-30'] / mean", r_out, py_out, "QA")
    results.append(ok)

    # ---- Scénario 4 : lacunes, NApct_lim=10 ----
    data = load_r_csv("sc4_year_gaps_napct_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = None,
        NApct_lim       = 10,
        rmNApct         = False,
    )
    r_out = load_r_csv("sc4_year_gaps_napct_output")
    ok = compare_results("SC4 : year / lacunes / NApct_lim=10", r_out, py_out, "QA")
    results.append(ok)

    # ---- Scénario 5 : début tardif, année hydrologique ----
    data = load_r_csv("sc5_year_late_start_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = "09-01",
        rmNApct         = False,
    )
    r_out = load_r_csv("sc5_year_late_start_output")
    ok = compare_results("SC5 : year / sampling_period='09-01' / début tardif", r_out, py_out, "QA")
    results.append(ok)

    # ---- Scénario 6 : mean annuel mai-nov, série démarrant mi-fenêtre ----
    data = load_r_csv("sc6_year_sub_midstart_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = ["05-01", "11-30"],
        rmNApct         = False,
    )
    r_out = load_r_csv("sc6_year_sub_midstart_output")
    r_out = r_out.rename(columns={"QMNA": "QA"})
    ok = compare_results("SC6 : year / ['05-01','11-30'] / début mi-fenêtre", r_out, py_out, "QA", napct_strict=False)
    results.append(ok)

    # ---- Scénario 7 : mean annuel mai-nov, série se terminant mi-fenêtre ----
    data = load_r_csv("sc7_year_sub_midend_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = ["05-01", "11-30"],
        rmNApct         = False,
    )
    r_out = load_r_csv("sc7_year_sub_midend_output")
    r_out = r_out.rename(columns={"QMNA": "QA"})
    ok = compare_results("SC7 : year / ['05-01','11-30'] / fin mi-fenêtre", r_out, py_out, "QA", napct_strict=False)
    results.append(ok)

    # ---- Scénario 8 : départ milieu de mois (03-15) ----
    data = load_r_csv("sc8_year_march15_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = "03-15",
        rmNApct         = False,
    )
    r_out = load_r_csv("sc8_year_march15_output")
    ok = compare_results("SC8 : year / sampling_period='03-15' / milieu de mois", r_out, py_out, "QA")
    results.append(ok)

    # ---- Scénario 9 : sous-fenêtre croisée (11-01 → 04-30) ----
    data = load_r_csv("sc9_year_cross_subwindow_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = ["11-01", "04-30"],
        rmNApct         = False,
    )
    r_out = load_r_csv("sc9_year_cross_subwindow_output")
    ok = compare_results("SC9 : year / ['11-01','04-30'] / sous-fenêtre croisée", r_out, py_out, "QA", napct_strict=False)
    results.append(ok)

    # ---- Scénario 10 : mean annuel mai-nov, NAs dans la fenêtre (pas aux bords) ----
    data = load_r_csv("sc10_year_na_in_window_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step       = "year",
        sampling_period = ["05-01", "11-30"],
        rmNApct         = False,
    )
    r_out = load_r_csv("sc10_year_na_in_window_output")
    r_out = r_out.rename(columns={"QMNA": "QA"})
    ok = compare_results("SC10 : year / NAs dans la fenêtre", r_out, py_out, "QA", napct_strict=False)
    results.append(ok)

    # ---- Scénario 11 : year-month, mean ----
    data = load_r_csv("sc11_yearmonth_default_input")
    py_out = process_extraction(
        data      = data,
        funct     = {"QM": (np.mean, "Q", {"skipna": True})},
        time_step = "year-month",
        rmNApct   = False,
    )
    r_out = load_r_csv("sc11_yearmonth_default_output")
    ok = compare_results("SC11 : year-month / mean", r_out, py_out, "QM", napct_strict=False)
    results.append(ok)

    # ---- Scénario 12 : month, mean ----
    data = load_r_csv("sc12_month_default_input")
    py_out = process_extraction(
        data      = data,
        funct     = {"QM": (np.mean, "Q", {"skipna": True})},
        time_step = "month",
        rmNApct   = False,
    )
    r_out = load_r_csv("sc12_month_default_output")
    ok = compare_results("SC12 : month / mean", r_out, py_out, "QM",
                         merge_on=["ID", "Date"], napct_strict=False)
    results.append(ok)

    # ---- Scénario 13 : year-season, mean ----
    data = load_r_csv("sc13_yearseason_default_input")
    py_out = process_extraction(
        data      = data,
        funct     = {"QS": (np.mean, "Q", {"skipna": True})},
        time_step = "year-season",
        rmNApct   = False,
    )
    r_out = load_r_csv("sc13_yearseason_default_output")
    ok = compare_results("SC13 : year-season / mean", r_out, py_out, "QS", napct_strict=False)
    results.append(ok)

    # ---- Scénario 14 : season, mean ----
    data = load_r_csv("sc14_season_default_input")
    py_out = process_extraction(
        data      = data,
        funct     = {"QS": (np.mean, "Q", {"skipna": True})},
        time_step = "season",
        rmNApct   = False,
    )
    r_out = load_r_csv("sc14_season_default_output")
    ok = compare_results("SC14 : season / mean", r_out, py_out, "QS",
                         merge_on=["ID", "Season"], napct_strict=False)
    results.append(ok)

    # ---- Scénario 15 : yearday, mean ----
    data = load_r_csv("sc15_yearday_default_input")
    py_out = process_extraction(
        data      = data,
        funct     = {"QJA": (np.mean, "Q", {"skipna": True})},
        time_step = "yearday",
        rmNApct   = False,
    )
    r_out = load_r_csv("sc15_yearday_default_output")
    ok = compare_results("SC15 : yearday / mean", r_out, py_out, "QJA",
                         merge_on=["ID", "Yearday"], napct_strict=False)
    results.append(ok)

    # ---- Scénario 16 : none, mean ----
    data = load_r_csv("sc16_none_default_input")
    py_out = process_extraction(
        data      = data,
        funct     = {"QA": (np.mean, "Q", {"skipna": True})},
        time_step = "none",
        rmNApct   = False,
    )
    r_out = load_r_csv("sc16_none_default_output")
    ok = compare_results("SC16 : none / mean", r_out, py_out, "QA",
                         merge_on=["ID"], napct_strict=True)
    results.append(ok)

    # ---- Scénario 17 : is_date, np.argmax avec correction circulaire ----
    # Données SC2 (hydro year 09-01, 2001-2015).
    # Vérifie : type entier, plage, hy=2003 (bissextile), années tronquées.
    data = load_r_csv("sc2_year_hydro_sep_input")
    py_out = process_extraction(
        data            = data,
        funct           = {"tQJXA": (np.argmax, "Q", True)},
        time_step       = "year",
        sampling_period = "09-01",
        rmNApct         = False,
    )
    print(f"\n{'='*60}")
    print(f"  SC17 : is_date / np.argmax / hydro 09-01")
    print(f"{'='*60}")
    ok_sc17 = True

    # 1. Type entier (Int64 nullable)
    if not pd.api.types.is_integer_dtype(py_out["tQJXA"]):
        print(f"  ✗ Type tQJXA attendu int, obtenu {py_out['tQJXA'].dtype}")
        ok_sc17 = False
    else:
        print(f"  ✓ Type tQJXA = {py_out['tQJXA'].dtype}")

    # 2. Années complètes (NApct=0) : valeurs dans [-365, 730]
    full = py_out[py_out["NApct"] == 0.0]["tQJXA"].dropna().astype(float)
    bad = full[(full < -365) | (full > 730)]
    if len(bad) > 0:
        print(f"  ✗ {len(bad)} valeurs hors plage [-365, 730]")
        ok_sc17 = False
    else:
        print(f"  ✓ {len(full)} années complètes dans [-365, 730]")

    # 3. hy=2003 couvre fév 2004 (année bissextile) : valeur présente
    hy2003 = py_out[(py_out["ID"] == "serie_A") & (py_out["Date"].dt.year == 2003)]
    if len(hy2003) != 1:
        print("  ✗ hy=2003 introuvable")
        ok_sc17 = False
    else:
        print(f"  ✓ hy=2003 (fenêtre couvre fév bisextile 2004) : tQJXA={hy2003['tQJXA'].iloc[0]}")

    # 4. Années tronquées hy=2000 / hy=2015 : valeur présente et entière
    #    (la troncature est signalée par NApct > 0, pas par NA : utiliser NApct_lim pour filtrer)
    for hy_lbl in [2000, 2015]:
        row = py_out[(py_out["ID"] == "serie_A") & (py_out["Date"].dt.year == hy_lbl)]
        if len(row) != 1:
            print(f"  ✗ hy={hy_lbl} introuvable")
            ok_sc17 = False
        else:
            v, napct = row["tQJXA"].iloc[0], row["NApct"].iloc[0]
            print(f"  ✓ hy={hy_lbl} (tronqué NApct={napct:.1f}%) : tQJXA={v}")

    print(f"\n  → {'✓ OK' if ok_sc17 else '✗ DIFFÉRENCES'}")
    results.append(ok_sc17)

    # ---- Scénario 18 : dict multi-variables, QJXA + QA en un seul appel ----
    # Vérifie que le résultat combiné est identique à deux appels séparés.
    data = load_r_csv("sc1_year_default_input")
    ref18_qjxa = process_extraction(
        data=data, funct={"QJXA": (np.max,  "Q", {"skipna": True})},
        time_step="year", rmNApct=False,
    )
    ref18_qa = process_extraction(
        data=data, funct={"QA":   (np.mean, "Q", {"skipna": True})},
        time_step="year", rmNApct=False,
    )
    py_out18 = process_extraction(
        data  = data,
        funct = {"QJXA": (np.max,  "Q", {"skipna": True}),
                 "QA":   (np.mean, "Q", {"skipna": True})},
        time_step = "year",
        rmNApct   = False,
    )
    print(f"\n{'='*60}")
    print(f"  SC18 : dict multi-variables / QJXA + QA en un appel")
    print(f"{'='*60}")
    ok_sc18 = True

    required_cols = {"ID", "Date", "QJXA", "QA"}
    if not required_cols.issubset(py_out18.columns):
        print(f"  ✗ Colonnes manquantes : obtenu : {py_out18.columns.tolist()}")
        ok_sc18 = False
    else:
        print(f"  ✓ Colonnes : {py_out18.columns.tolist()}")

    for col, ref in [("QJXA", ref18_qjxa), ("QA", ref18_qa)]:
        merged = py_out18[["ID","Date",col]].merge(ref[["ID","Date",col]], on=["ID","Date"], suffixes=("_c","_r"))
        if not np.allclose(merged[f"{col}_c"].values, merged[f"{col}_r"].values, equal_nan=True):
            print(f"  ✗ {col} : divergence vs appel individuel")
            ok_sc18 = False
        else:
            print(f"  ✓ {col} identique à l'appel individuel ({len(py_out18)} lignes)")

    print(f"\n  → {'✓ OK' if ok_sc18 else '✗ DIFFÉRENCES'}")
    results.append(ok_sc18)

    # ---- Scénario 19 : multi-colonnes, bias(Q_obs, Q_sim) ----
    # Vérifie le chemin groupby.apply multi-colonnes contre calcul numpy direct.
    _base19 = load_r_csv("sc1_year_default_input").copy()
    _rng19  = np.random.default_rng(19)
    _base19["Q_obs"] = _base19["Q"] + _rng19.uniform(-1, 1, len(_base19))
    _base19["Q_sim"] = _base19["Q"] * 0.9 + _rng19.uniform(-0.5, 0.5, len(_base19))
    data19 = _base19.drop(columns=["Q"])

    def _bias(obs: pd.Series, sim: pd.Series) -> float:
        return float((obs - sim).mean())

    py_out19 = process_extraction(
        data      = data19,
        funct     = {"bias": (_bias, "Q_obs", "Q_sim")},
        time_step = "year",
        rmNApct   = False,
    )
    print(f"\n{'='*60}")
    print(f"  SC19 : multi-colonnes / bias(Q_obs, Q_sim)")
    print(f"{'='*60}")
    ok_sc19 = True

    # Vérification sur chaque (station, année)
    n_checked, n_wrong = 0, 0
    for _, row in py_out19.iterrows():
        sub = data19[(data19["ID"] == row["ID"]) & (data19["Date"].dt.year == row["Date"].year)]
        expected = float((sub["Q_obs"] - sub["Q_sim"]).mean())
        if abs(expected - float(row["bias"])) > 1e-10:
            n_wrong += 1
        n_checked += 1
    if n_wrong > 0:
        print(f"  ✗ {n_wrong}/{n_checked} valeurs incorrectes")
        ok_sc19 = False
    else:
        print(f"  ✓ {n_checked} valeurs vérifiées vs numpy direct")
        print(f"  ✓ Colonnes : {py_out19.columns.tolist()}")

    print(f"\n  → {'✓ OK' if ok_sc19 else '✗ DIFFÉRENCES'}")
    results.append(ok_sc19)

    # ---- Scénario 20 : suffix, QA × [obs, sim] → QA_obs + QA_sim ----
    # Vérifie que suffix produit le même résultat que deux appels individuels.
    _base20 = load_r_csv("sc1_year_default_input").copy()
    _base20["Q_obs"] = _base20["Q"] * 1.1
    _base20["Q_sim"] = _base20["Q"] * 0.85
    data20 = _base20.drop(columns=["Q"])

    py_out20 = process_extraction(
        data      = data20,
        funct     = {"QA": (np.mean, "Q")},
        suffix    = ["obs", "sim"],
        time_step = "year",
        rmNApct   = False,
    )
    ref20_obs = process_extraction(
        data=data20, funct={"QA_obs": (np.mean, "Q_obs")},
        time_step="year", rmNApct=False,
    )
    ref20_sim = process_extraction(
        data=data20, funct={"QA_sim": (np.mean, "Q_sim")},
        time_step="year", rmNApct=False,
    )
    print(f"\n{'='*60}")
    print(f"  SC20 : suffix / QA × [obs, sim] → QA_obs + QA_sim")
    print(f"{'='*60}")
    ok_sc20 = True

    if not {"ID", "Date", "QA_obs", "QA_sim"}.issubset(py_out20.columns):
        print(f"  ✗ Colonnes manquantes : obtenu : {py_out20.columns.tolist()}")
        ok_sc20 = False
    else:
        print(f"  ✓ Colonnes : {py_out20.columns.tolist()}")

    for col, ref in [("QA_obs", ref20_obs), ("QA_sim", ref20_sim)]:
        m = py_out20[["ID","Date",col]].merge(ref[["ID","Date",col]], on=["ID","Date"], suffixes=("_s","_r"))
        if not np.allclose(m[f"{col}_s"].values, m[f"{col}_r"].values, equal_nan=True):
            print(f"  ✗ {col} : divergence vs appel individuel")
            ok_sc20 = False
        else:
            print(f"  ✓ {col} identique à l'appel individuel ({len(py_out20)} lignes)")

    print(f"\n  → {'✓ OK' if ok_sc20 else '✗ DIFFÉRENCES'}")
    results.append(ok_sc20)

    # ---- Scénario 21 : keep="all", fan-out vers lignes d'origine ----
    # Paramètre Python uniquement (pas de référence R).
    # Vérifie :
    #   - même nb de lignes que l'entrée
    #   - colonnes d'origine présentes, NApct absent
    #   - valeur sur 1re ligne de chaque (ID, année) = résultat agrégé standard
    #   - non-premières lignes → NaN
    data21 = load_r_csv("sc1_year_default_input")
    ref21 = process_extraction(
        data=data21, funct={"QA": (np.mean, "Q", {"skipna": True})},
        time_step="year", rmNApct=True,
    )
    py_out21 = process_extraction(
        data=data21, funct={"QA": (np.mean, "Q", {"skipna": True})},
        time_step="year", keep="all",
    )

    print(f"\n{'='*60}")
    print(f"  SC21 : keep='all' / year / fan-out vers lignes d'origine")
    print(f"{'='*60}")
    ok_sc21 = True

    if len(py_out21) != len(data21):
        print(f"  ✗ Nb lignes : attendu {len(data21)}, obtenu {len(py_out21)}")
        ok_sc21 = False
    else:
        print(f"  ✓ Nb lignes = nb lignes entrée ({len(data21)})")

    if not set(data21.columns).issubset(set(py_out21.columns)):
        print(f"  ✗ Colonnes d'origine manquantes, obtenu : {py_out21.columns.tolist()}")
        ok_sc21 = False
    else:
        print(f"  ✓ Colonnes d'origine présentes")

    if any(c.startswith("NApct") for c in py_out21.columns):
        print(f"  ✗ NApct présent alors qu'il devrait être absent")
        ok_sc21 = False
    else:
        print(f"  ✓ NApct absent")

    # Valeur sur 1re ligne de chaque (ID, année) == agrégat standard
    py_sorted = py_out21.sort_values(["ID", "Date"]).reset_index(drop=True)
    py_sorted["_year"] = py_sorted["Date"].dt.year
    is_first = ~py_sorted.duplicated(subset=["ID", "_year"], keep="first")
    first_rows = py_sorted.loc[is_first, ["ID", "_year", "QA"]].copy()
    first_rows["Date"] = pd.to_datetime(first_rows["_year"].astype(str) + "-01-01")
    m21 = first_rows.merge(ref21[["ID", "Date", "QA"]], on=["ID", "Date"], suffixes=("_keep", "_ref"))
    if not np.allclose(m21["QA_keep"].values, m21["QA_ref"].values, equal_nan=True):
        print("  ✗ Valeur sur 1re ligne ≠ agrégat standard")
        ok_sc21 = False
    else:
        print(f"  ✓ Valeur sur 1re ligne = agrégat standard ({len(m21)} groupes)")

    # Non-premières lignes → NaN
    non_first_vals = py_sorted.loc[~is_first, "QA"]
    if not non_first_vals.isna().all():
        print(f"  ✗ {non_first_vals.notna().sum()} lignes non-premières ont une valeur non-NaN")
        ok_sc21 = False
    else:
        print(f"  ✓ Non-premières lignes = NaN ({(~is_first).sum()} lignes)")

    print(f"\n  → {'✓ OK' if ok_sc21 else '✗ DIFFÉRENCES'}")
    results.append(ok_sc21)

    # ---- Scénario 22 : NAyear_lim, troncature autour d'une longue lacune ----
    # Paramètre Python uniquement (pas de référence R).
    # Données : série A 2000-2019, lacune 2008-2013 (5 ans+), série B sans lacune.
    # Avec NAyear_lim=3 : la lacune (>3 ans) doit déclencher une troncature.
    # La partie la plus longue est APRÈS la lacune (2014-2019) → données avant 2008 masquées.
    print(f"\n{'='*60}")
    print(f"  SC22 : NAyear_lim / troncature autour d'une longue lacune")
    print(f"{'='*60}")
    ok_sc22 = True

    _dates_a = pd.date_range("2000-01-01", "2019-12-31", freq="D")
    _rng22   = np.random.default_rng(7)
    _q_a     = _rng22.uniform(10, 100, len(_dates_a))
    # Lacune du 2008-01-01 au 2013-12-31 (6 ans consécutifs)
    _gap_mask = (_dates_a >= pd.Timestamp("2008-01-01")) & (_dates_a <= pd.Timestamp("2013-12-31"))
    _q_a[_gap_mask] = np.nan

    _dates_b = pd.date_range("2000-01-01", "2019-12-31", freq="D")
    _q_b     = _rng22.uniform(10, 100, len(_dates_b))   # pas de lacune

    data22 = pd.DataFrame({
        "Date": np.concatenate([_dates_a.to_numpy(), _dates_b.to_numpy()]),
        "Q":    np.concatenate([_q_a, _q_b]),
        "ID":   np.repeat(["A", "B"], len(_dates_a)),
    })

    out22 = process_extraction(
        data=data22,
        funct={"QA": (np.mean, "Q", {"skipna": True})},
        time_step="year",
        NAyear_lim=3,
        rmNApct=False,
    )
    out22_no = process_extraction(
        data=data22,
        funct={"QA": (np.mean, "Q", {"skipna": True})},
        time_step="year",
        rmNApct=False,
    )

    # Série B non modifiée (pas de lacune)
    b22    = out22[out22["ID"]   == "B"]
    b22_no = out22_no[out22_no["ID"] == "B"]
    m22b   = b22.merge(b22_no[["ID","Date","QA"]], on=["ID","Date"], suffixes=("","_ref"))
    if not np.allclose(m22b["QA"].values, m22b["QA_ref"].values, equal_nan=True):
        print("  ✗ Série B (sans lacune) modifiée à tort")
        ok_sc22 = False
    else:
        print("  ✓ Série B (sans lacune) non modifiée")

    # Série A : années avant la lacune (2000-2007) doivent être NaN
    # La lacune est 2008-2013 (>3 ans), après = 2014-2019 (6 ans), avant = 2000-2007 (8 ans).
    # Avant(2008-01-01 - 2000-01-01) = ~8 ans, Après(2019-12-31 - 2013-12-31) = ~6 ans.
    # Avant > Après → garde la partie AVANT → set Date >= 2013-12-31 à NaN.
    a22 = out22[out22["ID"] == "A"].sort_values("Date")
    years_after_gap  = a22[a22["Date"].dt.year >= 2014]["QA"]
    years_before_gap = a22[a22["Date"].dt.year <= 2007]["QA"]
    years_gap        = a22[(a22["Date"].dt.year >= 2008) & (a22["Date"].dt.year <= 2013)]["QA"]

    if not years_before_gap.notna().all():
        print(f"  ✗ Années avant la lacune (2000-2007) devraient avoir des valeurs non-NaN")
        ok_sc22 = False
    else:
        print(f"  ✓ Années avant la lacune (2000-2007) non masquées ({years_before_gap.notna().sum()} valeurs)")

    if not years_after_gap.isna().all():
        print(f"  ✗ Années après la lacune (2014-2019) devraient être NaN")
        ok_sc22 = False
    else:
        print(f"  ✓ Années après la lacune (2014-2019) masquées ({years_after_gap.isna().sum()} valeurs NaN)")

    if not years_gap.isna().all():
        print(f"  ✗ Années de lacune (2008-2013) devraient être NaN")
        ok_sc22 = False
    else:
        print(f"  ✓ Années de lacune (2008-2013) NaN ({years_gap.isna().sum()} valeurs)")

    print(f"\n  → {'✓ OK' if ok_sc22 else '✗ DIFFÉRENCES'}")
    results.append(ok_sc22)

    # ---- Résumé ----
    n_ok = sum(results)
    n_total = len(results)
    print(f"\n{'='*60}")
    print(f"  RÉSUMÉ : {n_ok}/{n_total} scénarios OK")
    print(f"{'='*60}\n")
    sys.exit(0 if n_ok == n_total else 1)


if __name__ == "__main__":
    run_all()
