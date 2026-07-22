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
# (identifiant de série), une ou plusieurs colonnes numériques. Ici deux
# séries synthétiques, l'une en baisse lente, l'autre stable.
dates = pd.date_range("1970-01-01", "2020-12-31", freq="D")
rng = np.random.default_rng(0)
saison = 1 + 0.6 * np.cos(2 * np.pi * (dates.dayofyear.to_numpy() - 30) / 365)

def serie(nom, facteur):
    return pd.DataFrame({
        "date": dates, "id": nom,
        "Q": (rng.gamma(2, 5, len(dates)) * saison
              * np.linspace(1.0, facteur, len(dates)))})

data = pd.concat([serie("A", 0.75), serie("B", 1.0)], ignore_index=True)

# moyenne annuelle sur l'année hydrologique (départ 1er septembre)
qa = stase.extract(data, func={"QA": (np.nanmean, "Q")},
                   time_step="year", sampling_period="09-01")
# id       date        QA
#  A 1969-09-01  9.548228
#  A 1970-09-01  9.257581
```

Les colonnes sont reconnues par leur **type**, jamais par leur nom :
datetime pour les dates, texte pour l'identifiant de série, numérique
pour les valeurs. Une colonne de dates en texte au format ISO
`YYYY-MM-DD` est convertie automatiquement. Des identifiants numériques
doivent être convertis en texte : `data["code"].astype(str)`.

## Analyser la stationnarité

```python
tr = stase.trend(qa)
tr[["id", "variable", "H", "p", "a", "a_relative"]]
# id variable     H            p         a  a_relative
#  A       QA  True 2.767571e-16 -0.055412   -0.632233
#  B       QA False 8.189923e-01  0.001022    0.010210
```

Une ligne par série et par variable. `H` dit si la tendance est
significative au seuil demandé, `a` est la pente de Sen dans l'unité de
la variable et par an, `a_relative` la même en pourcentage de la moyenne.
Trois hypothèses de dépendance temporelle : `INDE` (test standard),
`AR1` (correction d'autocorrélation d'ordre 1) et `LTP` (persistance
longue, coefficient de Hurst). Le LTP départage les ex aequo par tirage
aléatoire : passer `seed=` pour un résultat rejouable.

## Enchaîner les agrégations

La sortie de `stase.extract` se réinjecte comme entrée. Le QMNA, minimum
annuel des débits moyens mensuels, s'écrit ainsi en deux temps :

```python
qm = stase.extract(data, func={"QM": (np.nanmean, "Q")}, time_step="year-month")
qmna = stase.extract(qm, func={"QMNA": (np.nanmin, "QM")}, time_step="year")
# id       date     QMNA
#  A 1970-01-01 4.317909
#  A 1971-01-01 3.528193
```

## Fenêtre d'échantillonnage adaptative

Une fenêtre annuelle fixe coupe parfois un événement en deux. `Adaptive`
la décide série par série, ici en démarrant l'année au mois du maximum du
régime, ce qui place l'étiage au milieu de la fenêtre :

```python
vcn = stase.extract(data, func={"VCN": (np.nanmin, "Q")}, time_step="year",
                    sampling_period=stase.Adaptive(np.nanmax, "Q"))
```

## Colonnes de paramètre

Une colonne fournie par l'appelant, constante par série, qui n'est ni
l'axe temporel ni une mesure : un seuil réglementaire, une borne de
période, une surface de bassin. Déclarée dans `param_cols`, elle est
référençable par une fonction, exclue du comptage des lacunes, et
**conservée en sortie** pour traverser un enchaînement :

```python
def jours_sous(Q, seuil):
    return int(np.sum(np.asarray(Q, float) < float(np.asarray(seuil)[0])))

d = data.assign(seuil=np.where(data["id"] == "A", 3.0, 4.0))
n = stase.extract(d, func={"n_jours": (jours_sous, "Q", {"seuil": "seuil"})},
                  time_step="year", param_cols=["seuil"])
# id       date  n_jours  seuil
#  A 1970-01-01       66    3.0
#  A 1971-01-01       66    3.0
```

Chaque série reçoit sa propre valeur, et le seuil reste lisible à côté du
résultat qu'il a produit.

## Capacités du moteur

- `time_step` : year, year-month, month, year-season, season, yearday,
  none.
- `func` en tuples `(fn, *colonnes_ou_littéraux, kwargs?, is_date?)`,
  plusieurs variables par appel via un dict. Un kwarg dont la valeur est
  un nom de colonne reçoit la colonne alignée sur le groupe (ex.
  `{"lim": "upLim"}`).
- `sampling_period` : fenêtre fixe (`"09-01"`) ou partielle
  (`["05-01", "11-30"]`), qui restreint alors les données à cette
  sous-période, ou adaptative par série.
- Sorties dynamiques en `time_step="none"` : scalaire, colonne alignée
  (moyenne mobile) ou lignes libres (courbe des débits classés).
- Filtres de lacunes : `max_na_pct` (taux de lacunes par échantillon,
  comparé au taux exact) et `max_na_years` (troncature des séries à
  trous pluriannuels).
- Chroniques à trous sûres : la grille temporelle de chaque série est
  matérialisée (pas de temps manquants insérés en NaN), et toutes les
  séries d'un appel doivent partager le même pas de temps (détection
  par série, erreur explicite sinon).
- `param_cols` : colonnes de paramètre constantes par série, conservées
  en sortie.
- `suffix` : une même fonction appliquée à plusieurs variantes d'une
  colonne en un appel, la résolution se faisant référence par référence
  (une série partagée reste partagée, seule la colonne qui varie éclate).

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
