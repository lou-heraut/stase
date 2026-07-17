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
- **Tirage des ex-æquo en LTP** : comme en R (ties.method='random',
  choix documenté dans tools.R, Hamed 2008 ne prescrit rien), mais
  rendu reproductible par le paramètre `seed` de `stase.trend`.

## Noms hérités du R

L'API canonique est `stase.extract` / `stase.trend`. Les noms de
fonctions du R restent valides en alias (`process_extraction`,
`process_trend`, `GeneralMannKendall`, `fieldSignificance_FDR`), mais
les paramètres et colonnes de sortie utilisent les nouveaux noms partout
(renommage sec) : table complète dans [RENAMING_PY.md](RENAMING_PY.md).
