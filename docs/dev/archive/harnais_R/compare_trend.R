## compare_trend.R : Generates reference MK results for Python validation
## Run from project root:
##   Rscript EXstat_py/compare_trend.R

suppressPackageStartupMessages({
    library(tibble)
    library(dplyr)
})

source("R/tools.R")

outdir <- "EXstat_py/ref_trend"
dir.create(outdir, showWarnings=FALSE)

set.seed(2024)

## ── Series generation ──────────────────────────────────────────────────────

n_long  <- 50    # INDE / AR1 scenarios
n_short <- 30    # LTP scenarios (n^4 loop is slow in R)

# 1. Trending series (slope ~0.1/yr)
t_long  <- 1:n_long
t_short <- 1:n_short
series_trend_long  <- 0.1 * t_long  + rnorm(n_long,  sd=0.5)
series_trend_short <- 0.1 * t_short + rnorm(n_short, sd=0.5)

# 2. Stationary noise
series_stat_long  <- rnorm(n_long,  sd=1)
series_stat_short <- rnorm(n_short, sd=1)

# 3. AR1 process (rho=0.7)
ar1_long <- numeric(n_long)
ar1_long[1] <- rnorm(1)
for (i in 2:n_long)  ar1_long[i]  <- 0.7*ar1_long[i-1]  + rnorm(1, sd=sqrt(1-0.7^2))
ar1_short <- numeric(n_short)
ar1_short[1] <- rnorm(1)
for (i in 2:n_short) ar1_short[i] <- 0.7*ar1_short[i-1] + rnorm(1, sd=sqrt(1-0.7^2))

# 4. Series with ties (rounds values to 1 decimal)
series_ties <- round(rnorm(n_long, sd=1), 1)

# 5. Series with NAs (randomly mask ~15%)
series_na <- series_trend_long
series_na[sample(n_long, round(n_long*0.15))] <- NA

## ── Save all input series ──────────────────────────────────────────────────
series_df <- data.frame(
    trend_long   = series_trend_long,
    stat_long    = series_stat_long,
    ar1_long     = ar1_long,
    ties         = series_ties,
    na_series    = series_na,
    trend_short  = c(series_trend_short, rep(NA, n_long - n_short)),
    stat_short   = c(series_stat_short,  rep(NA, n_long - n_short)),
    ar1_short    = c(ar1_short,          rep(NA, n_long - n_short))
)
write.csv(series_df, file.path(outdir, "input_series.csv"), row.names=FALSE)

## ── Run MK tests and collect results ───────────────────────────────────────

run_mk <- function(label, X, option) {
    res <- generalMannKendall_hide(
        X = X,
        level = 0.1,
        time_dependency_option = option,
        do_detrending = TRUE,
        verbose = FALSE
    )
    data.frame(
        scenario = label,
        option   = option,
        n_valid  = sum(!is.na(X)),
        H        = res$H,
        p        = res$P,
        a        = res$TREND,
        stat     = res$STAT,
        dep      = res$DEP,
        stringsAsFactors = FALSE
    )
}

results <- rbind(
    # INDE scenarios
    run_mk("trend_long",  series_trend_long,  "INDE"),
    run_mk("stat_long",   series_stat_long,   "INDE"),
    run_mk("ar1_long",    ar1_long,           "INDE"),
    run_mk("ties",        series_ties,        "INDE"),
    run_mk("na_series",   series_na,          "INDE"),
    # AR1 scenarios
    run_mk("trend_long",  series_trend_long,  "AR1"),
    run_mk("stat_long",   series_stat_long,   "AR1"),
    run_mk("ar1_long",    ar1_long,           "AR1"),
    run_mk("ties",        series_ties,        "AR1"),
    run_mk("na_series",   series_na,          "AR1"),
    # LTP scenarios (short series for speed)
    run_mk("trend_short", series_trend_short, "LTP"),
    run_mk("stat_short",  series_stat_short,  "LTP"),
    run_mk("ar1_short",   ar1_short,          "LTP")
)

write.csv(results, file.path(outdir, "mk_results.csv"), row.names=FALSE)

cat(sprintf("Wrote %d reference results to %s/\n", nrow(results), outdir))
cat(sprintf("  input_series.csv : %d series × %d rows\n",
            ncol(series_df), nrow(series_df)))
cat("  mk_results.csv   : scenarios × {H, p, a, stat, dep}\n")
