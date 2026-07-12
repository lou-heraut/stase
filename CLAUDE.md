# CLAUDE.md — stase

## Contexte

stase (*STatistical Aggregation & Stationarity Evaluation*) est le port
Python du package R **EXstat** : agrégation de chroniques journalières
hydroclimatiques en variables temporelles (annuelles, saisonnières,
mensuelles…) puis analyse de stationnarité (Mann-Kendall généralisé,
pente de Sen). Il sert de **moteur de données** au package `card`
(`CARD_project/card`), qui exécute les fiches CARD YAML.

Repos liés :
- `EXstat_project/EXstat/` — code R d'origine (référence, ne pas modifier)
- `EXstat_project/EXstat_Claude/` — première conversion Python ; contient
  les scripts de validation croisée R↔Python et les CSVs de référence
  complets (`EXstat_py/ref_output/`, `ref_trend/`)
- `CARD_project/card/` — consommateur de stase (sa ROADMAP.md documente
  la refonte commune) ; `CARD_project/CARD-R/` — R d'origine

## Structure

```
src/stase/
  extraction.py   # process_extraction — moteur d'agrégation (cœur du projet)
  trend.py        # process_trend — enveloppe MK + Sen par série × variable
  tools.py        # cœur statistique : MK INDE/AR1/LTP, Sen, Hurst, FDR — GELÉ
  _display.py     # _verbose_box partagé
tests/
  test_extraction.py         # comportement du moteur
  test_golden_extraction.py  # 11 goldens R (7 time_steps)
  test_tools.py              # 13 goldens MK R + cas limites figés
  test_trend.py              # 5 goldens process_trend R + cas limites
  data/                      # CSVs de référence R (repo auto-suffisant)
PLAN.md           # audit 2026-07-12 + plan d'amélioration (suivi à jour)
```

## Règles du projet (décisions utilisateur, 2026-07-12)

1. **`tools.py` est gelé.** Port validé contre R (73/73). Pas de refactor,
   pas de seed RNG, pas d'optimisation mémoire. Seules interactions
   permises : tests goldens et documentation des limites. Exception :
   une vraie divergence de résultat avec R se corrige (aucune connue).
2. **Détection des colonnes par type, jamais par nom.** datetime → date,
   texte → identifiant de série, numérique → valeurs. Ne jamais proposer
   de paramètre `id_col=`/`date_col=`. Les problèmes de détection se
   traitent par de meilleurs messages d'erreur.
3. **Wording générique.** Jamais « station » dans les messages, la doc ou
   le code : dire « série ». stase est agnostique du domaine.

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
  `_yd`) sont calculées au premier usage puis réutilisées — ne pas les
  recalculer par variable.
- `process_trend` unit les colonnes identifiantes multiples avec le
  séparateur `\x1f` (jamais `_` : les IDs peuvent en contenir) et
  restitue les colonnes d'origine en sortie. `H` est un booléen nullable.
- Divergences R intentionnelles (NApct calendaire réel, bug yearday R
  non reproduit, précision MLE Hurst) : documentées dans le README —
  ne pas « corriger ». Le détail historique complet de la conversion est
  dans `EXstat_Claude/CLAUDE.md`.
