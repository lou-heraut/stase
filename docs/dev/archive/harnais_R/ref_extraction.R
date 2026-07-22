# Script de référence pour la comparaison R vs Python
# Doit être lancé depuis la racine du projet :
#   Rscript EXstat_py/ref_extraction.R
#
# Génère des données aléatoires simples, fait tourner process_extraction R,
# et sauvegarde les inputs/outputs en CSV pour comparison Python.

suppressMessages({
    devtools::load_all(quiet=TRUE)
    library(dplyr)
})

OUT_DIR = file.path("EXstat_py", "ref_output")
dir.create(OUT_DIR, showWarnings=FALSE, recursive=TRUE)

save_scenario = function(name, data_input, data_output) {
    write.csv(data_input,
              file.path(OUT_DIR, paste0(name, "_input.csv")),
              row.names=FALSE)
    write.csv(data_output,
              file.path(OUT_DIR, paste0(name, "_output.csv")),
              row.names=FALSE)
    cat(sprintf("  [OK] %s  (%d lignes output)\n", name, nrow(data_output)))
}


## Données de base : 2 séries, 2001-01-01 à 2015-12-31, continue, sans NA ----
set.seed(42)
Start = as.Date("2001-01-01")
End   = as.Date("2015-12-31")
Date  = seq.Date(Start, End, by="day")

make_data = function(seed, id, na_rows=NULL) {
    set.seed(seed)
    d = tibble(
        Date = Date,
        Q    = 100 + cumsum(rnorm(length(Date), 0, 1)),
        ID   = id
    )
    if (!is.null(na_rows)) {
        d$Q[na_rows] = NA
    }
    d
}

data_clean = bind_rows(
    make_data(1, "serie_A"),
    make_data(2, "serie_B")
)

# Données avec lacunes (pour NApct) : 80 jours NA consécutifs en 2005
na_days = which(Date >= as.Date("2005-03-01") & Date <= as.Date("2005-05-19"))
data_gaps = bind_rows(
    make_data(1, "serie_A", na_rows=na_days),
    make_data(2, "serie_B")
)

cat("=== Scénarios de référence ===\n")


## Scénario 1 : année civile complète, sampling_period=NULL, funct=mean --------
cat("\nScénario 1 : year, sampling_period=NULL, mean\n")
out_1 = process_extraction(
    data           = data_clean,
    funct          = list(QA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= NULL,
    rmNApct        = FALSE
)
save_scenario("sc1_year_default", data_clean, out_1)


## Scénario 2 : année hydrologique (début sept.), sampling_period="09-01", max -
cat("\nScénario 2 : year, sampling_period='09-01', max\n")
out_2 = process_extraction(
    data           = data_clean,
    funct          = list(QJXA=max),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= "09-01",
    rmNApct        = FALSE
)
save_scenario("sc2_year_hydro_sep", data_clean, out_2)


## Scénario 3 : fenêtre sous-annuelle (mai→nov), sampling_period=c("05-01","11-30") ---
cat("\nScénario 3 : year, sampling_period=c('05-01','11-30'), mean\n")
out_3 = process_extraction(
    data           = data_clean,
    funct          = list(QMNA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= c("05-01", "11-30"),
    rmNApct        = FALSE
)
save_scenario("sc3_year_sub_window", data_clean, out_3)


## Scénario 4 : avec lacunes, NApct_lim=10 ------------------------------------
cat("\nScénario 4 : year, sampling_period=NULL, lacunes, NApct_lim=10\n")
out_4 = process_extraction(
    data           = data_gaps,
    funct          = list(QA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= NULL,
    NApct_lim      = 10,
    rmNApct        = FALSE
)
save_scenario("sc4_year_gaps_napct", data_gaps, out_4)


## Scénario 5 : année hydrologique avec lacunes en début de série ---------------
# La série A commence au 2003-06-15 (simulé par NA au début)
na_start = which(Date < as.Date("2003-06-15"))
data_late_start = bind_rows(
    make_data(1, "serie_A", na_rows=na_start),
    make_data(2, "serie_B")
)
cat("\nScénario 5 : year, sampling_period='09-01', début tardif\n")
out_5 = process_extraction(
    data           = data_late_start,
    funct          = list(QA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= "09-01",
    rmNApct        = FALSE
)
save_scenario("sc5_year_late_start", data_late_start, out_5)

## Scénario 6 : fenêtre sous-annuelle, série démarrant EN MILIEU de première fenêtre
# La série A commence le 2001-07-01 (milieu de la fenêtre 05-01→11-30)
# → première année incomplète, dNA élevé
cat("\nScénario 6 : year, sampling_period=c('05-01','11-30'), début mi-fenêtre\n")
Date_short = seq.Date(as.Date("2001-07-01"), End, by="day")
make_data_from = function(seed, id, start, na_rows=NULL) {
    set.seed(seed)
    dates = seq.Date(start, End, by="day")
    d = tibble(Date=dates, Q=100 + cumsum(rnorm(length(dates), 0, 1)), ID=id)
    if (!is.null(na_rows)) d$Q[na_rows] = NA
    d
}
data_mid_start = bind_rows(
    make_data_from(1, "serie_A", as.Date("2001-07-01")),
    make_data_from(2, "serie_B", as.Date("2001-01-01"))
)
out_6 = process_extraction(
    data           = data_mid_start,
    funct          = list(QMNA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= c("05-01", "11-30"),
    rmNApct        = FALSE
)
save_scenario("sc6_year_sub_midstart", data_mid_start, out_6)


## Scénario 7 : fenêtre sous-annuelle, série se terminant EN MILIEU de dernière fenêtre
cat("\nScénario 7 : year, sampling_period=c('05-01','11-30'), fin mi-fenêtre\n")
End_short = as.Date("2015-09-30")
make_data_to = function(seed, id, end) {
    set.seed(seed)
    dates = seq.Date(Start, end, by="day")
    tibble(Date=dates, Q=100 + cumsum(rnorm(length(dates), 0, 1)), ID=id)
}
data_mid_end = bind_rows(
    make_data_to(1, "serie_A", as.Date("2015-09-30")),
    make_data_to(2, "serie_B", End)
)
out_7 = process_extraction(
    data           = data_mid_end,
    funct          = list(QMNA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= c("05-01", "11-30"),
    rmNApct        = FALSE
)
save_scenario("sc7_year_sub_midend", data_mid_end, out_7)


## Scénario 8 : date de départ quelconque milieu de mois ("03-15")
cat("\nScénario 8 : year, sampling_period='03-15' (milieu de mois)\n")
out_8 = process_extraction(
    data           = data_clean,
    funct          = list(QA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= "03-15",
    rmNApct        = FALSE
)
save_scenario("sc8_year_march15", data_clean, out_8)


## Scénario 9 : fenêtre sous-annuelle CROISANT l'année ("11-01" → "04-30")
cat("\nScénario 9 : year, sampling_period=c('11-01','04-30') (sous-fenêtre croisée)\n")
out_9 = process_extraction(
    data           = data_clean,
    funct          = list(QA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= c("11-01", "04-30"),
    rmNApct        = FALSE
)
save_scenario("sc9_year_cross_subwindow", data_clean, out_9)


## Scénario 10 : NAs DANS la fenêtre (pas seulement aux bords), sans NApct_lim
# 30 jours de NA en juillet 2008, dans la fenêtre 05-01→11-30
cat("\nScénario 10 : year, sampling_period=c('05-01','11-30'), NAs dans la fenêtre\n")
na_in_window = which(Date >= as.Date("2008-07-01") & Date <= as.Date("2008-07-30"))
data_na_in = bind_rows(
    make_data(1, "serie_A", na_rows=na_in_window),
    make_data(2, "serie_B")
)
out_10 = process_extraction(
    data           = data_na_in,
    funct          = list(QMNA=mean),
    funct_args     = list("Q", na.rm=TRUE),
    time_step      = "year",
    sampling_period= c("05-01", "11-30"),
    rmNApct        = FALSE
)
save_scenario("sc10_year_na_in_window", data_na_in, out_10)


## Scénario 11 : year-month, mean -----------------------------------------
cat("\nScénario 11 : year-month, mean\n")
out_11 = process_extraction(
    data       = data_clean,
    funct      = list(QM=mean),
    funct_args = list("Q", na.rm=TRUE),
    time_step  = "year-month",
    rmNApct    = FALSE
)
save_scenario("sc11_yearmonth_default", data_clean, out_11)


## Scénario 12 : month, mean across years -----------------------------------
cat("\nScénario 12 : month, mean\n")
out_12 = process_extraction(
    data       = data_clean,
    funct      = list(QM=mean),
    funct_args = list("Q", na.rm=TRUE),
    time_step  = "month",
    rmNApct    = FALSE
)
save_scenario("sc12_month_default", data_clean, out_12)


## Scénario 13 : year-season, mean ------------------------------------------
cat("\nScénario 13 : year-season, mean\n")
out_13 = process_extraction(
    data       = data_clean,
    funct      = list(QS=mean),
    funct_args = list("Q", na.rm=TRUE),
    time_step  = "year-season",
    rmNApct    = FALSE
)
save_scenario("sc13_yearseason_default", data_clean, out_13)


## Scénario 14 : season, mean across years ----------------------------------
cat("\nScénario 14 : season, mean\n")
out_14 = process_extraction(
    data       = data_clean,
    funct      = list(QS=mean),
    funct_args = list("Q", na.rm=TRUE),
    time_step  = "season",
    rmNApct    = FALSE
)
save_scenario("sc14_season_default", data_clean, out_14)


## Scénario 15 : yearday, mean across years ---------------------------------
cat("\nScénario 15 : yearday, mean\n")
out_15 = process_extraction(
    data       = data_clean,
    funct      = list(QJA=mean),
    funct_args = list("Q", na.rm=TRUE),
    time_step  = "yearday",
    rmNApct    = FALSE
)
save_scenario("sc15_yearday_default", data_clean, out_15)


## Scénario 16 : none, mean -------------------------------------------------
cat("\nScénario 16 : none, mean\n")
out_16 = process_extraction(
    data       = data_clean,
    funct      = list(QA=mean),
    funct_args = list("Q", na.rm=TRUE),
    time_step  = "none",
    rmNApct    = FALSE
)
save_scenario("sc16_none_default", data_clean, out_16)


cat("\nFichiers sauvegardés dans", OUT_DIR, "\n")
