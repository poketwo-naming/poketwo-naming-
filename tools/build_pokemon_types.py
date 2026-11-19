#!/usr/bin/env python3
"""Generate ordered type data for every trained Pokétwo Pokémon class."""

import csv
import json
from pathlib import Path
import unicodedata
import urllib.request


POKEAPI_CSV_BASE = (
    "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"
)
TRAINING_ROOT = Path("pokemon_images/training_data")
OUTPUT = Path("pokemon_types.json")
SPRITE_IDS_OUTPUT = Path("pokemon_sprite_ids.json")

CANONICAL_OVERRIDES = {
    "10% Zygarde": "zygarde-10",
    "Aegislash": "aegislash-shield",
    "Amped Toxtricity": "toxtricity-amped",
    "Attack Deoxys": "deoxys-attack",
    "Basculegion": "basculegion-male",
    "Basculin": "basculin-red-striped",
    "Blade Aegislash": "aegislash-blade",
    "Blue Plumage Squawkabilly": "squawkabilly-blue-plumage",
    "Blue-Striped Basculin": "basculin-blue-striped",
    "Complete Zygarde": "zygarde-complete",
    "Darmanitan": "darmanitan-standard",
    "Defense Deoxys": "deoxys-defense",
    "Deoxys": "deoxys-normal",
    "Droopy Tatsugiri": "tatsugiri-droopy",
    "Dusk Lycanroc": "lycanroc-dusk",
    "Eiscue": "eiscue-ice",
    "Enamorus": "enamorus-incarnate",
    "Family of Three Maushold": "maushold-family-of-three",
    "Frillish": "frillish-male",
    "Galarian Darmanitan": "darmanitan-galar-standard",
    "Galarian Zen Darmanitan": "darmanitan-galar-zen",
    "Giratina": "giratina-altered",
    "Gourgeist": "gourgeist-average",
    "Hangry Morpeko": "morpeko-hangry",
    "Hero Palafin": "palafin-hero",
    "Indeedee": "indeedee-male",
    "Jellicent": "jellicent-male",
    "Keldeo": "keldeo-ordinary",
    "Landorus": "landorus-incarnate",
    "Low Key Toxtricity": "toxtricity-low-key",
    "Lycanroc": "lycanroc-midday",
    "Maushold": "maushold-family-of-three",
    "Meloetta": "meloetta-aria",
    "Meowstic": "meowstic-male",
    "Midnight Lycanroc": "lycanroc-midnight",
    "Mimikyu": "mimikyu-disguised",
    "Minior": "minior-red-meteor",
    "Morpeko": "morpeko-full-belly",
    "Nidoran": "nidoran-f",
    "Nidoran♂": "nidoran-m",
    "Noice Face Eiscue": "eiscue-noice",
    "Oinkologne": "oinkologne-male",
    "Oricorio": "oricorio-baile",
    "Pa'u Oricorio": "oricorio-pau",
    "Palafin": "palafin-zero",
    "Pirouette Meloetta": "meloetta-pirouette",
    "Pom-pom Oricorio": "oricorio-pom-pom",
    "Pumpkaboo": "pumpkaboo-average",
    "Pyroar": "pyroar-male",
    "Rapid Strike Urshifu": "urshifu-rapid-strike",
    "Roaming Gimmighoul": "gimmighoul-roaming",
    "Sandy Wormadam": "wormadam-sandy",
    "School Wishiwashi": "wishiwashi-school",
    "Sensu Oricorio": "oricorio-sensu",
    "Shaymin": "shaymin-land",
    "Speed Deoxys": "deoxys-speed",
    "Squawkabilly": "squawkabilly-green-plumage",
    "Stretchy Tatsugiri": "tatsugiri-stretchy",
    "Tatsugiri": "tatsugiri-curly",
    "Thundurus": "thundurus-incarnate",
    "Tornadus": "tornadus-incarnate",
    "Trash Wormadam": "wormadam-trash",
    "Urshifu": "urshifu-single-strike",
    "White Plumage Squawkabilly": "squawkabilly-white-plumage",
    "White-Striped Basculin": "basculin-white-striped",
    "Wishiwashi": "wishiwashi-solo",
    "Wormadam": "wormadam-plant",
    "Yellow Plumage Squawkabilly": "squawkabilly-yellow-plumage",
    "Zen Darmanitan": "darmanitan-zen",
    "Zygarde": "zygarde-50",
    "Zygarde Cell": "zygarde-10",
    "Zygarde Core": "zygarde-10",
}
CANONICAL_OVERRIDES.update(
    {
        f"Unown {letter}": "unown"
        for letter in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        + ["Exclamation", "Question"]
    }
)

# Pokétwo event forms have no official PokéAPI entry.
CUSTOM_TYPES = {
    "Chef Dente": ["normal"],
    "MissingNo": ["normal"],
    "Mosslax": ["grass", "normal"],
    "Peakychu": ["electric"],
    "Rotom Drone": ["electric", "ghost"],
    "Rotom Phone": ["electric", "ghost"],
    "Rotom Pokédex": ["electric", "ghost"],
    "Smearguru": ["normal"],
}
CUSTOM_SPRITE_IDENTIFIERS = {
    "Chef Dente": "greedent",
    "Mosslax": "snorlax",
    "Peakychu": "pikachu",
    "Rotom Drone": "rotom",
    "Rotom Phone": "rotom",
    "Rotom Pokédex": "rotom",
    "Ride Cyclizar": "cyclizar",
    "Smearguru": "smeargle",
}

REGION_SUFFIXES = {
    "alolan": "alola",
    "galarian": "galar",
    "hisuian": "hisui",
    "paldean": "paldea",
}


def normalize(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if character.isalnum()
    )


def download_csv(name: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        f"{POKEAPI_CSV_BASE}/{name}",
        headers={"User-Agent": "poketwo-naming-bot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def canonical_types(pokemon_rows=None):
    if pokemon_rows is None:
        pokemon_rows = download_csv("pokemon.csv")
    pokemon = {
        int(row["id"]): row["identifier"]
        for row in pokemon_rows
    }
    type_names = {
        int(row["id"]): row["identifier"]
        for row in download_csv("types.csv")
    }
    slots = {}
    for row in download_csv("pokemon_types.csv"):
        slots.setdefault(int(row["pokemon_id"]), []).append(
            (int(row["slot"]), type_names[int(row["type_id"])])
        )
    return {
        identifier: [type_name for _, type_name in sorted(slots.get(pokemon_id, []))]
        for pokemon_id, identifier in pokemon.items()
        if slots.get(pokemon_id)
    }


def resolve_class_identifier(class_name, identifiers) -> str:
    """Resolve a trained Pokétwo class to a canonical PokéAPI identifier."""
    if class_name in CUSTOM_TYPES:
        raise ValueError(f"{class_name} is a custom class")
    by_normalized_name = {
        normalize(identifier): identifier
        for identifier in identifiers
    }
    identifier = CANONICAL_OVERRIDES.get(class_name)
    if identifier is None:
        words = class_name.split()
        candidates = [normalize(class_name)]
        if words and words[0].casefold() in REGION_SUFFIXES:
            base_name = " ".join(words[1:])
            candidates.insert(
                0,
                normalize(base_name + REGION_SUFFIXES[words[0].casefold()]),
            )
        identifier = next(
            (
                by_normalized_name[candidate]
                for candidate in candidates
                if candidate in by_normalized_name
            ),
            None,
        )
        if identifier is None:
            normalized = normalize(class_name)
            suffix_matches = [
                key for key in by_normalized_name if normalized.endswith(key)
            ]
            if suffix_matches:
                identifier = by_normalized_name[max(suffix_matches, key=len)]

    if not isinstance(identifier, str) or identifier not in identifiers:
        raise ValueError(f"Cannot resolve Pokémon class: {class_name}")
    return identifier


def build_type_map(types_by_identifier):
    classes = sorted(
        path.name for path in TRAINING_ROOT.iterdir() if path.is_dir()
    )
    result = {}
    for class_name in classes:
        if class_name in CUSTOM_TYPES:
            result[class_name] = CUSTOM_TYPES[class_name]
            continue
        identifier = resolve_class_identifier(
            class_name,
            set(types_by_identifier),
        )
        if identifier and identifier in types_by_identifier:
            result[class_name] = types_by_identifier[identifier]
    return result


def build_sprite_id_map(pokemon_rows):
    pokemon_ids = {
        row["identifier"]: int(row["id"])
        for row in pokemon_rows
    }
    identifiers = set(pokemon_ids)
    classes = sorted(
        path.name for path in TRAINING_ROOT.iterdir() if path.is_dir()
    )
    result = {}
    for class_name in classes:
        identifier = CUSTOM_SPRITE_IDENTIFIERS.get(class_name)
        if identifier is None:
            try:
                identifier = resolve_class_identifier(class_name, identifiers)
            except ValueError:
                continue
        if identifier in pokemon_ids:
            result[class_name] = pokemon_ids[identifier]
    return result


def main() -> None:
    if not TRAINING_ROOT.is_dir():
        raise FileNotFoundError(f"Training directory not found: {TRAINING_ROOT}")
    pokemon_rows = download_csv("pokemon.csv")
    type_map = build_type_map(canonical_types(pokemon_rows))
    sprite_id_map = build_sprite_id_map(pokemon_rows)
    with open(OUTPUT, "w", encoding="utf-8") as output:
        json.dump(type_map, output, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Created {OUTPUT} with {len(type_map)} Pokémon class mappings.")
    with open(SPRITE_IDS_OUTPUT, "w", encoding="utf-8") as output:
        json.dump(sprite_id_map, output, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Created {SPRITE_IDS_OUTPUT} with {len(sprite_id_map)} sprite mappings.")


if __name__ == "__main__":
    main()
