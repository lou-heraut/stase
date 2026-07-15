## compare_process_trend.R — Generates reference process_trend results
## Run from project root:
##   Rscript EXstat_py/compare_process_trend.R

suppressPackageStartupMessages({
    library(tibble)
    library(dplyr)
    library(tidyr)
    library(lubridate)
})

source("R/tools.R")
source("R/process_trend.R")

outdir <- "EXstat_py/ref_trend"
dir.create(outdir, showWarnings = FALSE)

set.seed(42)

## ── Synthetic input data (mimics process_extraction output) ─────────────────

n_stations <- 8
n_years    <- 30   # keep short enough for LTP to be feasible

station_ids <- paste0("S", sprintf("%02d", seq_len(n_stations)))
years <- seq(as.Date("1990-01-01"), by = "year", length.out = n_years)

# Two variables: QA (annual mean, trending) and QJXA (annual max, stationary)
set.seed(42)
rows <- lapply(station_ids, function(sid) {
    qa   <- 50 + 0.5 * seq_len(n_years) + rnorm(n_years, sd = 5)
    qjxa <- 200 + rnorm(n_years, sd = 20)
    # Introduce ~10% NAs in QA
    na_idx <- sample(n_years, max(1, round(n_years * 0.1)))
    qa[na_idx] <- NA
    data.frame(
        ID   = sid,
        Date = years,
        QA   = qa,
        QJXA = qjxa,
        stringsAsFactors = FALSE
    )
})
dataEX <- dplyr::bind_rows(rows)
dataEX$Date <- as.Date(dataEX$Date)
dataEX <- tibble::as_tibble(dataEX)

write.csv(dataEX, file.path(outdir, "process_trend_input.csv"), row.names = FALSE)
cat(sprintf("Input: %d rows × %d cols\n", nrow(dataEX), ncol(dataEX)))

## ── Helper to save results ───────────────────────────────────────────────────
save_result <- function(result, filename) {
    # Flatten list columns (period_trend, mean_period_change) for CSV export
    df <- result

    # period_trend list column → two date columns
    if ("period_trend" %in% names(df)) {
        df$period_trend_start <- as.Date(sapply(df$period_trend, `[[`, 1))
        df$period_trend_end   <- as.Date(sapply(df$period_trend, `[[`, 2))
        df$period_trend <- NULL
    }

    # mean_period_change list column → two numeric columns
    if ("mean_period_change" %in% names(df)) {
        df$mean_period_change_1 <- sapply(df$mean_period_change, `[[`, 1)
        df$mean_period_change_2 <- sapply(df$mean_period_change, `[[`, 2)
        df$mean_period_change <- NULL
    }

    # period_change list column → four date columns
    if ("period_change" %in% names(df)) {
        df$period_change_start_1 <- as.Date(sapply(df$period_change, function(x) x[[1]][1]))
        df$period_change_end_1   <- as.Date(sapply(df$period_change, function(x) x[[1]][2]))
        df$period_change_start_2 <- as.Date(sapply(df$period_change, function(x) x[[2]][1]))
        df$period_change_end_2   <- as.Date(sapply(df$period_change, function(x) x[[2]][2]))
        df$period_change <- NULL
    }

    write.csv(df, file.path(outdir, filename), row.names = FALSE)
    cat(sprintf("  Wrote %s (%d rows)\n", filename, nrow(df)))
}

## ── SC1: INDE, to_normalise=TRUE ─────────────────────────────────────────────
cat("\nSC1: INDE, to_normalise=TRUE\n")
res1 <- process_trend(
    dataEX  = dataEX,
    MK_level = 0.1,
    time_dependency_option = "INDE",
    to_normalise = TRUE,
    verbose = FALSE
)
save_result(res1, "pt_sc1_inde_norm.csv")

## ── SC2: AR1, to_normalise=FALSE ─────────────────────────────────────────────
cat("\nSC2: AR1, to_normalise=FALSE\n")
res2 <- process_trend(
    dataEX  = dataEX,
    MK_level = 0.1,
    time_dependency_option = "AR1",
    to_normalise = FALSE,
    verbose = FALSE
)
save_result(res2, "pt_sc2_ar1_nonorm.csv")

## ── SC3: INDE, period_trend filter ───────────────────────────────────────────
cat("\nSC3: INDE, period_trend=1995–2010\n")
res3 <- process_trend(
    dataEX  = dataEX,
    MK_level = 0.1,
    time_dependency_option = "INDE",
    to_normalise = TRUE,
    period_trend = c(as.Date("1995-01-01"), as.Date("2010-12-31")),
    verbose = FALSE
)
save_result(res3, "pt_sc3_inde_period.csv")

## ── SC4: INDE, period_change ──────────────────────────────────────────────────
cat("\nSC4: INDE, period_change\n")
res4 <- process_trend(
    dataEX  = dataEX,
    MK_level = 0.1,
    time_dependency_option = "INDE",
    to_normalise = TRUE,
    period_change = list(
        c(as.Date("1990-01-01"), as.Date("2004-12-31")),
        c(as.Date("2005-01-01"), as.Date("2019-12-31"))
    ),
    verbose = FALSE
)
save_result(res4, "pt_sc4_inde_change.csv")

## ── SC5: extreme_take_not_signif_into_account=FALSE ──────────────────────────
cat("\nSC5: extreme_take_not_signif_into_account=FALSE\n")
res5 <- process_trend(
    dataEX  = dataEX,
    MK_level = 0.1,
    time_dependency_option = "INDE",
    to_normalise = TRUE,
    extreme_take_not_signif_into_account = FALSE,
    verbose = FALSE
)
save_result(res5, "pt_sc5_extreme_nosignif.csv")

cat("\nDone.\n")
