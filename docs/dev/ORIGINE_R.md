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
optimisations, phases de validation) est conservé dans le dossier
`EXstat_Claude/` du projet d'origine.

## Divergences intentionnelles avec le R

Ces écarts sont assumés et ne seront pas « corrigés » :

- **NApct** utilise le nombre réel de jours calendaires comme dénominateur
  (R : constantes 365.25 / 30.4375) et s'adapte à la résolution de
  l'entrée (journalière, mensuelle, saisonnière).
- Le bug R du NApct des jours 1 et 365 en `yearday` n'est pas reproduit.
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
