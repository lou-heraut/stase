# CLAUDE.md : stase

## Contexte

stase (*STatistical Aggregation & Stationarity Evaluation*) est le port
Python du package R **EXstat** : agrégation de chroniques journalières
hydroclimatiques en variables temporelles (annuelles, saisonnières,
mensuelles…) puis analyse de stationnarité (Mann-Kendall généralisé,
pente de Sen). Il sert de **moteur de données** au package `card`
(`../../CARD_project/card`), qui exécute les fiches CARD YAML. Les
dépôts R d'origine (`../EXstat/`, `../../CARD_project/CARD-R/`) restent
sans fichiers IA : on y lit, on n'y dépose rien (`dev/decisions.md`).

## Où lire quoi

Un rôle par fichier, chacun l'annonce dans un bandeau de statut en tête ;
ne jamais recopier d'un fichier à l'autre, renvoyer.

- `README.md` : ce que fait le moteur, et comment s'en servir.
- `ROADMAP.md` : ce qui reste à faire.
- `CHANGELOG.md` : ce qui a été fait, quand, et où lire le détail ; la
  doctrine des versions est en tête.
- `dev/decisions.md` : les règles du moteur avec leur date et leur raison.
- `dev/r-origin.md` : origine R, validation croisée, et les divergences
  intentionnelles à ne jamais « corriger ».
- `dev/renaming.md` : la table des noms R vers Python, qui fait foi.
- `dev/plans/` : plans datés, terminés (audit du 2026-07-12, conversion
  R) ; `dev/r-harness/` : le harnais de validation croisée R, figé.
- Principes documentaires communs aux quatre dépôts de l'écosystème :
  `../../CARD_project/card/dev/decisions.md`.

## Structure

```
src/stase/
  extraction.py   # process_extraction : moteur d'agrégation (cœur du projet)
  trend.py        # process_trend : enveloppe MK + Sen par série × variable
  tools.py        # cœur statistique : MK INDE/AR1/LTP, Sen, Hurst, FDR, GELÉ
  _display.py     # _verbose_box partagé
tests/
  test_extraction.py         # comportement du moteur
  test_golden_extraction.py  # 11 goldens R (7 time_steps)
  test_grid.py               # grille matérialisée : trous de lignes ≡ NaN,
                             #   résolutions mixtes, Sen sur années absentes
  test_tools.py              # 13 goldens MK R + cas limites figés
  test_trend.py              # 5 goldens process_trend R + cas limites
  test_suffix.py             # résolution du suffixe référence par référence
  test_params.py             # rôle param_cols (colonnes de paramètre)
  data/                      # CSVs de référence R (repo auto-suffisant)
docs/img/         # figures du README (déposées manuellement)
```

> ## À NE JAMAIS FAIRE
>
> - **`note.txt` (et tout fichier de notes de l'utilisateur) : NE PAS
>   L'OUVRIR.** Ni Read, ni `cat`, ni `grep`, ni au détour d'un `git add`.
>   C'est son brouillon personnel : pas de lecture, pas de résumé, pas de
>   « au passage j'ai vu que ». Il n'entre dans aucune tâche sans une
>   demande explicite de sa part, fichier par fichier. Un en-tête qui dit
>   de ne pas lire est un ordre, pas une mise en garde à évaluer.
> - **Pas de `git add -A` ni de `git add .`** : stager nommément les
>   fichiers que l'on a soi-même modifiés. Ce qui traîne dans l'arbre de
>   travail appartient à l'utilisateur.
> - **Ne JAMAIS signaler un fichier non suivi.** Un fichier non suivi est
>   à l'utilisateur : brouillon, essai, sortie jetable. Il a le droit d'en
>   avoir, il n'a pas à s'en justifier, et le lui rappeler est une
>   nuisance. Pas de « au passage, j'ai vu que », pas de « je n'y touche
>   pas », pas de récapitulatif en fin de réponse. On n'en parle que s'il
>   en parle le premier. Le répertoire `bac/` est ignoré par git : c'est
>   là qu'on lui propose de déposer ce qu'il veut faire disparaître du
>   `git status`, une fois, sans y revenir.

## Règles du projet

Décisions de l'utilisateur du 2026-07-12, détaillées avec leurs raisons
dans `dev/decisions.md` :

1. **`tools.py` est gelé** : aucune modification sans accord explicite.
2. **Détection des colonnes par type, jamais par nom** : jamais de
   paramètre `id_col=` / `date_col=`.
3. **Wording générique** : « série », jamais « station ».
4. **Docstring d'une fonction publique** : anglais, sections NumPy, corps
   en Markdown (`tests/test_docstrings.py`).
5. **Versions** : rien au quotidien sauf `## Non publié` ; publier par
   `scripts/set_version.py`, jamais à la main.

## API

Canonique : `stase.extract` et `stase.trend` (les noms de fonctions R
restent en alias, mais paramètres et colonnes de sortie sont renommés
sec : table dans `dev/renaming.md` ; la colonne de date de sortie
reprend le nom de la colonne d'entrée). En interne, extraction.py et
trend.py gardent les noms historiques via un pont en tête de fonction :
ne pas « nettoyer » ce pont, il isole la logique validée par les
goldens. Style : pas de préfixe redondant, pas de tiret quadratin (—) dans la
prose, docs, messages ni réponses (marqueur de texte IA, rebute des
utilisateurices : reformuler), références R limitées à une mention
(`dev/r-origin.md`).

## Commandes

```bash
.python_env/bin/python -m pytest        # suite complète (~2 s)
# validation côté consommateur :
cd ../../CARD_project/card && .python_env/bin/python -m pytest
```

Environnement : `.python_env/` ; dépendance déclarée pandas>=2.2
(include_groups, observed=).

## Versions et citation

Doctrine complète : « Versions, en cinq phrases », en tête de
`CHANGELOG.md`. Ce qu'il ne faut pas rater :

- **Au quotidien : rien.** La production suit `main`, le service publie
  le commit et le SWHID de card et de stase dans chaque réponse. Le seul
  geste régulier est l'entrée `## Non publié` du CHANGELOG. **Le
  proposer soi-même**, l'utilisateur ne le demandera pas.
- **Quand couper une version** : un changement de l'API du moteur se
  publie le jour où il est livré (et card remonte son `stase>=`), le
  reste attend la fin du chantier en cours, jamais le calendrier.
  Critères exacts : cinquième phrase du CHANGELOG.
  `python scripts/set_version.py --etat` donne les faits. **Le proposer
  soi-même** aussi : l'utilisateur ne le demandera pas, il l'a dit
  explicitement le 2026-08-05.
- **Publier une version** (rare : PyPI, dépôt citable) :
  `python scripts/set_version.py 0.3.0` accorde `pyproject.toml`,
  `CITATION.cff` et `codemeta.json`. Ne JAMAIS y écrire un numéro à la
  main : `tests/test_citation.py` refuse le désaccord. Puis section de
  CHANGELOG, commit, `git tag -a vX.Y.Z`, `git push --tags`.
- **SWHID** : `swh:1:rev:<hash du commit>` EST l'identifiant Software
  Heritage d'une révision git, calculable sans aucun appel d'API. Il ne
  résout que si le dépôt est archivé : fait le 2026-07-22 pour les trois,
  et SWH revisite tout seul ensuite. Rien à refaire par version.
- **Un changement du moteur nécessaire à card** (comme `param_cols`) :
  publier ici ET remonter `stase>=` dans le pyproject de card, sinon la
  contrainte ment.

## Points d'architecture à connaître

- La sortie de `process_extraction` se **réinjecte** comme entrée
  (enchaînements type QMNA). Les colonnes creuses d'un fan-out
  `keep='all'` sont marquées dans `DataFrame.attrs[_SPARSE_ATTR]` et
  compactées à l'appel suivant.
- L'identifiant est converti en `Categorical` en début d'appel (perf) ;
  tous les `groupby` passent `observed=True` explicitement (sinon les
  catégories vidées par un filtre `period` créent des lignes fantômes).
- En multi-variables, les colonnes clés (`_hy`, `_ym`, `_season_*`,
  `_yd`) sont calculées au premier usage puis réutilisées, ne pas les
  recalculer par variable.
- `process_trend` unit les colonnes identifiantes multiples avec le
  séparateur `\x1f` (jamais `_` : les IDs peuvent en contenir) et
  restitue les colonnes d'origine en sortie. `H` est un booléen nullable.
- **Grille temporelle matérialisée** (0.2) : `process_extraction`
  détecte la résolution PAR SÉRIE (erreur si les séries mélangent des
  pas différents) puis insère une ligne NaN à chaque pas manquant
  (`_complete_grid`, partagé avec `process_trend` qui réindexe de même
  ses séries agrégées : pente de Sen et corrections AR1/LTP supposent
  un pas régulier). `keep='all'` renvoie la grille complète, pas les
  lignes d'origine. Séries à dates hors grille : laissées telles
  quelles avec warning.
- Divergences R intentionnelles (NApct calendaire réel et seuil
  max_na_pct comparé au taux exact, grille matérialisée, bug yearday R
  non reproduit, précision MLE Hurst) : documentées dans
  `dev/r-origin.md`, ne pas « corriger ». Le détail historique
  complet de la conversion est dans `dev/plans/2026-07-15_r-conversion.md`
  (l'ancien `EXstat_Claude/CLAUDE.md`).
