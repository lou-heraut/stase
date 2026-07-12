# PLAN — Audit et améliorations de stase (2026-07-12)

Audit du package stase (port Python d'EXstat, moteur de card) réalisé le
2026-07-12 par comparaison avec EXstat (R), EXstat_Claude (1re conversion)
et l'usage réel dans card. État de départ : pytest stase 14/14 OK,
pytest card 40/40 OK, sous pandas 3.0.3 / numpy 2.5.1.

Chaque bug listé en phase 1 a été **reproduit et confirmé par exécution**
(pas seulement par lecture du code).

Après chaque phase : `pytest` dans stase ET dans card, plus le corpus
lourd de card (`tests/run_py_corpus.py` / `validate_py.py`, réf. 552 ok)
pour les phases touchant au moteur.

**Priorité (décision utilisateur 2026-07-12)** : le processus
d'agrégation (extraction.py) d'abord — soit 1.1, 1.4, 1.5, puis les tests
(phase 2), puis 4.1. Les correctifs 1.2 et 1.3 portent sur l'assemblage
du tableau de résultats dans trend.py (pandas pur, aucune formule
statistique touchée) et passent après. Aucune erreur de portage n'a été
détectée dans le cœur statistique tools.py (validé 73/73 et 896/896
contre R) : rien à y corriger.

---

## Phase 1 — Correctifs de fiabilité (bugs confirmés)

### 1.1 Stations fantômes en `time_step='none'` après filtre `period`
`_extract_none` fait `groupby(id_col, observed=False)` explicitement
(extraction.py:1781). La colonne id étant convertie en Categorical **avant**
le filtre `period`, une station entièrement exclue par `period` reste comme
catégorie inutilisée et produit une ligne fantôme `NaN` en sortie.
Incohérent avec `time_step='year'` (aucune ligne).

Reproduit : S2 sans donnée dans la période → sortie `[S1: 9.98, S2: NaN]`.

**Fix** : passer `observed=True` (ou `remove_unused_categories()` juste
après le filtre `period`, comme le fait déjà `_process_adaptive`
extraction.py:1915). Vérifier au passage tous les `groupby` du package pour
fixer `observed=` explicitement (le défaut a changé entre pandas 2 et 3).

### 1.2 Corruption des IDs multiples dans `process_trend`
trend.py:294 unit les colonnes id avec `"_"`, puis trend.py:550 re-split
avec `n=len(cols)-1`. Si le **premier** id contient un `_`, le split coupe
au mauvais endroit. Reproduit : id=`S_1`, model=`M1` → sortie id=`S`,
model=`1_M1` (données corrompues silencieusement).

**Fix** : conserver les colonnes id d'origine à côté de la clé unie (merge
final sur la clé) ou utiliser un séparateur non imprimable (`"\x1f"`) pour
l'interne uniquement. Ajouter un test avec `_` dans les IDs.

### 1.3 Colonne `H` en dtype object avec `None`
Une station avec n<3 valeurs valides donne `H=None` → la colonne `H`
devient object (mélange bool/None). `trendEX[trendEX.H]` plante et tout
filtrage booléen devient fragile. Reproduit.

**Fix** : convertir en dtype `boolean` nullable (pd.NA) à l'assemblage
final de `process_trend` ; idem `p`, `a`, `b` en float propre. Documenter
dans la docstring. Vérifier l'impact côté card (`functions/trend.py`).

### 1.4 IDs numériques → stations fusionnées + erreur trompeuse
`_detect_columns` ne reconnaît l'id que s'il est str. Des codes de station
en int sont classés colonnes de valeur, toutes les stations fusionnent en
`"time serie"` et l'utilisateur reçoit une erreur « dates dupliquées »
sans rapport avec la cause. Reproduit.

**Fix — diagnostic uniquement** (décision utilisateur 2026-07-12 : la
détection par type des colonnes est la philosophie de stase, pas de
paramètre `id_col=` par nom) : quand aucune colonne texte n'a été trouvée
(id fictif) ET que des dates dupliquées sont détectées, enrichir le
message d'erreur avec la cause probable et la conversion `astype(str)`.
Zéro changement d'API ni de comportement de détection.

> ✅ **Fait (2026-07-12)** — hint ajouté dans l'erreur des doublons.
> Au passage, wording générique appliqué partout (décision utilisateur :
> jamais « station », toujours « série ») : messages, verbose, docstrings,
> README, helpers internes renommés (`_mk_series`, `_change_series`).

### 1.5 Contrainte de dépendance pandas incorrecte
pyproject déclare `pandas>=2.0`, mais `trend.py` utilise
`include_groups=False` (pandas ≥ 2.2) **sans** le fallback try/except
présent dans extraction.py, et le comportement `observed` diffère entre
pandas 2 et 3. Le package n'est validé que sous pandas 3.0.3.

**Fix** : monter à `pandas>=2.2` (minimum), fixer `observed=` partout
(cf. 1.1), et idéalement tester une fois sous pandas 2.2 pour valider la
borne basse — sinon déclarer `pandas>=3.0`.

---

## Phase 2 — Tests (le plus gros manque)

> ✅ **Fait en grande partie (2026-07-12)** — 59 tests (14 → 59) :
> - `tests/data/ref_trend/` (goldens R complets, 52 Ko) +
>   `tests/data/ref_extraction/` (input commun + 11 sorties R, ~500 Ko).
> - `tests/test_tools.py` : 13 scénarios MK INDE/AR1/LTP vs R (tolérance
>   1e-10, LTP 3e-3 — l'ancienne 2e-3 dépassée de 4e-5 sous numpy 2.5),
>   getMKStat/ties/AR1/FDR, cas limites figés (n<3, constante, tout-NaN).
> - `tests/test_trend.py` : les 5 scénarios process_trend vs R + cas
>   limites (série courte → H NA, période hors données, entrée vide).
> - `tests/test_golden_extraction.py` : 11 scénarios R couvrant les 7
>   time_steps (NApct strict là où R et Python concordent).
> - pyproject : suppression des `filterwarnings` globaux (la suite passe
>   même avec `-W error::FutureWarning`) ; `.pytest_cache/` gitignoré.
> - card revalidé : 40/40.
>
> Reste (2.2 partiel) : cas limites extraction supplémentaires — stations
> fantômes après `period` pour tous les time_steps (à écrire AVEC le fix
> 1.1), id numérique → message enrichi (fait), entrée vide.

La validation scientifique R↔Python (73/73 tools, 896/896 process_trend,
22/22 extraction) vivait dans `EXstat_Claude/EXstat_py/` — **hors du repo
stase**. Dans stase, `tools.py` et `trend.py` n'avaient aucun test.

### 2.1 Rapatrier des goldens figés
Copier dans `tests/data/` un sous-ensemble des CSVs de référence R
(`EXstat_Claude/EXstat_py/ref_output/` et `ref_trend/`) et écrire
`tests/test_tools.py` + `tests/test_trend.py` qui les rejouent en pytest
(tolérances : 1e-10 INDE/AR1, 2e-3 LTP — cf. divergence MLE Hurst
documentée). Le repo devient auto-suffisant pour la non-régression.

### 2.2 Tests de cas limites
- tools : n<3, série constante (S=0), série toute-NaN, NaN par paires
  dans getMKStat, FDR avec p-values NaN.
- trend : station unique, `period_trend` hors données, `period_change`,
  `to_normalise` dict incomplet, IDs avec `_` (cf. 1.2), H nullable
  (cf. 1.3).
- extraction : stations fantômes après `period` pour tous les time_steps
  (cf. 1.1), entrée vide, id numérique avec `id_col=` explicite (cf. 1.4).

### 2.3 Hygiène pytest
`filterwarnings` ignore actuellement **globalement** UserWarning et
FutureWarning → les tests ne verront jamais une nouvelle dépréciation
pandas ni un warning de régression. Restreindre aux warnings attendus
(par test, via `pytest.warns` / marqueurs ciblés).
Ajouter `.pytest_cache/` au .gitignore.

---

## Phase 3 — Robustesse des entrées

> **Décision utilisateur (2026-07-12)** : `tools.py` (cœur statistique
> validé contre R : MK, Sen, Hurst, LTP, FDR) est **gelé** — aucune
> modification de code. Les deux points relevés à l'audit (RNG global non
> seedable dans `randomizedNormalScore` en cas d'ex-æquo ; mémoire du
> calcul de variance LTP en O(M²) au-delà de n≈150) sont rétrogradés en
> simples **notes de documentation** (docstring/README : « LTP :
> non-déterministe avec ex-æquo, prévu pour des séries annuelles,
> pas millénaires »), sans toucher au code.

### 3.3 Validation d'entrées complémentaires
- `sampling_period` : valider le format `MM-DD` (regex) avec message
  clair — aujourd'hui un format invalide donne une erreur pandas obscure.
- `Adaptive` : si `funct` retourne une valeur absente des moyennes
  mensuelles (ex. `np.nanmean`), repli **silencieux** sur `default` —
  émettre un warning.
- Kwargs-références de colonnes (`_resolve_column_references`) : une
  valeur str qui matche par hasard un nom de colonne devient une référence
  silencieusement. Émettre un warning informatif à la conversion
  (« kwarg 'lim' interprété comme référence à la colonne 'upLim' ») —
  card en dépend, ne pas changer le mécanisme, juste le rendre visible.
- Documenter l'ambiguïté bool des tuples funct : `(fn, "Q", True)` =
  is_date mais `(fn, "Q", True, {})` = littéral positionnel True.

---

## Phase 4 — Efficacité

### 4.1 Hydro-year calculé une fois par appel (pas par variable)
En multi-variables, `_extract_year` recalcule `_assign_hydro_year` (scan
complet O(N)) pour **chaque** variable alors que `sampling_period` est
identique. Factoriser : assigner `_hy` une fois avant la boucle des
functs. Idem `_ym`/`_season_*` pour les autres time_steps. Gain attendu
sensible sur les fiches CARD multi-variables sur 5M lignes.

### 4.2 Micro-optimisations (opportunistes, si mesurées utiles)
- trend.py:299 `groupby().apply(lambda s: s.duplicated().any())` →
  `dataEX.duplicated([id_col, date_col]).any()` (vectorisé).
- `_extract_year_season` : caches Date par clé unique comme dans
  `_extract_year` (list comprehensions par ligne actuellement).
- Rejouer `benchmark_real.py` (EXstat_Claude) après 4.1 pour chiffrer.

---

## Phase 5 — UX et documentation

### 5.1 Réécrire CLAUDE.md
L'actuel décrit l'arborescence d'EXstat_Claude (`EXstat_py/`, chemins de
venv et scripts inexistants ici). Le réécrire pour stase : structure
src/, tests, lien card, divergences R conservées (résumé), commandes.
L'historique de conversion détaillé peut rester référencé vers
EXstat_Claude.

### 5.2 Cohérence de l'API
- `verbose` : défaut `False` dans process_extraction, `True` dans
  process_trend → harmoniser sur `False`.
- Alias snake_case validés par l'utilisateur (2026-07-12) :
  `general_mann_kendall` et `field_significance_fdr` exposés dans
  `__init__.py` **en plus** des noms hérités de R (compat card intacte).
  Simple alias d'export — pas de modification dans tools.py.
- `_verbose_box` dupliqué dans extraction.py et trend.py → module
  interne partagé.
- Retours vides : `pd.DataFrame()` sans colonnes → retourner un DataFrame
  avec les colonnes attendues quand c'est possible (facilite les concat
  en aval).

### 5.3 Documentation utilisateurice
- README : ajouter une section API courte (formats des tuples funct,
  `keep`, colonnes creuses/attrs, NApct et ses divergences R
  intentionnelles) + un exemple process_trend complet.
- Docstrings : langue mixte FR/EN → choisir (FR pour cohérence actuelle)
  et compléter les paramètres manquants de process_trend.
- `py.typed` + annotations sur les signatures publiques (les internes en
  ont déjà une partie).

---

## Hors périmètre (décisions à garder en tête)

- **`tools.py` est gelé** (décision utilisateur 2026-07-12) : pas de
  refactor, pas de seed LTP, pas de chunking mémoire, pas d'alias
  snake_case (`general_mann_kendall`…). Seules interactions autorisées :
  le figer par des tests goldens (phase 2) et documenter ses limites.
- Les divergences R intentionnelles (NApct calendaire réel, bug yearday R
  non reproduit, précision MLE Hurst) sont **documentées et assumées** —
  ne pas « corriger ».
- `sampling_period` par station via dict (feature Python-only listée dans
  l'ancien CLAUDE.md) : couvert autrement par `Adaptive` ; à ne faire que
  sur besoin réel côté card.
- La publication GitHub (remotes, noms de repos) est suivie dans
  `card/ROADMAP.md`, pas ici.
