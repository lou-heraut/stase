"""
Benchmark process_extraction — 100 stations x 50 ans (~1.83M lignes)
"""
import time
import numpy as np
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from process_extraction import process_extraction

# ── Génération des données ────────────────────────────────────────────────────
N_STATIONS = 100
START = "1975-01-01"
END   = "2024-12-31"

rng = np.random.default_rng(42)
dates = pd.date_range(START, END, freq="D")
n_days = len(dates)
print(f"Dataset : {N_STATIONS} stations × {n_days} jours = {N_STATIONS*n_days:,} lignes\n")

station_ids = [f"S{i:03d}" for i in range(N_STATIONS)]
data = pd.DataFrame({
    "Date": np.tile(dates, N_STATIONS),
    "Q":    100.0 + rng.standard_normal(N_STATIONS * n_days).cumsum() * 0.01,
    "ID":   np.repeat(station_ids, n_days),
})

# ── Scénarios ─────────────────────────────────────────────────────────────────
scenarios = [
    ("year / default",          dict(time_step="year")),
    ("year / hydro (09-01)",    dict(time_step="year",   sampling_period="09-01")),
    ("year / sub-window",       dict(time_step="year",   sampling_period=["05-01","11-30"])),
    ("year-month",              dict(time_step="year-month")),
    ("month",                   dict(time_step="month")),
    ("year-season",             dict(time_step="year-season")),
    ("season",                  dict(time_step="season")),
    ("yearday",                 dict(time_step="yearday")),
    ("none",                    dict(time_step="none")),
]

REPS = 3
fmt = "{:<32s}  {:>6.3f} s   {:>8,} lignes"
print(f"{'Scénario':<32s}  {'temps':>6}   {'output':>8}")
print("-" * 55)

for label, kw in scenarios:
    times = []
    n_out = None
    for _ in range(REPS):
        t0 = time.perf_counter()
        out = process_extraction(
            data  = data,
            funct = (np.mean, "Q"),
            **kw,
        )
        times.append(time.perf_counter() - t0)
        n_out = len(out)
    print(fmt.format(label, min(times), n_out))

print()
