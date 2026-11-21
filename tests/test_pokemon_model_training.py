import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from tools.build_pokemon_model import split_by_class
from tools.build_pokemon_names import build_localized_data
from tools.build_pokemon_types import resolve_class_identifier


class PokemonModelTrainingTests(unittest.TestCase):
    def test_name_generation_preserves_woguru_alias(self):
        rows = {
            "pokemon.csv": [
                {"identifier": "braviary", "species_id": "628"},
                {"identifier": "braviary-hisui", "species_id": "628"},
            ],
            "pokemon_species_names.csv": [
                {"pokemon_species_id": "628", "local_language_id": "9", "name": "Braviary"},
            ],
        }
        root = SimpleNamespace(
            iterdir=lambda: [
                SimpleNamespace(name=name, is_dir=lambda: True)
                for name in ("Braviary", "Hisuian Braviary")
            ]
        )
        with (
            patch("tools.build_pokemon_names.TRAINING_ROOT", root),
            patch("tools.build_pokemon_names.download_csv", side_effect=rows.__getitem__),
        ):
            _, aliases, _ = build_localized_data()

        self.assertEqual(aliases["woguru"], "Braviary")

    def test_singleton_class_remains_in_training_data(self):
        labels = np.array([0, 0, 1])

        training, validation = split_by_class(labels, random_seed=3019)

        self.assertIn(1, labels[training])
        self.assertNotIn(1, labels[validation])

    def test_nidoran_and_palafin_forms_map_to_correct_species(self):
        identifiers = {"nidoran-f", "nidoran-m", "palafin-zero", "palafin-hero"}

        self.assertEqual(
            resolve_class_identifier("Nidoran♂", identifiers),
            "nidoran-m",
        )
        self.assertEqual(
            resolve_class_identifier("Palafin", identifiers),
            "palafin-zero",
        )

    def test_dudunsparce_forms_do_not_map_to_dunsparce(self):
        identifiers = {
            "dunsparce",
            "dudunsparce-two-segment",
            "dudunsparce-three-segment",
        }

        self.assertEqual(
            resolve_class_identifier("Dudunsparce", identifiers),
            "dudunsparce-two-segment",
        )
        self.assertEqual(
            resolve_class_identifier("Three-Segment Dudunsparce", identifiers),
            "dudunsparce-three-segment",
        )


if __name__ == "__main__":
    unittest.main()
