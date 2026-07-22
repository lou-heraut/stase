"""Benchmark stase sur données réelles RRSE (228 séries, ~5,16M lignes).

Données : EXstat_project/EXstat_Claude/data_test/RRSE_csv/ (non commitées ici).
Usage : .python_env/bin/python benchmarks/bench_rrse.py

Référence (2026-07-12, après optimisations tri/doublons, fan-out aligné,
argmax positionnel Cython) :
    QA 1.8s · QJXA 1.7s · tQJXA 3.0s · QMNA 2.5s · VCN10 2.9s ·
    4 vars 2.7s · trend 0.2s, total ~14.9s (avant : ~24.9s)
"""
import sys
import time
import glob
import warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import numpy as np
import pandas as pd
warnings.simplefilter("ignore")
from stase import process_extraction, process_trend

DATA = str(Path(__file__).resolve().parent.parent.parent
           / "EXstat_Claude" / "data_test" / "RRSE_csv")

t0 = time.perf_counter()
parts = []
for f in sorted(glob.glob(f"{DATA}/*.csv")):
    df = pd.read_csv(f, parse_dates=["date"])
    parts.append(df)
data = pd.concat(parts, ignore_index=True)
t_load = time.perf_counter() - t0
print(f"chargement      {t_load:6.2f}s   {len(data):,} lignes, {data['code'].nunique()} séries")

def bench(label, fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    n = len(out) if hasattr(out, "__len__") else "-"
    print(f"{label:15s} {dt:6.2f}s   {n} lignes")
    return out, dt

results = {}
_, results["QA"] = bench("QA", lambda: process_extraction(
    data, func={"QA": (np.nanmean, "Qm3s")}, time_step="year"))
qa, _ = bench("QA(bis)", lambda: process_extraction(
    data, func={"QA": (np.nanmean, "Qm3s")}, time_step="year"))
_, results["QJXA"] = bench("QJXA 09-01", lambda: process_extraction(
    data, func={"QJXA": (np.nanmax, "Qm3s")}, time_step="year",
    sampling_period="09-01"))
_, results["tQJXA"] = bench("tQJXA is_date", lambda: process_extraction(
    data, func={"tQJXA": (np.nanargmax, "Qm3s", True)}, time_step="year",
    sampling_period="09-01"))

def qmna():
    m = process_extraction(data, func={"QM": (np.nanmean, "Qm3s")},
                           time_step="year-month")
    return process_extraction(m, func={"QMNA": (np.nanmin, "QM")},
                              time_step="year")
_, results["QMNA"] = bench("QMNA 2 etapes", qmna)

def vcn10():
    def roll10(x):
        return pd.Series(np.asarray(x, float)).rolling(10, min_periods=10).mean().to_numpy()
    r = process_extraction(data, func={"Q10": (roll10, "Qm3s")},
                           time_step="none", keep="all")
    return process_extraction(r, func={"VCN10": (np.nanmin, "Q10")},
                              time_step="year", sampling_period="09-01")
_, results["VCN10"] = bench("VCN10 roll+min", vcn10)

# multi-variables en un appel (cas card typique)
_, results["multi4"] = bench("4 vars 1 appel", lambda: process_extraction(
    data, func={"QA": (np.nanmean, "Qm3s"), "QJXA": (np.nanmax, "Qm3s"),
                 "QNA": (np.nanmin, "Qm3s"), "QMED": (np.nanmedian, "Qm3s")},
    time_step="year"))

_, results["trend"] = bench("trend INDE", lambda: process_trend(qa, verbose=False))

print(f"\nTOTAL extraction+trend : {sum(results.values()):.1f}s (hors chargement)")
