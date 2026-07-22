> **Statut : norme en vigueur.** Table de correspondance des noms R vers
> Python (fonctions, paramètres, colonnes de sortie). Elle fait foi ;
> tout nouveau renommage passe par l'utilisateur.

# Renommages Python (2026-07-12)

Nettoyage validé par l'utilisateur : renommage sec des paramètres (pas
d'alias de paramètres), fonctions R conservées en alias, colonnes de
sortie en snake_case, colonne de date de sortie au nom de la colonne
d'entrée (le nom imposé « Date » était considéré comme un bug).

## Fonctions (alias R conservés)

| R / historique | Python canonique |
|---|---|
| process_extraction | stase.extract |
| process_trend | stase.trend |
| GeneralMannKendall | stase.general_mann_kendall |
| fieldSignificance_FDR | stase.field_significance_fdr |

## Paramètres de stase.extract (renommage sec)

| Ancien | Nouveau |
|---|---|
| funct | func |
| funct_args | supprimé (déprécié depuis la conversion) |
| is_date (top niveau) | supprimé (dans le tuple func) |
| NApct_lim | max_na_pct |
| rmNApct | drop_na_pct |
| nameEX | name |
| Seasons | seasons |
| rm_duplicates | drop_duplicates |
| NAyear_lim | max_na_years |
| Adaptive(funct=...) | Adaptive(func=...) |

## Paramètres de stase.trend (renommage sec)

| Ancien | Nouveau |
|---|---|
| dataEX | data |
| MK_level | level |
| time_dependency_option | dependency (valeurs INDE/AR1/LTP inchangées) |
| to_normalise | relative |
| metaEX | retiré en 0.4.0 : le caractère relatif se passe par `relative={variable: bool}` |
| extreme_take_not_signif_into_account | extremes_include_non_significant |
| extreme_take_only_series | extremes_series |
| extreme_by_suffix | extremes_by_suffix |
| period_trend | period |
| extreme_prob | extremes_prob |
| show_advance_stat | advanced_stats |

## Colonnes de sortie

| Ancien | Nouveau |
|---|---|
| Date | nom de la colonne de date d'entrée |
| ID (id synthétique) | id |
| Month / Season / YearSeason / Yearday | month / season / year_season / yearday |
| NApct, NApct_{var} | na_pct, na_pct_{var} |
| variable_en / variable_no_suffix_en (trend) | variable / variable_no_suffix |
| a_normalise (min/max) | a_relative (min/max) |
| period_trend_start / period_trend_end | period_start / period_end |
| mean_period_trend | mean_period |

En interne, extraction.py et trend.py conservent les noms historiques
(pont en tête de fonction) : la logique validée par les goldens n'est
pas touchée, seule l'interface change. Les CSVs de référence R gardent
leurs noms d'origine, traduits dans les helpers de tests.
