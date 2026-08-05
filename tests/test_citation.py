"""Les métadonnées de citation doivent annoncer la même version que le
paquet.

Un CITATION.cff qui traîne une version périmée fait citer un état qui
n'est pas celui qu'on a publié. C'est le seul endroit où un numéro doit
être recopié, donc le seul qui puisse se désaccorder : autant que ça
casse ici plutôt que dans une bibliographie.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _version(fichier, motif):
    m = re.search(motif, (ROOT / fichier).read_text(encoding="utf-8"), re.M)
    assert m, f"version introuvable dans {fichier}"
    return m.group(1)


def test_versions_de_citation_accordees():
    paquet = _version("pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    citation = _version("CITATION.cff", r'^version:\s*"([^"]+)"')
    codemeta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))

    assert citation == paquet, (
        f"CITATION.cff annonce {citation}, le paquet est en {paquet}"
    )
    init = _version("src/stase/__init__.py", r'^__version__ = "([^"]+)"')
    assert init == paquet, (
        f"stase.__version__ annonce {init}, le paquet est en {paquet}. "
        "Il annonçait 0.4.0 pour un paquet en 0.6.0 jusqu'au 2026-08-05, "
        "parce que ce test ne le regardait pas. Un consommateur qui publie "
        "la version du moteur publiait donc un faux numéro."
    )
    readme = _version("README.md", r'\(version (\d+\.\d+(?:\.\d+)?)\)')
    assert readme == paquet, (
        f"le modèle de citation du README annonce {readme}, le paquet est "
        f"en {paquet}. Il annonçait 0.5.0 pour un paquet en 0.6.1 jusqu'au "
        "2026-08-05."
    )
    assert codemeta["version"] == paquet, (
        f"codemeta.json annonce {codemeta['version']}, le paquet est en {paquet}"
    )
