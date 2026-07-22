"""
benchmark_real.py — process_extraction + process_trend sur 228 stations réelles
(data_test/RRSE_csv/ : ~5M lignes journalières de débit)

Run from project root:
    EXstat_py/python_env/bin/python3 EXstat_py/benchmark_real.py
"""
import sys, os, glob, time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
from process_extraction import process_extraction
from process_trend import process_trend

DATADIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "data_test", "RRSE_csv")

# ── 0. Chargement séquentiel ──────────────────────────────────────────────────
files = sorted(glob.glob(os.path.join(DATADIR, "*.csv")))

def _read(f):
    return pd.read_csv(f, parse_dates=["date"])

t0 = time.perf_counter()
raw = pd.concat([_read(f) for f in files], ignore_index=True)
raw = raw.rename(columns={"date": "Date", "code": "ID"})
t_load_seq = time.perf_counter() - t0

n_stations = raw["ID"].nunique()
n_rows     = len(raw)
print(f"Dataset : {n_stations} stations × {n_rows:,} lignes")
print(f"Chargement séquentiel : {t_load_seq:.2f}s")

# ── 0b. Chargement parallèle (ThreadPoolExecutor) ────────────────────────────
t0 = time.perf_counter()
with ThreadPoolExecutor() as pool:
    dfs = list(pool.map(_read, files))
raw_par = pd.concat(dfs, ignore_index=True)
raw_par = raw_par.rename(columns={"date": "Date", "code": "ID"})
t_load_par = time.perf_counter() - t0
print(f"Chargement parallèle  : {t_load_par:.2f}s  "
      f"(speedup {t_load_seq/t_load_par:.1f}×)\n")

# Use the already-loaded raw for the rest of the benchmark
fmt = "  {:<32s}  {:>6.3f} s   {:>8,} lignes"
sep = "  " + "-" * 58

print(f"  {'Scénario':<32s}  {'temps':>6}   {'output':>8}")
print(sep)

timings = {}

# ── 1. QA — mean annuel, année civile ────────────────────────────────────────
t0 = time.perf_counter()
qa = process_extraction(
    raw,
    funct={"QA": (np.mean, "Qm3s")},
    time_step="year",
    verbose=False,
)
timings["QA"] = time.perf_counter() - t0
print(fmt.format("QA  (year mean, civile)", timings["QA"], len(qa)))

# ── 2. QJXA — max annuel, année hydrologique ─────────────────────────────────
t0 = time.perf_counter()
qjxa = process_extraction(
    raw,
    funct={"QJXA": (np.max, "Qm3s")},
    time_step="year",
    sampling_period="09-01",
    verbose=False,
)
timings["QJXA"] = time.perf_counter() - t0
print(fmt.format("QJXA (year max, 09-01)", timings["QJXA"], len(qjxa)))

# ── 3. tQJXA — date du max annuel ────────────────────────────────────────────
t0 = time.perf_counter()
tqjxa = process_extraction(
    raw,
    funct={"tQJXA": (np.argmax, "Qm3s", True)},
    time_step="year",
    sampling_period="09-01",
    verbose=False,
)
timings["tQJXA"] = time.perf_counter() - t0
print(fmt.format("tQJXA (argmax + is_date, 09-01)", timings["tQJXA"], len(tqjxa)))

# ── 4. QMNA — mean mensuel → min annuel ──────────────────────────────────────
t0 = time.perf_counter()
_monthly = process_extraction(
    raw,
    funct={"Qm3s": (np.mean, "Qm3s")},
    time_step="year-month",
    verbose=False,
)
qmna = process_extraction(
    _monthly,
    funct={"QMNA": (np.min, "Qm3s")},
    time_step="year",
    verbose=False,
)
timings["QMNA"] = time.perf_counter() - t0
print(fmt.format("QMNA (year-month → year min)", timings["QMNA"], len(qmna)))

# ── 5. VCN10 — rolling(10).mean → year min ───────────────────────────────────
t0 = time.perf_counter()
raw_s = raw.sort_values(["ID", "Date"])
roll10 = (
    raw_s.groupby("ID", sort=False)["Qm3s"]
    .transform(lambda x: x.rolling(10, min_periods=10).mean())
)
raw_vcn = raw_s.copy()
raw_vcn["Qm3s_roll10"] = roll10.values
vcn10 = process_extraction(
    raw_vcn,
    funct={"VCN10": (np.min, "Qm3s_roll10")},
    time_step="year",
    sampling_period="09-01",
    verbose=False,
)
timings["VCN10"] = time.perf_counter() - t0
print(fmt.format("VCN10 (rolling10 → year min)", timings["VCN10"], len(vcn10)))

# ── 6. process_trend sur QA ──────────────────────────────────────────────────
print()
print(f"  {'process_trend':<32s}  {'temps':>6}   {'output':>8}")
print(sep)

t0 = time.perf_counter()
trend_qa = process_trend(
    qa,
    MK_level=0.1,
    time_dependency_option="INDE",
    to_normalise=True,
    verbose=False,
)
timings["trend_QA"] = time.perf_counter() - t0
print(fmt.format("trend QA (INDE)", timings["trend_QA"], len(trend_qa)))

t0 = time.perf_counter()
trend_qjxa = process_trend(
    qjxa,
    MK_level=0.1,
    time_dependency_option="INDE",
    to_normalise=True,
    verbose=False,
)
timings["trend_QJXA"] = time.perf_counter() - t0
print(fmt.format("trend QJXA (INDE)", timings["trend_QJXA"], len(trend_qjxa)))

# ── Résumé ────────────────────────────────────────────────────────────────────
t_extraction = sum(timings[k] for k in ["QA", "QJXA", "tQJXA", "QMNA", "VCN10"])
t_trend      = sum(timings[k] for k in ["trend_QA", "trend_QJXA"])
t_total_seq  = t_load_seq + t_extraction + t_trend
t_total_par  = t_load_par + t_extraction + t_trend

print()
print(f"  {'── Résumé':<32s}  {'temps':>6}")
print(sep)
print(f"  {'Chargement (séquentiel)':<32s}  {t_load_seq:>6.3f} s")
print(f"  {'Chargement (parallèle)':<32s}  {t_load_par:>6.3f} s")
print(f"  {'Total process_extraction':<32s}  {t_extraction:>6.3f} s")
print(f"  {'Total process_trend (INDE)':<32s}  {t_trend:>6.3f} s")
print(f"  {'TOTAL (chargement séq.)':<32s}  {t_total_seq:>6.3f} s")
print(f"  {'TOTAL (chargement paral.)':<32s}  {t_total_par:>6.3f} s")
print()

# ── Aperçu résultats ──────────────────────────────────────────────────────────
print("Aperçu trend_qa (5 premières lignes) :")
print(trend_qa[["ID", "variable_en", "H", "p", "a", "a_normalise"]].head())
