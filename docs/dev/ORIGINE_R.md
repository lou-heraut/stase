# Origine : conversion depuis le package R EXstat

stase est le port Python du package R [EXstat](https://github.com/lou-heraut/EXstat)
(INRAE, UR RiverLy). La conversion a été validée nombre à nombre contre R,
et les références de cette validation sont commitées dans `tests/data/`
(le repo est auto-suffisant pour la non-régression) :

- 13 scénarios Mann-Kendall (INDE, AR1, LTP) : concordance à 1e-10
  (LTP à 3e-3, cf. divergence de précision ci-dessous) ;
- 5 scénarios process_trend complets : concordance à 1e-10 ;
- 11 scénarios d'extraction couvrant les 7 time_steps.

L'historique détaillé de la conversion (choix d'implémentation,
optimisations, phases de validation) est conservé dans
[CONVERSION_R.md](CONVERSION_R.md), et le harnais de validation croisée
d'origine dans [harnais_R/](harnais_R/).

## Divergences intentionnelles avec le R

Ces écarts sont assumés et ne seront pas « corrigés » :

- **NApct** utilise le nombre réel de jours calendaires comme dénominateur
  (R : constantes 365.25 / 30.4375) et s'adapte à la résolution de
  l'entrée (journalière, mensuelle, saisonnière).
- **Groupe sans valeur valide → NaN, pour toutes les fonctions** (0.3),
  y compris les sommes : une année entièrement lacunaire est une
  lacune, pas 0 (R : `sum(na.rm=TRUE)` sur tout-NA vaut 0). Et les
  alias Cython internes sont restreints aux variantes nan* : aliaser
  np.median (pas de dispatch pandas), les builtins (ordre-dépendants
  face aux NaN) ou np.nanstd (ddof=0 vs ddof=1 pandas) changeait la
  valeur, pas seulement la vitesse (test d'équivalence dédié).
- **Le seuil `max_na_pct` se compare au NApct exact**, non arrondi
  (R comparait la valeur arrondie à 1 décimale : un taux réel de
  3.04 % passait un seuil de 3). L'arrondi à 1 décimale ne subsiste
  que dans la colonne `na_pct` de sortie (affichage).
- Le bug R du NApct des jours 1 et 365 en `yearday` n'est pas reproduit.
- **Grille temporelle matérialisée** (stase 0.2) : les pas de temps
  absents de l'entrée (lignes manquantes) sont insérés en NaN par série
  dans `process_extraction`, et dans les séries agrégées de
  `process_trend`. R supposait des chroniques denses sans le vérifier :
  sur des chroniques trouées, les dates d'extremum (`is_date`), les
  fenêtres glissantes, `max_na_years` et la pente de Sen y étaient
  silencieusement faux (biais de pente mesuré à +38 % avec 10 années
  absentes sur 40). Séries à dates irrégulières (hors grille) : laissées
  telles quelles avec warning.
- **Résolution homogène requise** : le pas de temps est détecté par
  série (R et stase 0.1 ne regardaient que la première) et les séries
  d'une même extraction doivent le partager, erreur explicite sinon
  (agréger un max journalier et un max mensuel sous le même nom
  comparerait des grandeurs différentes).
- **Précision du MLE de Hurst** (LTP) : scipy optimise plus finement que
  l'`optimize` de R (écarts possibles d'environ 2e-3 sur la p-value, le
  verdict H est identique).
- **process_trend** : les colonnes listes de R deviennent des colonnes
  séparées (`period_trend_start` / `period_trend_end`, etc.) et `H` est
  un booléen nullable (NA si moins de 3 valeurs valides).
- **`suffix` se décide par argument, pas par fonction.** R teste si au
  moins un argument d'une fonction admet une variante suffixée présente
  dans les données (`where_no_suffix`) ; si oui il suffixe alors *tous*
  ses arguments d'un bloc, et ceux qui n'ont pas de variante deviennent
  NA puis sont passés à la fonction comme chaînes littérales. Un calcul
  mêlant une série partagée et une colonne qui varie par scénario y est
  donc silencieusement faux. stase applique la règle référence par
  référence : la colonne suffixée si elle existe, la colonne de base
  sinon, kwargs-colonnes compris. La sortie est suffixée dès qu'une
  référence l'a été, et une fonction dont aucune référence ne varie est
  émise une seule fois sans suffixe (donc calculée une fois, pas une
  fois par suffixe). Sur le cas nominal du R, où toutes les colonnes
  référencées ont une variante, le résultat est inchangé.
- **Tirage des ex-æquo en LTP** : comme en R (ties.method='random',
  choix documenté dans tools.R, Hamed 2008 ne prescrit rien), mais
  rendu reproductible par le paramètre `seed` de `stase.trend`.
- **Unité des indicateurs de tendance** (2026-07-20). En R,
  `a_normalise` contenait la pente en % de la moyenne quand la variable
  était normalisée, et une COPIE de la pente absolue `a` sinon ; idem
  pour `change`. Deux variables d'une même sortie pouvaient donc se
  retrouver dans des unités différentes sous le même nom de colonne,
  sans rien pour les distinguer (seul `mean_period_trend` à NA le
  laissait deviner). stase sépare les deux registres : `a` et `change`
  portent toujours l'absolu, `a_relative` et `change_relative` toujours
  le pourcentage, et ces dernières valent NaN quand la variable n'est
  pas relative. Aucune information n'est perdue, la copie du R étant
  redondante avec `a`. Les bornes de quantiles suivent la même
  séparation : `a_min`/`a_max` et `change_min`/`change_max` (nouvelles,
  dans l'unité de la variable) reprennent les valeurs des
  `a_normalise_min`/`max` du R dans le cas non normalisé, et
  `a_relative_min`/`max`, `change_relative_min`/`max` les reprennent
  dans le cas normalisé. `mean_period` est désormais toujours calculée.
  Divergences figées par `tests/test_trend.py` (scénarios 2 et 4), qui
  continuent de vérifier la parité R sur `a`, `p` et `b`.
- **Le paramètre `meta=` de `process_trend` a été retiré** (2026-07-20).
  Il acceptait la table de métadonnées de `card.extract`, ce qui faisait
  dépendre stase du format d'un paquet aval, et il court-circuitait la
  validation de `relative` (une variable non couverte y retombait
  silencieusement sur `True`, au lieu de lever). Le caractère relatif se
  passe désormais par `relative={variable: bool}`, la forme générique
  déjà validée contre les goldens R. C'est à card de traduire ses
  fiches.

## Noms hérités du R

L'API canonique est `stase.extract` / `stase.trend`. Les noms de
fonctions du R restent valides en alias (`process_extraction`,
`process_trend`, `GeneralMannKendall`, `fieldSignificance_FDR`), mais
les paramètres et colonnes de sortie utilisent les nouveaux noms partout
(renommage sec) : table complète dans [RENAMING_PY.md](RENAMING_PY.md).
