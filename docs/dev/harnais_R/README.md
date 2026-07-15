# Harnais de validation croisée R↔Python (archive)

Scripts copiés de `EXstat_Claude/EXstat_py/` le 2026-07-15 pour que le
repo soit auto-suffisant. Ils datent d'avant le renommage en stase :
les chemins et imports (`process_extraction.py`, `tools.py`...) sont à
adapter si on veut les rejouer.

- `ref_extraction.R` — génère les références R d'extraction
- `compare.py` — 22 scénarios process_extraction R vs Python
- `compare_trend.R` / `compare_trend.py` — 73 scénarios Mann-Kendall
- `compare_process_trend.R` / `.py` — 896 scénarios process_trend
- `benchmark.py` / `benchmark_real.py` — mesures de performance ;
  le jeu réel (228 chroniques HYDRO, ~5M lignes) a été déplacé le
  2026-07-15 vers `../EXstat/data_test/RRSE_csv/` (adapter le chemin
  en tête de script)

Les CSVs de référence complets (`ref_output/`, `ref_trend/`) ne sont pas
copiés : régénérables via les scripts R et le package R EXstat
(`../EXstat/`). Le sous-ensemble curé servant à la non-régression est
commité dans `tests/data/` et couvert par pytest.
