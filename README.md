# stase

[![tests](https://github.com/lou-heraut/stase/actions/workflows/tests.yml/badge.svg)](https://github.com/lou-heraut/stase/actions/workflows/tests.yml)

**STASE** — *STatistical Aggregation & Stationarity Evaluation*.

<!-- Figure d'illustration (à déposer dans docs/img/, cf. docs/img/README.md) :
![Schéma du pipeline stase](docs/img/pipeline.png)
-->

Port Python du package R **EXstat** : extraction et agrégation de
variables hydroclimatiques à partir de séries temporelles journalières,
et analyse de leur (non-)stationnarité — Mann-Kendall généralisé et
pente de Sen. La stase est l'état d'une série sans tendance :
l'hypothèse nulle du test de Mann-Kendall. stase agrège les chroniques
et mesure ce qui s'en écarte.

```python
import numpy as np
import pandas as pd
from stase import process_extraction, Adaptive, process_trend

data = pd.DataFrame({"date": ..., "Q": ..., "id": ...})   # date en datetime64

# agrégation annuelle simple
qa = process_extraction(data, funct={"QA": (np.nanmean, "Q")},
                        time_step="year", sampling_period="09-01")

# année hydrologique adaptative (démarre au mois du max des moyennes
# mensuelles inter-annuelles, calculé par série)
qna = process_extraction(data, funct={"QNA": (np.nanmin, "Q")},
                         time_step="year",
                         sampling_period=Adaptive(np.nanmax, "Q"))

# analyse de stationnarité : Mann-Kendall + pente de Sen par série
trendEX = process_trend(qa, MK_level=0.1, time_dependency_option="INDE")
trendEX[trendEX.H == True]      # séries à tendance significative
```

La sortie de `process_extraction` se réinjecte comme entrée (enchaînement
d'agrégations, ex. QMNA = moyenne mensuelle → min annuel). `process_trend`
retourne une ligne par série × variable : `H` (booléen nullable — NA si
moins de 3 valeurs valides), `p`, `a` (pente de Sen par pas de temps),
`b`, bornes extrêmes de la pente normalisée.

## Capacités du moteur

- `time_step` : year, year-month, month, year-season, season, yearday, none.
- `funct` en tuples `(fn, *colonnes_ou_littéraux, kwargs?, is_date?)` ;
  les kwargs dont la valeur est un nom de colonne des données reçoivent la
  colonne alignée sur le groupe (ex. `{"lim": "upLim"}`). Un bool en
  dernière position est toujours `is_date` : pour passer un littéral
  booléen à `fn`, ajouter le dict kwargs après — `(fn, "Q", True, {})`.
- **Sorties dynamiques en time_step 'none'** : scalaire (une ligne par
  série), vecteur de même longueur (colonne alignée, ex. moyenne mobile),
  ou vecteur de longueur libre (lignes « ragged », ex. courbe des débits
  classés).
- `sampling_period` fixe (`"MM-DD"`, `["MM-DD","MM-DD"]`) ou `Adaptive`.
- `keep` : None, `'all'` (fan-out sur les lignes d'origine) ou liste de
  colonnes à conserver. Les colonnes creuses produites par le fan-out sont
  signalées via `DataFrame.attrs` et compactées automatiquement à l'appel
  suivant (équivalent de la distinction NA/NaN du R).
- Filtres de lacunes `NApct_lim` (par échantillon) et `NAyear_lim`
  (troncature des séries à trous pluriannuels).
- `process_trend` : Mann-Kendall généralisé + pente de Sen (tools.py).
  Trois options de dépendance temporelle : `INDE` (test standard), `AR1`
  (correction d'autocorrélation, Hamed & Rao 1998), `LTP` (persistance
  longue via coefficient de Hurst, Hamed 2008). Le cœur statistique est
  un port fidèle de tools.R, validé nombre à nombre contre R (goldens
  dans `tests/data/`). Notes LTP : prévu pour des séries agrégées
  (annuelles typiquement, n ≤ ~100 ; calcul en O(n⁴), warning au-delà de
  200 valeurs, mémoire bornée par blocs). En présence d'ex-æquo, le
  tirage aléatoire des rangs (ties.method='random', choix documenté de
  tools.R — Hamed 2008 ne prescrit rien) rend le résultat non
  déterministe : passer `seed=<int>` à `process_trend` pour des
  résultats rejouables (sans effet sur les séries sans ex-æquo,
  identiques à R).

Les colonnes sont détectées par **type**, jamais par nom : datetime →
dates, texte → identifiant de série, numérique → valeurs. Des codes de
série numériques doivent être convertis : `data["code"].astype(str)`.

Quand il n'y a rien à retourner (entrée vide, `period` excluant toutes
les données…), la sortie est un DataFrame de zéro ligne **avec les
colonnes attendues** : filtres, merges et enchaînements fonctionnent
sans traitement spécial du cas vide. Exceptions (colonnes indéfinissables
sans données) : `compress`, `expand` et `keep='all'` retournent un
DataFrame nu.

## Divergences intentionnelles vs EXstat R

- `NApct` utilise le nombre réel de jours calendaires comme dénominateur
  (R : constantes 365.25 / 30.4375) et s'adapte à la résolution de
  l'entrée (journalière, mensuelle, saisonnière).
- Le bug R du NApct des jours 1 et 365 en `yearday` n'est pas reproduit.
- Précision du MLE de Hurst (LTP) : scipy est plus précis que
  l'`optimize` de R (écarts possibles ~2e-3 sur p, signe identique).
- `process_trend` : les colonnes listes de R deviennent des colonnes
  séparées (`period_trend_start`/`period_trend_end`, etc.) et `H` est un
  booléen nullable.

## Installation

Depuis GitHub (pas de publication PyPI pour l'instant) :

```bash
pip install "stase @ git+https://github.com/lou-heraut/stase.git"
```

Pour le développement : cloner le repo puis `pip install -e .`
(environnement virtuel), ou simplement ajouter `src/` au PYTHONPATH.

## Développement

Tests : `pytest` (goldens R inclus dans `tests/data/` — le repo est
auto-suffisant pour la non-régression). CI : `.github/workflows/tests.yml`
(pytest sur matrice Python × pandas + ruff). Benchmark données réelles :
`benchmarks/bench_rrse.py`. Le plan d'amélioration et son suivi sont
dans `docs/dev/PLAN.md`.

Le package `card` (CARD_project/card) utilise stase comme moteur pour
exécuter les fiches CARD YAML.

## Origine

Issu de `EXstat_Claude/EXstat_py` (port validé contre le package R EXstat),
enrichi des mécanismes moteur nécessaires aux fiches CARD (adaptatif,
sorties vectorielles, références de colonnes, colonnes creuses) le
2026-07-11. Licence et auteurs : fichiers LICENSE et AUTHORS (repris du
package R EXstat).
