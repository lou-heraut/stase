"""STASE : STatistical Aggregation & Stationarity Evaluation.

Agrégation de séries temporelles journalières en variables temporelles
(annuelles, saisonnières, mensuelles...) et analyse de leur
(non-)stationnarité par test de Mann-Kendall généralisé et pente de Sen.

Usage :
    import stase
    dataEX  = stase.extract(data, func={"QA": (np.nanmean, "Q")},
                            time_step="year")
    trendEX = stase.trend(dataEX)
"""

from .extraction import Adaptive, process_extraction  # noqa: F401
from .tools import GeneralMannKendall, fieldSignificance_FDR  # noqa: F401
from .trend import process_trend  # noqa: F401

# ── API canonique ────────────────────────────────────────────────────────────
extract = process_extraction
trend = process_trend
general_mann_kendall = GeneralMannKendall
field_significance_fdr = fieldSignificance_FDR

# Les noms hérités du package R EXstat (process_extraction, process_trend,
# GeneralMannKendall, fieldSignificance_FDR) restent valides : ce sont des
# alias, utiles pour qui migre depuis R.

__all__ = [
    "extract",
    "trend",
    "Adaptive",
    "general_mann_kendall",
    "field_significance_fdr",
    # alias héritage R
    "process_extraction",
    "process_trend",
    "GeneralMannKendall",
    "fieldSignificance_FDR",
]

__version__ = "0.1.0"
