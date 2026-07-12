# stase

**STASE** — *STatistical Aggregation & Stationarity Evaluation*.

Port Python du package R **EXstat** : extraction et agrégation de
variables hydroclimatiques à partir de séries temporelles journalières,
et analyse de leur (non-)stationnarité — Mann-Kendall généralisé et
pente de Sen. La stase, c'est ce que l'on cherche dans les chroniques ;
les données climatiques et hydrologiques disent souvent autre chose.

```python
import numpy as np
import pandas as pd
from stase import process_extraction, Adaptive, process_trend

data = pd.DataFrame({"date": ..., "Q": ..., "id": ...})   # date en datetime64

# agrégation annuelle simple
qa = process_extraction(data, funct={"QA": (np.nanmean, "Q")},
                        time_step="year", sampling_period="09-01")

# année hydrologique adaptative (démarre au mois du max des moyennes
# mensuelles inter-annuelles, calculé par station)
qna = process_extraction(data, funct={"QNA": (np.nanmin, "Q")},
                         time_step="year",
                         sampling_period=Adaptive(np.nanmax, "Q"))
```

## Capacités du moteur

- `time_step` : year, year-month, month, year-season, season, yearday, none.
- `funct` en tuples `(fn, *colonnes_ou_littéraux, kwargs?, is_date?)` ;
  les kwargs dont la valeur est un nom de colonne des données reçoivent la
  colonne alignée sur le groupe (ex. `{"lim": "upLim"}`).
- **Sorties dynamiques en time_step 'none'** : scalaire (une ligne par
  station), vecteur de même longueur (colonne alignée, ex. moyenne mobile),
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

## Développement

Sans installation : ajouter `src/` au PYTHONPATH. Sinon
`pip install -e .` (environnement virtuel).

Le package `card` (CARD_project/card) utilise stase comme moteur pour
exécuter les fiches CARD YAML.

## Origine

Issu de `EXstat_Claude/EXstat_py` (port validé contre le package R EXstat),
enrichi des mécanismes moteur nécessaires aux fiches CARD (adaptatif,
sorties vectorielles, références de colonnes, colonnes creuses) le
2026-07-11. Licence et auteurs : fichiers LICENSE et AUTHORS (repris du
package R EXstat).
