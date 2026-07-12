"""STASE — STatistical Aggregation & Stationarity Evaluation.

Extraction et agrégation de variables hydroclimatiques à partir de séries
temporelles journalières, et analyse de leur (non-)stationnarité
(port Python du package R EXstat).
"""

from .extraction import Adaptive, process_extraction  # noqa: F401
from .tools import GeneralMannKendall, fieldSignificance_FDR  # noqa: F401
from .trend import process_trend  # noqa: F401

__version__ = "0.1.0"
