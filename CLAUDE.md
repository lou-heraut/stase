# CLAUDE.md : stase

## Contexte

stase (*STatistical Aggregation & Stationarity Evaluation*) est le port
Python du package R **EXstat** : agrégation de chroniques journalières
hydroclimatiques en variables temporelles (annuelles, saisonnières,
mensuelles…) puis analyse de stationnarité (Mann-Kendall généralisé,
pente de Sen). Il sert de **moteur de données** au package `card`
(`CARD_project/card`), qui exécute les fiches CARD YAML.

Repos liés (séparation actée le 2026-07-15 : les repos R restent
« propres, sans IA » : référence de validation uniquement ; tout le
travail IA se fait dans stase et card) :
- `EXstat_project/EXstat/` : code R d'origine, en maintenance
  (ne pas modifier, ne pas y ajouter de fichiers IA)
- `CARD_project/card/` : consommateur de stase (son CHANGELOG.md trace
  ce qui a changé de son côté) ; `CARD_project/CARD-R/` : R d'origine,
  même statut que EXstat
- `EXstat_project/EXstat_Claude/` : ancien dossier de travail de la
  conversion (pas un repo git), désormais archivable. Son CLAUDE.md
  historique est copié dans `docs/dev/archive/CONVERSION_R.md` et le
  harnais de validation croisée dans `docs/dev/archive/harnais_R/` ; ses
  CSVs de référence complets (`EXstat_py/ref_output/`, `ref_trend/`) se
  régénèrent avec ces scripts

Où lire quoi. Un rôle par fichier, chacun l'annonce dans un bandeau de
statut en tête ; ne jamais recopier d'un fichier à l'autre, renvoyer.
- `CHANGELOG.md` (racine) : ce qui a changé, quand, et où lire le détail.
- docs/dev/, normes en vigueur : `ORIGINE_R.md` (origine R, validation,
  divergences à ne jamais « corriger »), `RENAMING_PY.md` (noms R vers
  Python).
- docs/dev/archive/ : documents d'époque, non maintenus (`PLAN.md`,
  `CONVERSION_R.md`, `harnais_R/`).

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

## Règles du projet (décisions utilisateur, 2026-07-12)

1. **`tools.py` est gelé.** Port validé contre R (73/73). Aucune
   modification sans accord explicite de l'utilisateur. Deux exceptions
   ont été validées et faites le 2026-07-12 : rng/seed LTP
   (reproductibilité des ex-æquo) et variance LTP par blocs (mémoire
   bornée), toutes deux prouvées par tests d'équivalence dans
   `tests/test_tools.py`. Interactions toujours permises : tests goldens,
   documentation des limites, correction d'une vraie divergence de
   résultat avec R (aucune connue).
2. **Détection des colonnes par type, jamais par nom.** datetime → date,
   texte → identifiant de série, numérique → valeurs. Ne jamais proposer
   de paramètre `id_col=`/`date_col=`. Les problèmes de détection se
   traitent par de meilleurs messages d'erreur.
3. **Wording générique.** Jamais « station » dans les messages, la doc ou
   le code : dire « série ». stase est agnostique du domaine.
4. **La version du paquet ne sert qu'à publier**, on n'y touche pas au
   quotidien. Le seul geste à ne pas oublier est l'entrée `## Non publié`
   du CHANGELOG quand un changement mérite d'être retenu. Une exception :
   si un changement du moteur devient nécessaire à card (comme
   `param_cols` l'a été), bump ici ET remontée de la contrainte `stase>=`
   dans le pyproject de card, sinon la contrainte ment. Le proposer
   soi-même.

## API

Canonique : `stase.extract` et `stase.trend` (les noms de fonctions R
restent en alias, mais paramètres et colonnes de sortie sont renommés
sec : table dans docs/dev/RENAMING_PY.md ; la colonne de date de sortie
reprend le nom de la colonne d'entrée). En interne, extraction.py et
trend.py gardent les noms historiques via un pont en tête de fonction :
ne pas « nettoyer » ce pont, il isole la logique validée par les
goldens. Style : pas de préfixe redondant, pas de tiret quadratin (—) dans la
prose, docs, messages ni réponses (marqueur de texte IA, rebute des
utilisateurices : reformuler), références R limitées à une mention
(docs/dev/ORIGINE_R.md).

## Commandes

```bash
.python_env/bin/python -m pytest        # suite complète (~2 s)
# validation côté consommateur :
cd ../../CARD_project/card && .python_env/bin/python -m pytest
```

Environnement : `.python_env/` (pandas 3.0.3, numpy 2.5.1) ;
dépendance déclarée pandas>=2.2 (include_groups, observed=).

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
  docs/dev/ORIGINE_R.md, ne pas « corriger ». Le détail historique
  complet de la conversion est dans `docs/dev/archive/CONVERSION_R.md`
  (archive de l'ancien `EXstat_Claude/CLAUDE.md`).
