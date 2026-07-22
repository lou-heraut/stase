# Journal des modifications

Évolutions notables de `stase`, moteur d'agrégation et de stationnarité.
Format inspiré de [Keep a
Changelog](https://keepachangelog.com/fr/1.1.0/). Le paquet consommateur
`card` tient son propre journal.

Chaque entrée dit ce qui a changé et renvoie au document qui l'explique.
Rien n'est recopié ici : une information recopiée finit par mentir à un
des deux endroits.

**Note sur les numéros.** Le dépôt n'est pas encore étiqueté (pas de tag
git, installation depuis GitHub). Les jalons 0.2.0 et 0.3.0 ont été
annoncés dans les messages de commit sans que `pyproject.toml` soit
touché : le numéro n'a rattrapé son retard qu'au 0.4.0, le 2026-07-20.
Les sections ci-dessous portent la date réelle du travail.

## Non publié

### Ajouté

- Rôle `param_cols` : une colonne fournie par l'appelant, souvent une
  date, qui n'est ni un axe ni une mesure. Elle est mise de côté à la
  détection (l'axe et l'identifiant tombent alors par élimination),
  reste référençable par une fonction quel que soit son dtype, sort du
  canal numérique (`value_cols`, `_apply_nayear_lim`), se suffixe, et
  surtout est **conservée** en sortie pour traverser un enchaînement de
  process. Rétrocompatible : `param_cols=None` ne change rien.

  C'est ce qui permet à card de sortir les bornes d'horizon et les
  seuils réglementaires des fiches pour les recevoir en entrée. **Point
  d'attention** : card en dépend déjà alors que le rôle est arrivé après
  le bump 0.4.0, et que sa contrainte de dépendance est `stase>=0.4.0`.
  Une version 0.4.0 figée par un tag ne suffirait pas.

## 0.4.0 (2026-07-20)

### Retiré

- Le paramètre `meta=` de `process_trend`. Il acceptait la table de
  métadonnées de `card.extract`, ce qui faisait dépendre le moteur du
  format d'un paquet aval, et il court-circuitait la validation de
  `relative=` : une variable non couverte y retombait silencieusement
  sur `True` au lieu de lever. Le caractère relatif passe désormais par
  `relative={variable: bool}`, forme générique déjà validée contre les
  goldens R. C'est à card de traduire ses fiches.

### Modifié

- **Les unités de sortie de tendance cessent d'être ambiguës.**
  `a_normalise` portait le pourcentage quand la variable était
  normalisée, et une simple copie de la pente absolue sinon : deux
  variables d'une même sortie pouvaient se retrouver dans des unités
  différentes sous le même nom de colonne, sans rien pour les
  distinguer. Désormais `a` et `change` portent toujours l'absolu,
  `a_relative` et `change_relative` toujours le pourcentage, et valent
  NaN quand la variable n'est pas relative. Nouvelles bornes `a_min`,
  `a_max`, `change_min`, `change_max` dans l'unité de la variable, si
  bien qu'une variable non relative garde des bornes exploitables.
  `mean_period` est désormais toujours calculée.
- **Le suffixe se résout référence par référence, non fonction par
  fonction.** R calculait `where_no_suffix` et n'éclatait que les
  fonctions dont au moins un argument admettait une variante suffixée,
  en passant les autres arguments comme chaînes littérales : un calcul
  mêlant une série partagée et une colonne variant par scénario y était
  silencieusement faux. stase prend la colonne suffixée si elle existe,
  la colonne de base sinon, kwargs-colonnes compris. Une fonction dont
  aucune référence ne varie est émise une seule fois, donc calculée une
  seule fois. Le cas nominal du R est inchangé.

### Corrigé

- `_strip_suffix` retirait une sous-chaîne n'importe où dans le nom : un
  suffixe `sim` amputait une variable `QA_simple`. Retrait ancré en fin
  de nom.
- Avertissement numpy à chaque extraction comportant des années de date
  manquantes : la conversion en Int64 nullable arrondissait et
  convertissait tout le tableau, emplacements NaN compris, avant de les
  masquer. Les valeurs étaient correctes, le bruit ne l'était pas.

Détail des divergences : `docs/dev/ORIGINE_R.md`. Tests :
`tests/test_suffix.py` (9 scénarios), `tests/test_trend.py` (scénarios 2
et 4, qui continuent de vérifier la parité R sur `a`, `p` et `b`).

## 0.3.0 (2026-07-17)

### Corrigé

- **Un alias d'agrégation ne doit jamais changer la valeur.** La table
  d'alias Cython promettait de la vitesse et changeait des résultats :
  `np.nanstd` était aliasé vers le `std` de pandas (ddof=1 contre ddof=0
  pour numpy), `np.median` ne se délègue pas à pandas (strict contre
  skipna sur des groupes lacunaires), les builtins dépendent de l'ordre
  face aux NaN, et le `sum` de pandas rend 0.0 sur un groupe tout-NaN là
  où le chemin générique rend NaN. La table est restreinte aux variantes
  `nan*`, dont le contrat **est** celui de pandas, et un test dédié
  prouve l'équivalence alias contre générique sur groupes lacunaires et
  tout-NaN.
- Invariant du moteur rendu explicite : un groupe sans aucune valeur
  valide rend NaN pour **toutes** les fonctions, sommes comprises. Une
  année entièrement lacunaire est une lacune, pas un cumul nul.
  Divergence intentionnelle avec le `sum(na.rm = TRUE)` de R.

### Ajouté

- Avertissement sur les fonctions d'agrégation ambiguës face aux NaN.
  `np.mean` se délègue à la méthode pandas avec skipna, `np.median`
  reste stricte, `np.argmax` traite NaN comme le maximum, et les
  builtins dépendent de l'ordre : la sémantique dépendait du chemin
  d'exécution. Le moteur les accepte toujours, avec un avertissement qui
  pointe la variante `nan*` explicite. Le vocabulaire `nan*` reste
  silencieux.

## 0.2.0 (2026-07-16)

Issue de la revue critique menée avant le premier déploiement.

### Ajouté

- **Grille temporelle matérialisée.** Toute la chaîne supposait des
  chroniques denses, avec les lacunes portées par des NaN. Or les
  sources réelles comme Hub'Eau ne renvoient que les jours mesurés :
  les lignes absentes échappaient silencieusement à `max_na_years`,
  décalaient les dates d'extremum (`is_date`) et les fenêtres
  glissantes, et biaisaient la pente de Sen (+38 % mesuré avec 10 années
  absentes sur 40). `_complete_grid`, partagé, insère une ligne NaN à
  chaque pas manquant, par série, dans `process_extraction` comme dans
  les séries agrégées de `process_trend` (la pente de Sen et les
  corrections AR1/LTP supposent un pas régulier, la statistique de
  Mann-Kendall elle-même non).
- Résolution détectée **par série**, avec une erreur explicite si les
  séries d'une même extraction mélangent des pas de temps. Agréger un
  maximum journalier et un maximum mensuel sous le même nom
  comparerait des grandeurs différentes.
- `keep='all'` renvoie la grille complète, ce qui rend la sortie
  directement réinjectable. Séries à dates hors grille : laissées telles
  quelles, avec un avertissement.

### Modifié

- `max_na_pct` se compare au taux de lacunes **exact** et non plus
  arrondi. R comparait la valeur arrondie à une décimale, si bien qu'un
  taux réel de 3.04 % passait un seuil de 3. L'arrondi ne subsiste que
  dans la colonne `na_pct` de sortie, pour l'affichage.
- Les noms hérités `dataEX` et `metaEX` disparaissent de la surface
  publique (documentation et messages).

Tests d'équivalence lacunes-en-lignes contre lacunes-en-NaN :
`tests/test_grid.py`.

## 0.1.0 (2026-07-12)

Première version, port Python du paquet R
[EXstat](https://github.com/lou-heraut/EXstat).

### Ajouté

- `process_extraction`, moteur d'agrégation couvrant les sept pas de
  temps, et `process_trend`, enveloppe Mann-Kendall généralisé plus
  pente de Sen par série et par variable. Cœur statistique (MK INDE,
  AR1, LTP, Sen, Hurst, FDR) porté et validé contre R, puis **gelé**.
- API pythonique `stase.extract` et `stase.trend`, les noms R restant en
  alias. Paramètres et colonnes de sortie renommés sec.
- Goldens R rapatriés dans le dépôt, qui devient autosuffisant pour la
  non-régression : 13 scénarios Mann-Kendall, 5 scénarios
  `process_trend`, 11 scénarios d'extraction couvrant les sept pas de
  temps.
- Détection des colonnes par type et jamais par nom (datetime pour
  l'axe, texte pour l'identifiant de série, numérique pour les valeurs),
  avec un diagnostic explicite sur les identifiants numériques.

### Corrigé

- Séries fantômes après un filtre `period` : les catégories vidées
  créaient des lignes vides, tous les `groupby` passent désormais
  `observed=True`.
- `process_trend` perdait de l'information sur les identifiants
  multiples ; la colonne `H` devient un booléen nullable.
- Retours vides typés : zéro ligne, mais les colonnes attendues.

### Modifié

- Passe de performance sur les chemins chauds, mesurée sur données
  réelles (228 séries, 5,16 millions de lignes journalières) : 24,9 s
  vers 14,9 s, corpus régénéré identique au bit près.
- LTP : tirage des ex aequo rendu reproductible par un paramètre `seed`,
  et variance calculée par blocs (mémoire bornée à environ 130 Mo au
  lieu de plus de 3 Go au-delà de n = 200). Exception au gel de
  `tools.py`, validée par l'utilisateur et prouvée par tests
  d'équivalence.
- Conversion automatique des colonnes de dates en texte ISO strict, les
  formats ambigus restant une erreur.
- Licence GPL-3 pour tout le dépôt.

Détail : `docs/dev/ORIGINE_R.md` (origine et divergences assumées),
`docs/dev/RENAMING_PY.md` (table des renommages),
`docs/dev/archive/PLAN.md` (audit du 2026-07-12, clôturé).
