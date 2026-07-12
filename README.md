# stase [<img src="docs/img/flower.png" align="right" width="160" height="160" alt="stase"/>](https://github.com/lou-heraut/card)

<!-- badges: start -->
[![tests](https://github.com/lou-heraut/stase/actions/workflows/tests.yml/badge.svg)](https://github.com/lou-heraut/stase/actions/workflows/tests.yml)
[![Lifecycle: maturing](https://img.shields.io/badge/lifecycle-maturing-blue)](https://lifecycle.r-lib.org/articles/stages.html)
![](https://img.shields.io/github/last-commit/lou-heraut/stase)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-bd0000)](LICENSE)
<!-- badges: end -->

**STASE** (*STatistical Aggregation & Stationarity Evaluation*) agrège
des séries temporelles journalières en variables annuelles,
saisonnières ou mensuelles, puis analyse leur stationnarité par test de
Mann-Kendall généralisé et pente de Sen. La stase est l'état d'une
série sans tendance : l'hypothèse nulle du test. stase agrège les
chroniques et mesure ce qui s'en écarte.

## Installation

```bash
pip install "stase @ git+https://github.com/lou-heraut/stase.git"
```

## Démarrage rapide

```python
import numpy as np
import pandas as pd
import stase

# une chronique journalière : une colonne datetime, une colonne texte
# (identifiant de série), une ou plusieurs colonnes numériques
dates = pd.date_range("1990-01-01", "2020-12-31", freq="D")
data = pd.DataFrame({
    "date": dates,
    "Q": np.random.default_rng(0).gamma(2, 5, len(dates)),
    "id": "ma_station",
})

# moyenne annuelle sur l'année hydrologique (départ 1er septembre)
qa = stase.extract(data, funct={"QA": (np.nanmean, "Q")},
                   time_step="year", sampling_period="09-01")

# tendance : Mann-Kendall + pente de Sen, une ligne par série
trendEX = stase.trend(qa)
trendEX[trendEX.H == True]     # séries à tendance significative
```

Les colonnes sont reconnues par leur **type**, jamais par leur nom :
datetime pour les dates, texte pour l'identifiant de série, numérique
pour les valeurs. Une colonne de dates en texte au format ISO
`YYYY-MM-DD` est convertie automatiquement. Des identifiants numériques
doivent être convertis en texte : `data["code"].astype(str)`.

## Capacités du moteur

- `time_step` : year, year-month, month, year-season, season, yearday,
  none.
- `funct` en tuples `(fn, *colonnes_ou_littéraux, kwargs?, is_date?)`,
  plusieurs variables par appel via un dict. Un kwarg dont la valeur est
  un nom de colonne reçoit la colonne alignée sur le groupe (ex.
  `{"lim": "upLim"}`).
- `sampling_period` : fenêtre fixe (`"09-01"`, `["05-01", "11-30"]`) ou
  adaptative par série (`Adaptive(np.nanmax, "Q")` : l'année
  hydrologique démarre au mois du maximum du régime).
- La sortie de `stase.extract` se réinjecte comme entrée pour enchaîner
  les agrégations (ex. QMNA : moyenne mensuelle puis min annuel).
- Sorties dynamiques en `time_step="none"` : scalaire, colonne alignée
  (moyenne mobile) ou lignes libres (courbe des débits classés).
- Filtres de lacunes : `NApct_lim` (taux de lacunes par échantillon) et
  `NAyear_lim` (troncature des séries à trous pluriannuels).
- `stase.trend` : options `INDE` (test standard), `AR1` (correction
  d'autocorrélation) et `LTP` (persistance longue, coefficient de
  Hurst ; prévu pour des séries annuelles, passer `seed=` pour des
  résultats reproductibles en présence d'ex-æquo).

Quand il n'y a rien à retourner (entrée vide, `period` excluant toutes
les données), la sortie est un DataFrame de zéro ligne avec les
colonnes attendues : filtres et enchaînements fonctionnent sans
traitement spécial du cas vide.

Pour des variables hydroclimatiques prêtes à l'emploi (étiages, crues,
saisonnalité...), le package [card](https://github.com/lou-heraut/card)
fournit 215 fiches paramétrées exécutées par stase.

## Origine

stase est le port Python du package R
[EXstat](https://github.com/lou-heraut/EXstat) (INRAE, UR RiverLy),
validé nombre à nombre contre R. Le détail de la validation et les
divergences documentées sont dans
[docs/dev/ORIGINE_R.md](docs/dev/ORIGINE_R.md). Licence GPL-3, auteurs
dans le fichier AUTHORS.

## Développement

```bash
pip install -e . && pytest      # 97 tests, goldens inclus dans tests/data/
```

CI : `.github/workflows/tests.yml` (matrice Python × pandas, ruff).
Benchmark données réelles : `benchmarks/bench_rrse.py`. Suivi du plan
d'amélioration : `docs/dev/PLAN.md`.
