> **Statut : registre vivant.** Ce fichier ne contient que des pistes
> **ouvertes**. Un chantier livré en sort et devient une entrée de
> `CHANGELOG.md`, à la racine du dépôt, qui renvoie au document
> expliquant le détail.

# CHANTIERS : pistes ouvertes (ouvert le 2026-07-22)

## Discipline de version et étiquetage

Constat fait en écrivant le CHANGELOG, le 2026-07-22. Le numéro de
version de `pyproject.toml` est passé directement de 0.1.0 à 0.4.0 le
2026-07-20 : les jalons 0.2.0 et 0.3.0 avaient été annoncés dans des
messages de commit sans que le fichier soit touché. Et depuis, le rôle
`param_cols` est arrivé sans bump.

Conséquence concrète : card déclare `stase>=0.4.0` et utilise
`param_cols`, qui n'existe pas dans le 0.4.0 tel qu'il a été numéroté.
Rien ne casse aujourd'hui parce que l'installation se fait depuis la
branche principale, mais la contrainte ment. À trancher avec
l'utilisateur :

- bumper en 0.5.0 pour couvrir `param_cols`, et remonter la contrainte
  de card en conséquence ;
- poser des tags git sur les jalons, faute de quoi une version ne
  désigne rien d'installable ;
- bumper au moment du changement, pas rétroactivement.

## `sampling_period` par série via dictionnaire

Fonctionnalité listée à l'époque de la conversion, jamais faite parce
que `Adaptive` couvre le besoin autrement. À reprendre seulement si un
usage réel apparaît côté card, pas par symétrie d'API.

## `period` par série, depuis des colonnes de paramètre

Ouvert le 2026-07-22, prérequis d'un chantier de card (« convertir les
12 fiches à horizon figé au modèle suffixe »).

Le filtre `period` de `process_extraction` prend deux dates littérales et
s'applique identiquement à toutes les séries. Or card a besoin qu'une
période varie **par série** : un horizon défini par degré de
réchauffement ne tombe pas aux mêmes dates d'une station à l'autre.

Le rôle `param_cols` transporte déjà des bornes constantes par série, et
les fonctions savent les recevoir en kwargs : c'est ainsi que les fiches
delta ont été converties. Ce qui manque est l'équivalent pour le filtre
de période lui-même, qui n'est pas une fonction mais un paramètre du
moteur.

Deux voies à instruire :
- étendre `period` à accepter des noms de colonnes en plus de dates,
  au prix d'un paramètre à deux sens ;
- un paramètre distinct, plus explicite mais une surface de plus.

Contrainte à ne pas perdre : le filtre s'applique aujourd'hui avant
l'agrégation et avant le comptage des lacunes, et le passage par série
doit garder cet ordre pour ne pas changer les résultats existants.
