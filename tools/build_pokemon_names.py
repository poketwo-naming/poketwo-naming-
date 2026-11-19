#!/usr/bin/env python3
"""Generate shortest localized names and aliases for every Pokémon class."""

import json
from pathlib import Path
import re
import sys

from unidecode import unidecode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.build_pokemon_types import (
    CUSTOM_TYPES,
    TRAINING_ROOT,
    download_csv,
    normalize,
    resolve_class_identifier,
)


BEST_NAMES_OUTPUT = Path("pokemon_best_names.json")
ALIASES_OUTPUT = Path("pokemon_aliases.json")
SPECIES_OUTPUT = Path("pokemon_species.json")
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
CATCH_NAME_OVERRIDES = {
    "Eevee": "ibui",
}
OFFICIAL_CATCH_LANGUAGE_IDS = {2, 5, 6, 7, 8, 9, 14}


def romanized_name(name: str) -> str:
    romanized = re.sub(r"[^A-Za-z0-9]+", "", unidecode(name))
    return romanized or name


def shortest_name(names: list[str]) -> str:
    candidates = set()
    for name in names:
        cleaned = name.strip()
        if not cleaned:
            continue
        candidates.add(cleaned)
    return min(candidates, key=lambda name: (len(name), name.casefold(), name))


def build_localized_data() -> tuple[
    dict[str, str], dict[str, str], dict[str, int | str]
]:
    pokemon_rows = download_csv("pokemon.csv")
    identifier_to_species = {
        row["identifier"]: int(row["species_id"])
        for row in pokemon_rows
    }
    localized_species = {}
    species_all_names = {}
    for row in download_csv("pokemon_species_names.csv"):
        species_id = int(row["pokemon_species_id"])
        species_all_names.setdefault(species_id, []).append(row["name"])
        if int(row["local_language_id"]) not in OFFICIAL_CATCH_LANGUAGE_IDS:
            continue
        localized_species.setdefault(
            species_id,
            [],
        ).append(row["name"])

    best_by_species = {
        species_id: shortest_name(names)
        for species_id, names in localized_species.items()
    }
    english_by_species = {
        int(row["pokemon_species_id"]): row["name"]
        for row in download_csv("pokemon_species_names.csv")
        if int(row["local_language_id"]) == 9
    }
    identifiers = set(identifier_to_species)
    classes = sorted(
        path.name for path in TRAINING_ROOT.iterdir() if path.is_dir()
    )
    best_names = {}
    aliases_to_classes = {}
    species_by_class = {}

    for class_name in classes:
        if class_name in CUSTOM_TYPES:
            species = CUSTOM_SPECIES.get(class_name)
            if species is None:
                raise ValueError(f"Missing custom species mapping: {class_name}")
            species_id = None if species == "MissingNo" else (
                identifier_to_species[species]
            )
            best_names[class_name] = (
                "MissingNo"
                if species_id is None
                else best_by_species[species_id]
            )
            names = [class_name]
        else:
            identifier = resolve_class_identifier(class_name, identifiers)
            species_id = identifier_to_species[identifier]
            names = species_all_names[species_id]
            best_names[class_name] = CATCH_NAME_OVERRIDES.get(
                class_name,
                (
                    english_by_species[species_id]
                    if species_id >= 906
                    else best_by_species[species_id]
                ),
            )

        species_by_class[class_name] = (
            species_id if species_id is not None else "MissingNo"
        )
        names = list(
            dict.fromkeys(
                [
                    class_name,
                    best_names[class_name],
                    *names,
                    *(romanized_name(name) for name in names),
                ]
            )
        )
        for name in names:
            aliases_to_classes.setdefault(normalize(str(name)), set()).add(class_name)

    aliases = {}
    for alias, class_names in aliases_to_classes.items():
        if not alias:
            continue
        shortest_length = min(len(class_name) for class_name in class_names)
        shortest_classes = sorted(
            class_name
            for class_name in class_names
            if len(class_name) == shortest_length
        )
        if len(shortest_classes) == 1:
            aliases[alias] = shortest_classes[0]
    return best_names, aliases, species_by_class


def main() -> None:
    if not TRAINING_ROOT.is_dir():
        raise FileNotFoundError(f"Training directory not found: {TRAINING_ROOT}")
    best_names, aliases, species_by_class = build_localized_data()
    with open(BEST_NAMES_OUTPUT, "w", encoding="utf-8") as output:
        json.dump(best_names, output, ensure_ascii=False, indent=2, sort_keys=True)
    with open(ALIASES_OUTPUT, "w", encoding="utf-8") as output:
        json.dump(aliases, output, ensure_ascii=False, indent=2, sort_keys=True)
    with open(SPECIES_OUTPUT, "w", encoding="utf-8") as output:
        json.dump(
            species_by_class, output, ensure_ascii=False, indent=2, sort_keys=True
        )
    print(
        f"Created {BEST_NAMES_OUTPUT} with {len(best_names)} names and "
        f"{ALIASES_OUTPUT} with {len(aliases)} localized aliases, and "
        f"{SPECIES_OUTPUT} with {len(species_by_class)} species mappings."
    )


if __name__ == "__main__":
    main()
