> **Statut : repères en vigueur.** Les choix qui engagent le moteur,
> chacun avec sa date et sa raison : on les suit tant qu'ils servent, et
> leur raison dit quand l'un d'eux ne tient plus. Les écarts assumés avec
> le R ont leur propre fichier, `dev/r-origin.md` ; la table des noms,
> `dev/renaming.md`. Réunis ici le 2026-11-06 depuis le `CLAUDE.md`, qui
> garde une ligne par règle.

# Décisions de stase

## Les dépôts R restent sans IA (2026-07-15)

Séparation actée à la clôture de la conversion : les dépôts R restent
« propres, sans IA », référence de validation uniquement, et tout le
travail assisté se fait dans stase et dans card.

- `EXstat_project/EXstat/` : le code R d'origine, en maintenance. Ne pas
  le modifier, ne pas y ajouter de fichiers IA.
- `CARD_project/CARD-R/` : le R d'origine des fiches, même statut.
- `EXstat_project/EXstat_Claude/` : l'ancien dossier de travail de la
  conversion, qui n'est pas un dépôt git et peut être archivé. Son
  `CLAUDE.md` est conservé dans `dev/plans/2026-07-15_r-conversion.md`
  et le harnais de validation croisée dans `dev/r-harness/` ; ses CSV de
  référence complets (`EXstat_py/ref_output/`, `ref_trend/`) se
  régénèrent avec ces scripts.

## Les règles du moteur (décisions de l'utilisateur, 2026-07-12)

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
4. **Docstring d'une fonction PUBLIQUE** (tout ce que `stase.__all__`
   annonce) : **anglais, sections NumPy**. C'est de la documentation,
   pas un commentaire, et c'est la norme du Python scientifique. Mesuré
   par `tests/test_docstrings.py`, qui porte les raisons. Même règle et
   même garde dans card : les deux paquets s'installent et se lisent
   ensemble, une norme qui s'arrêterait à la frontière de l'un ne
   servirait à rien. La machinerie interne écrit dans la langue qu'elle
   veut, elle s'adresse à qui ouvre le fichier.
   **Le balisage du corps est du MARKDOWN**, pour tout le paquet : un
   accent grave SIMPLE pour du code, aucun rôle `:func:`. Le style NumPy
   est né pour Sphinx et sa syntaxe en ligne est du reST ; un
   générateur moderne découpe les sections NumPy puis rend le corps en
   Markdown, et le reST y ressort en clair. Normalisé le 2026-08-13 dans
   les deux paquets, mesuré côté card par `tests/test_docstrings.py`.
5. **Versions.** On n'y touche pas au quotidien. Une modif notable se
   note sous `## Non publié` du CHANGELOG ; publier se fait par
   `scripts/set_version.py`, jamais à la main ; et si un changement du
   moteur devient nécessaire à card (comme `param_cols` l'a été), il faut
   publier ICI **et** remonter la contrainte `stase>=` dans le pyproject
   de card, sinon elle ment. Doctrine complète : « Versions, en cinq
   phrases », en tête de `CHANGELOG.md`.
