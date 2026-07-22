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
qa = stase.extract(data, func={"QA": (np.nanmean, "Q")},
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
- `func` en tuples `(fn, *colonnes_ou_littéraux, kwargs?, is_date?)`,
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
- Filtres de lacunes : `max_na_pct` (taux de lacunes par échantillon,
  comparé au taux exact) et `max_na_years` (troncature des séries à
  trous pluriannuels).
- Chroniques à trous sûres : la grille temporelle de chaque série est
  matérialisée (pas de temps manquants insérés en NaN), et toutes les
  séries d'un appel doivent partager le même pas de temps (détection
  par série, erreur explicite sinon).
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
fournit un corpus de fiches paramétrées exécutées par stase.

## Citer

Ce moteur est un logiciel scientifique : merci de le citer si vous
l'utilisez dans un travail publié.

```
Héraut L., Dorchies D., Sauquet É., Vidal J.-P. (2026). stase :
agrégation statistique et évaluation de stationnarité (version 0.5.0).
Software Heritage : swh:1:rev:<commit>
https://github.com/lou-heraut/stase
```

Le dépôt est archivé sur [Software
Heritage](https://archive.softwareheritage.org/browse/origin/directory/?origin_url=https://github.com/lou-heraut/stase),
qui donne un identifiant pérenne par révision. Métadonnées lisibles par
machine : `CITATION.cff` et `codemeta.json` à la racine ; GitHub propose
d'ailleurs « Cite this repository » à partir du premier.

Si vous citez un résultat produit par le service
[card-api](https://github.com/lou-heraut/card-api), chaque réponse porte
déjà le commit et le SWHID exacts du code qui l'a calculé, ainsi que la
version de chaque fiche employée : reprenez-les plutôt que ce modèle.

## Origine

stase est le port Python du package R
[EXstat](https://github.com/lou-heraut/EXstat) (INRAE, UR RiverLy),
validé nombre à nombre contre R. Le détail de la validation et les
divergences documentées sont dans
[docs/dev/ORIGINE_R.md](docs/dev/ORIGINE_R.md). Licence GPL-3, auteurs
dans le fichier AUTHORS.

## Développement

```bash
pip install -e . && pytest      # 131 tests, goldens inclus dans tests/data/
```

CI : `.github/workflows/tests.yml` (matrice Python × pandas, ruff).
Benchmark données réelles : `benchmarks/bench_rrse.py`. Ce qui a changé
et quand : [CHANGELOG.md](CHANGELOG.md).
