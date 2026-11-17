#!/usr/bin/env python3
"""Generate the shortest Latin-script localized name for every Pokémon class."""

import json
from pathlib import Path
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.build_pokemon_types import (
    CUSTOM_TYPES,
    TRAINING_ROOT,
    download_csv,
    resolve_class_identifier,
)


OUTPUT = Path("pokemon_best_names.json")
CUSTOM_SPECIES = {
    "Chef Dente": "greedent",
    "MissingNo": "MissingNo",
    "Mosslax": "snorlax",
    "Peakychu": "pikachu",
    "Rotom Drone": "rotom",
    "Rotom Phone": "rotom",
    "Rotom Pokédex": "rotom",
    "Smearguru": "smeargle",
}


def is_latin_name(name: str) -> bool:
    letters = [character for character in name if character.isalpha()]
    return bool(letters) and all(
        "LATIN" in unicodedata.name(character, "")
        for character in letters
    )


def shortest_latin_name(names: list[str]) -> str:
    candidates = sorted(
        {name.strip() for name in names if is_latin_name(name.strip())},
        key=lambda name: (len(name), name.casefold(), name),
    )
    if not candidates:
        raise ValueError("Pokémon has no Latin-script localized names")
    return candidates[0]


def build_best_names() -> dict[str, str]:
    pokemon_rows = download_csv("pokemon.csv")
    identifier_to_species = {
        row["identifier"]: int(row["species_id"])
        for row in pokemon_rows
    }
    species_names = {}
    for row in download_csv("pokemon_species_names.csv"):
        species_names.setdefault(int(row["pokemon_species_id"]), []).append(
            row["name"]
        )

    best_by_species = {
        species_id: shortest_latin_name(names)
        for species_id, names in species_names.items()
    }
    identifiers = set(identifier_to_species)
    classes = sorted(
        path.name for path in TRAINING_ROOT.iterdir() if path.is_dir()
    )
    result = {}

    for class_name in classes:
        if class_name in CUSTOM_TYPES:
            species = CUSTOM_SPECIES.get(class_name)
            if species is None:
                raise ValueError(f"Missing custom species mapping: {class_name}")
            if class_name == "MissingNo":
                result[class_name] = species
                continue
            species_id = identifier_to_species[species]
        else:
            identifier = resolve_class_identifier(class_name, identifiers)
            species_id = identifier_to_species[identifier]
        result[class_name] = best_by_species[species_id]
    return result


def main() -> None:
    if not TRAINING_ROOT.is_dir():
        raise FileNotFoundError(f"Training directory not found: {TRAINING_ROOT}")
    names = build_best_names()
    with open(OUTPUT, "w", encoding="utf-8") as output:
        json.dump(names, output, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Created {OUTPUT} with {len(names)} Pokémon best names.")


if __name__ == "__main__":
    main()
