> **Statut : ce qui reste à faire, et seulement cela,** pour le moteur.
> Ce qui est fait en sort et devient une entrée de `CHANGELOG.md`, qui
> renvoie au document expliquant le détail. Un point devenu trop lourd
> ouvre un plan daté dans `dev/plans/`.

# Feuille de route de stase (mise à jour 2026-11-06)

## Dans EXstat, un geste de l'utilisateur (2026-11-06)

Les en-têtes de `R/process_extraction.R` et `R/process_trend.R` nomment
encore Éric Sauquet et Jean-Philippe Vidal, qui ont aidé à la conception
sans écrire de code (règle commune : `dev/decisions.md` de card, « Qui est
auteur »). Retirés de l'en-tête Python ; dans le dépôt R, resté sans
intervention de l'IA, c'est à l'utilisateur de le faire.

## `sampling_period` par série via dictionnaire

Fonctionnalité listée à l'époque de la conversion, jamais faite parce
que `Adaptive` couvre le besoin autrement. À reprendre seulement si un
usage réel apparaît côté card, pas par symétrie d'API.
