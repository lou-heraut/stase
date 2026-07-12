# Copyright           Benjamin Renard <benjamin.renard@inrae.fr>*2
#           2021-2026 Louis Héraut <louis.heraut@inrae.fr>*1
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
EXstat — Statistical tools (faithful Python conversion of tools.R)

Mann-Kendall (INDE / AR1 / LTP), Sen-Theil slope, FDR field significance.

References
----------
Hamed & Rao (1998) A modified Mann-Kendall trend test for autocorrelated
    data. J. Hydrol., 204(1-4): 182-196.
Hamed (2008) Trend detection in hydrologic data: The Mann-Kendall trend
    test under the scaling hypothesis. J. Hydrol., 349(3-4): 350-363.
Benjamini & Hochberg (1995) Controlling the false discovery rate.
    J. R. Stat. Soc. B, 57: 289-300.
"""

import warnings
import numpy as np
from scipy import stats as scipy_stats
from scipy import optimize as scipy_optimize


# ── 1. MANN-KENDALL ──────────────────────────────────────────────────────────

def getMKStat(X):
    """MK statistic S and Sen's slope.

    X may contain NaN; pairs where either value is NaN are skipped.

    Returns
    -------
    dict  {"stat": S, "trend": Sen_slope}
    """
    X = np.asarray(X, dtype=float)
    n = len(X)
    # All pairs (i, j) with j > i  (upper-triangle indices)
    i_idx, j_idx = np.triu_indices(n, k=1)
    Xi, Xj = X[i_idx], X[j_idx]
    valid = ~(np.isnan(Xi) | np.isnan(Xj))
    Xi_v, Xj_v = Xi[valid], Xj[valid]
    gaps = (j_idx - i_idx)[valid]  # j - i same in R (1-based) and Python (0-based)

    slopes = (Xj_v - Xi_v) / gaps
    stat = int(np.sum(Xj_v > Xi_v) - np.sum(Xj_v < Xi_v))
    trend = float(np.median(slopes)) if len(slopes) > 0 else np.nan
    return {"stat": stat, "trend": trend}


def getTiesCorrection(Z):
    """Variance correction for ties in MK test.

    Parameters
    ----------
    Z : array-like, NA-free

    Returns
    -------
    float  — ties correction (subtract from basic variance)
    """
    Z = np.asarray(Z, dtype=float)
    _, counts = np.unique(Z, return_counts=True)
    # For each unique group size t, count how many groups have that size
    unique_t, n_groups = np.unique(counts, return_counts=True)
    correction = float(np.sum(n_groups * unique_t * (unique_t - 1) * (2 * unique_t + 5)) / 18)
    return correction


def getAR1Correction(Z):
    """Variance correction for AR(1) autocorrelation (Hamed & Rao 1998).

    Parameters
    ----------
    Z : array-like, may contain NaN  (full-length series)

    Returns
    -------
    dict  {"lag1": rho_1, "correction": n_s/n}
    """
    Z = np.asarray(Z, dtype=float)
    n = len(Z)          # full length including NaNs — matches R's n
    Z0 = Z[~np.isnan(Z)]
    m = np.mean(Z0)

    x = Z[:-1]          # Z[1:(n-1)] in R
    y = Z[1:]           # Z[2:n]   in R
    mask = ~(np.isnan(x) | np.isnan(y))
    lag1 = float(np.sum((x[mask] - m) * (y[mask] - m)) / np.sum((Z0 - m) ** 2))

    # Σ_{i=1}^{n-2} (n-i)(n-i-1)(n-i-2) * lag1^i
    i_arr = np.arange(1, n - 1, dtype=float)   # i = 1 .. n-2
    w = (n - i_arr) * (n - i_arr - 1) * (n - i_arr - 2) * (lag1 ** i_arr)
    correction = float(1.0 + (2.0 / (n * (n - 1) * (n - 2))) * np.sum(w))
    return {"lag1": lag1, "correction": correction}


def randomizedNormalScore(x, rng=None):
    """Randomized normal-score transformation (handles ties and NaN).

    Replicates R's rank(x, ties.method="random", na.last="keep") / (1+n_valid).
    NaN positions are preserved as NaN in the output.

    Parameters
    ----------
    x   : array-like
    rng : None | int | numpy.random.Generator
        Source of randomness for tie-breaking. None (default) draws a
        fresh non-deterministic generator — same statistical behaviour
        as R's ties.method="random", but without touching numpy's
        global random state. Pass an int (seed) or a Generator for
        reproducible results.

    Note: the tie randomization is an implementation choice inherited
    from tools.R (Hamed 2008 does not specify tie handling at the
    normal-score step — see the R docstring). For continuous data
    (no ties) the result is fully deterministic and matches R exactly,
    whatever `rng`.
    """
    rng = np.random.default_rng(rng)
    x = np.asarray(x, dtype=float)
    n_valid = int(np.sum(~np.isnan(x)))
    z = np.full_like(x, np.nan)
    valid_mask = ~np.isnan(x)
    valid_x = x[valid_mask]

    # Assign random ranks within tied groups (mirrors R ties.method="random")
    unique_vals, inverse = np.unique(valid_x, return_inverse=True)
    ranks = np.empty(len(valid_x), dtype=float)
    base = 0
    for idx in range(len(unique_vals)):
        group_mask = inverse == idx
        sz = int(np.sum(group_mask))
        group_ranks = np.arange(base + 1, base + sz + 1, dtype=float)
        rng.shuffle(group_ranks)
        ranks[group_mask] = group_ranks
        base += sz

    p = ranks / (1 + n_valid)
    z[valid_mask] = scipy_stats.norm.ppf(p)
    return z


def HurstLkh(H, x):
    """Log-likelihood for Hurst-coefficient MLE.

    Parameters
    ----------
    H : float  — candidate Hurst coefficient
    x : array-like  — normal-score-transformed series (NaN allowed)

    Returns
    -------
    float  — log-likelihood value (maximise over H)
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    # Build n×n covariance matrix CnH
    lags = np.abs(np.arange(n)[:, None] - np.arange(n)[None, :])
    CnH = 0.5 * (np.abs(lags + 1) ** (2 * H)
                 - 2 * np.abs(lags) ** (2 * H)
                 + np.abs(lags - 1) ** (2 * H))

    mask = ~np.isnan(x)
    m = int(np.sum(mask))
    v0 = scipy_stats.norm.ppf(np.arange(1, m + 1) / (m + 1))
    g0 = float(np.var(v0, ddof=1))    # R's var() uses n-1

    CnH_sub = CnH[np.ix_(mask, mask)]
    x_sub = x[mask]

    sign, logdet = np.linalg.slogdet(CnH_sub)   # stable log-determinant
    if sign <= 0:
        return -np.inf
    L = (-0.5 * logdet
         - float(x_sub @ np.linalg.solve(CnH_sub, x_sub)) / (2 * g0))
    return float(L)


def estimateHurst(Z, do_detrending=True, trend=None, rng=None):
    """Estimate the Hurst coefficient by MLE.

    Parameters
    ----------
    Z  : array-like  — full series (NaN allowed for gapped data)
    do_detrending : bool
    trend : float or None  — pre-computed Sen slope (None → compute)
    rng : None | int | numpy.random.Generator — tie-breaking randomness
        (see randomizedNormalScore); only matters when the detrended
        series contains ties.
    """
    Z = np.asarray(Z, dtype=float)
    n = len(Z)
    if trend is None:
        trend = getMKStat(Z)["trend"]

    if do_detrending:
        Y = Z - trend * np.arange(1, n + 1, dtype=float)  # 1-based positions (= R)
    else:
        Y = Z.copy()

    W = randomizedNormalScore(Y, rng=rng)

    result = scipy_optimize.minimize_scalar(
        lambda H: -HurstLkh(H, W),
        bounds=(0.5, 1.0 - 1e-9),
        method='bounded',
    )
    return float(result.x)


# ── LTP variance: 4-level loop (naive reference + vectorized) ───────────────

def _ltp_variance_naive(C, n):
    """O(n^4) reference — same iteration order as tools.R.

    j in [2..n] (R) ↔ [1..n-1] (Python 0-based)
    i in [1..j-1]   ↔ [0..j-1]
    l in [2..n]      ↔ [1..n-1]
    k in [1..l-1]    ↔ [0..l-1]
    C is 0-based (C[lag] = R's C[lag+1]).
    """
    var0 = 0.0
    for j in range(1, n):
        for i in range(j):
            dij = 2.0 - 2.0 * C[j - i]  # lag j-i (always >0)
            for l in range(1, n):
                dkl = 2.0 - 2.0 * C[l - 0]  # placeholder; computed per k below
                for k in range(l):
                    dkl = 2.0 - 2.0 * C[l - k]
                    num = C[abs(j - l)] - C[abs(i - l)] - C[abs(j - k)] + C[abs(i - k)]
                    den = np.sqrt(dij * dkl)
                    var0 += np.arcsin(num / den)
    return var0


def _ltp_variance_vectorized(C, n, block_elems=2 ** 24):
    """Vectorized O(M^2) version of the 4-level LTP loop (M = n*(n-1)/2).

    Produces results identical to _ltp_variance_naive within floating-point
    precision (verified by tests/test_tools.py).

    The M×M computation is evaluated by row blocks of at most
    `block_elems` elements so memory stays bounded (~a few hundred MB)
    whatever n — the full M×M matrices would need (n(n-1)/2)^2 floats,
    i.e. >3 GB from n≈200. Same sum, block by block; for the usual
    annual series (n ≤ ~90) a single block is used and the computation
    is identical to the previous non-blocked version.
    """
    if n < 2:
        return 0.0
    # All pairs (i, j) with j > i  [j ∈ 1..n-1, i ∈ 0..n-2 in 0-based]
    i_arr, j_arr = np.triu_indices(n, k=1)   # shape (M,)
    M = len(i_arr)

    lags_ij = j_arr - i_arr                  # always > 0
    d = (2.0 - 2.0 * C[lags_ij]).astype(float)  # denominator factor per pair

    L = j_arr[None, :]   # (1, M)   — second pair uses same (j,i) set as (l,k)
    K = i_arr[None, :]   # (1, M)

    block = max(1, int(block_elems) // M)
    total = 0.0
    for s in range(0, M, block):
        e = min(s + block, M)
        J = j_arr[s:e, None]   # (b, 1)
        I = i_arr[s:e, None]   # (b, 1)

        num = (C[np.abs(J - L)]
               - C[np.abs(I - L)]
               - C[np.abs(J - K)]
               + C[np.abs(I - K)])

        den = np.sqrt(d[s:e, None] * d[None, :])

        # Clip to [-1, 1] to guard against tiny floating-point overflows
        # in arcsin
        ratio = np.clip(num / den, -1.0, 1.0)
        total += float(np.sum(np.arcsin(ratio)))
    return total


# Public alias — use vectorized by default
_ltp_variance = _ltp_variance_vectorized


def generalMannKendall_hide(X, level=0.1, time_dependency_option='INDE',
                             do_detrending=True, verbose=False, rng=None):
    """Core Mann-Kendall test (faithful Python port of generalMannKendall_hide).

    Parameters
    ----------
    X     : array-like, regularly spaced; NaN fills gaps
    level : float in (0,1)
    time_dependency_option : 'INDE' | 'AR1' | 'LTP'
    do_detrending : bool  (only used for LTP)
    verbose : bool

    Returns
    -------
    dict  {"H": bool|None, "P": float|None, "STAT": float|None,
           "TREND": float|None, "DEP": float|None}
    """
    OUT = {"H": None, "P": None, "STAT": None, "TREND": None, "DEP": None}

    if time_dependency_option not in ('INDE', 'AR1', 'LTP'):
        if verbose:
            warnings.warn('Unknown time_dependency_option')
        return OUT

    X = np.asarray(X, dtype=float)
    Z = X[~np.isnan(X)]
    n = len(Z)

    if n < 3:
        if verbose:
            warnings.warn('less than 3 non-missing values')
        return OUT

    mk = getMKStat(X)
    MK = mk["stat"]
    OUT["TREND"] = mk["trend"]

    # ── INDE / AR1 ───────────────────────────────────────────────────────────
    if time_dependency_option in ('INDE', 'AR1'):
        var0 = n * (n - 1) * (2 * n + 5) / 18.0
        var1 = var0 - getTiesCorrection(Z)
        if np.isnan(var1):
            if verbose:
                warnings.warn('NA variance')
            return OUT
        if var1 <= 0:
            if verbose:
                warnings.warn('negative variance')
            return OUT

        if time_dependency_option == 'AR1':
            ar1 = getAR1Correction(X)       # passes full X (with NaN)
            correction = ar1["correction"]
            OUT["DEP"] = ar1["lag1"]
        else:
            correction = 1.0
            OUT["DEP"] = 0.0

        MKvar = var1 * correction
        if MKvar <= 0:
            if verbose:
                warnings.warn('negative variance')
            return OUT

    # ── LTP ──────────────────────────────────────────────────────────────────
    else:  # LTP
        Hu = estimateHurst(X, do_detrending, OUT["TREND"], rng=rng)
        OUT["DEP"] = Hu

        # C[k] = 0.5*(|k+1|^{2H} - 2|k|^{2H} + |k-1|^{2H}), k = 0..n
        # n here = NA-free count (matches R)
        lam = np.arange(n + 1, dtype=float)
        C = 0.5 * (np.abs(lam + 1) ** (2 * Hu)
                   - 2 * np.abs(lam) ** (2 * Hu)
                   + np.abs(lam - 1) ** (2 * Hu))

        var0 = _ltp_variance(C, n)
        var1 = (2.0 / np.pi) * var0

        if np.isnan(var1):
            if verbose:
                warnings.warn('NA variance')
            return OUT
        if var1 <= 0:
            if verbose:
                warnings.warn('negative variance')
            return OUT

        # Bias correction polynomial (Hamed 2008)
        a0 = (1.0024 * n -   2.5681) / (n + 18.6693)
        a1 = (-2.2510 * n + 157.2075) / (n +  9.2245)
        a2 = (15.3402 * n - 188.6140) / (n +  5.8917)
        a3 = (-31.4258 * n + 549.8599) / (n -  1.1040)
        a4 = (20.7988 * n - 419.0402) / (n -  1.9248)
        B = a0 + a1 * Hu + a2 * Hu ** 2 + a3 * Hu ** 3 + a4 * Hu ** 4
        MKvar = var1 * B

        if MKvar <= 0:
            if verbose:
                warnings.warn('negative variance')
            return OUT

    # ── Final step ───────────────────────────────────────────────────────────
    if MK > 0:
        stat = (MK - 1) / np.sqrt(MKvar)
    elif MK < 0:
        stat = (MK + 1) / np.sqrt(MKvar)
    else:
        stat = 0.0

    OUT["STAT"] = float(stat)
    OUT["P"] = float(2.0 * scipy_stats.norm.cdf(-abs(stat)))
    OUT["H"] = bool(OUT["P"] < level)
    return OUT


def GeneralMannKendall(X, level=0.1, time_dependency_option='INDE',
                        do_detrending=True, show_advance_stat=False,
                        verbose=False, rng=None):
    """Public wrapper — returns dict {level, H, p, a [, stat, dep]}.

    Mirrors R's GeneralMannKendall tibble output.

    rng : None | int | numpy.random.Generator — LTP only : source du
        tirage aléatoire des ex-æquo (cf. randomizedNormalScore). Sans
        effet pour INDE/AR1 et pour les séries sans ex-æquo.
    """
    res = generalMannKendall_hide(
        X=X, level=level,
        time_dependency_option=time_dependency_option,
        do_detrending=do_detrending,
        verbose=verbose,
        rng=rng,
    )
    out = {
        "level": level,
        "H":     res["H"],
        "p":     res["P"],
        "a":     res["TREND"],
    }
    if show_advance_stat:
        out["stat"] = res["STAT"]
        out["dep"]  = res["DEP"]
    return out


# ── 2. FDR FIELD SIGNIFICANCE ────────────────────────────────────────────────

def fieldSignificance_FDR(pvals, level=0.1):
    """FDR field significance (Benjamini & Hochberg 1995).

    Parameters
    ----------
    pvals : array-like  — local p-values
    level : float

    Returns
    -------
    float  — pFDR threshold; local p-values ≤ pFDR are field-significant.
             Returns 0 if no site is field-significant.
    """
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    z = np.sort(pvals)
    thresholds = (level / n) * np.arange(1, n + 1, dtype=float)
    local = z <= thresholds
    if not np.any(local):
        return 0.0
    return float(z[int(np.max(np.where(local)))])
