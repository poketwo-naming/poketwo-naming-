import unittest

import numpy as np

from tools.build_pokemon_model import split_by_class
from tools.build_pokemon_types import resolve_class_identifier


class PokemonModelTrainingTests(unittest.TestCase):
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
