"""STASE — STatistical Aggregation & Stationarity Evaluation.

Extraction et agrégation de variables hydroclimatiques à partir de séries
temporelles journalières, et analyse de leur (non-)stationnarité
(port Python du package R EXstat).
"""

from .extraction import Adaptive, process_extraction  # noqa: F401
from .tools import GeneralMannKendall, fieldSignificance_FDR  # noqa: F401
from .trend import process_trend  # noqa: F401

# Alias snake_case (les noms hérités du R restent valides)
general_mann_kendall = GeneralMannKendall
field_significance_fdr = fieldSignificance_FDR

__all__ = [
    "Adaptive",
    "process_extraction",
    "process_trend",
    "GeneralMannKendall",
    "general_mann_kendall",
    "fieldSignificance_FDR",
    "field_significance_fdr",
]

__version__ = "0.1.0"
