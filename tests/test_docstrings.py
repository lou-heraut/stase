# Copyright 2021-2026 Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the stase Python package (Python port of the
# EXstat R package).
#
# stase is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""La docstring d'une fonction PUBLIQUE est de la documentation.

Deux règles, et elles ne valent que pour `stase.__all__`, c'est-à-dire ce
qu'un utilisateur appelle. La machinerie interne écrit dans la langue
qu'elle veut et comme elle veut : elle s'adresse à qui ouvre le fichier.

**Anglais.** C'est la langue de la publication scientifique, celle du
README. Une API française sous une vitrine anglaise oblige le lecteur à
changer de langue au moment précis où il passe de la promesse à l'usage.

**Sections NumPy.** `Parameters`, `Returns`, et les autres au besoin.
C'est la norme du Python scientifique, et c'est ce qu'un générateur de
documentation sait rendre en tableaux plutôt qu'en pavé.

Même fichier, mêmes règles, dans card : les deux paquets s'installent
ensemble et se lisent ensemble, une norme qui s'arrêterait à la frontière
de l'un des deux ne servirait à rien. Appliquées le 2026-08-11.
"""

import re

import pytest

import stase

# Mots français sans équivalent anglais, donc sans faux positif possible
# sur une docstring correcte.
FRANCAIS = re.compile(
    r"\b(fiche|fiches|une|des|qui|dans|pour|avec|chaque|selon|sont|"
    r"est|les|la|du|aux|leur|cette|ce|par|sans|plus|donc)\b"
)
SECTION = re.compile(r"^\s*(Parameters|Returns|Yields)\s*\n\s*-{3,}", re.M)


def _publiques():
    return [(n, getattr(stase, n)) for n in stase.__all__
            if callable(getattr(stase, n))]


def test_the_public_api_is_documented_in_english():
    """Une docstring publique qui parle français renvoie le lecteur à sa
    langue au moment où il cherche à s'en servir.

    Le seuil est à deux mots distincts : un accident de citation ne doit
    pas faire échouer, une phrase française doit.
    """
    fautifs = {}
    for nom, objet in _publiques():
        trouves = set(FRANCAIS.findall((objet.__doc__ or "").lower()))
        if len(trouves) >= 2:
            fautifs[nom] = sorted(trouves)
    assert not fautifs, (
        f"docstrings publiques encore en français : {fautifs}")


@pytest.mark.parametrize("nom", [n for n, _ in _publiques()])
def test_the_public_api_uses_numpy_sections(nom):
    """Sans sections, un générateur de documentation rend un pavé, et un
    lecteur cherche le sens de `sampling_period` dans un paragraphe."""
    doc = getattr(stase, nom).__doc__ or ""
    assert doc.strip(), f"{nom} n'a aucune docstring"
    assert SECTION.search(doc), (
        f"{nom} : docstring sans section NumPy `Parameters` ou `Returns`")


def test_every_exported_name_is_covered():
    """La garde doit suivre le paquet, pas une liste écrite ici."""
    assert stase.__all__, "__all__ vide : les deux gardes ne testent rien"
    for nom in stase.__all__:
        assert hasattr(stase, nom), f"__all__ annonce {nom}, absent du paquet"
