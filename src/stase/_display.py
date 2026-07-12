# Copyright 2021-2026 Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the stase Python package (Python port of the
# EXstat R package).
#
# stase is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.
#
# stase is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.

"""Affichage verbose partagé par process_extraction et process_trend."""


def _verbose_box(title: str, rows: list, width: int = 66) -> None:
    inner = width - 2
    bar = "─" * max(0, inner - len(title) - 3)
    print(f"┌─ {title} {bar}┐")
    for r in rows:
        print("│  " + r.ljust(inner - 2) + "│")
    print("└" + "─" * inner + "┘")
