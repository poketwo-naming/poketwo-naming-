import math
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from PIL import Image, ImageOps

from pokemon_recognition import PokemonImageRecognizer


class PokemonRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = PokemonImageRecognizer.__new__(PokemonImageRecognizer)
        self.recognizer.input_name = "image"
        self.recognizer.session = Mock()
        self.recognizer.session.run.return_value = [
            np.array([[1.0, 0.0]], dtype=np.float32)
        ]
        self.recognizer.classes = np.array(["First", "Second", "Third"])
        self.recognizer.centroids = np.array(
            [[0.9, 0.0], [0.8, 0.0], [0.3, 0.0]], dtype=np.float32
        )
        self.recognizer.refinement_class_ids = set()
        self.recognizer.refinement_labels = np.array([], dtype=np.int64)
        self.recognizer.focused_class_id_set = set()
        self.recognizer.calibration_coefficient = 2.0
        self.recognizer.calibration_intercept = -1.0
        self.image = Image.new("RGB", (224, 224))

    def assert_prediction(self, expected_name, margin):
        name, confidence, elapsed = self.recognizer.recognize(self.image)
        self.assertEqual(name, expected_name)
        self.assertAlmostEqual(confidence, 100 / (1 + math.exp(1 - 2 * margin)), places=5)
        self.assertGreaterEqual(elapsed, 0)

    def test_centroid_prediction_and_confidence(self):
        self.assert_prediction("First", 0.1)

    def test_refinement_prediction_and_confidence(self):
        self.recognizer.refinement_class_ids = {0}
        self.recognizer.refinement_embeddings = np.array(
            [[0.9, 0.0], [0.85, 0.0], [0.75, 0.0]], dtype=np.float32
        )
        self.recognizer.refinement_labels = np.array([1, 1, 2])
        self.assert_prediction("Second", 0.15)

    def test_close_reference_refines_an_unrelated_initial_class(self):
        self.recognizer.refinement_class_ids = {1, 2}
        self.recognizer.refinement_embeddings = np.array(
            [[0.98, 0.0], [0.8, 0.0]], dtype=np.float32
        )
        self.recognizer.refinement_labels = np.array([1, 2])
        self.assert_prediction("Second", 0.18)

    def test_distant_reference_does_not_override_initial_class(self):
        self.recognizer.refinement_class_ids = {1, 2}
        self.recognizer.refinement_embeddings = np.array(
            [[0.95, 0.0], [0.8, 0.0]], dtype=np.float32
        )
        self.recognizer.refinement_labels = np.array([1, 2])
        self.assert_prediction("First", 0.1)

    def test_focused_prediction_and_confidence(self):
        self.recognizer.focused_class_id_set = {0}
        self.recognizer.focused_class_ids = np.array([1, 2])
        self.recognizer.focused_centroids = np.array(
            [[0.8, 0.0], [0.6, 0.0]], dtype=np.float32
        )
        self.assert_prediction("Second", 0.2)
        self.assertEqual(self.recognizer.session.run.call_count, 2)

    def test_palafin_mark_overrides_finizen_prediction(self):
        self.recognizer.classes = np.array(["Finizen", "Palafin", "Third"])
        self.recognizer.focused_class_id_set = {0, 1}
        self.recognizer.focused_class_ids = np.array([0, 1])
        self.recognizer.focused_centroids = np.array(
            [[1.0, 0.0], [0.8, 0.0]], dtype=np.float32
        )
        image = Image.new("RGB", (224, 224))
        for x in range(100, 112):
            for y in range(100, 112):
                image.putpixel((x, y), (255, 0, 120))

        name, confidence, _ = self.recognizer.recognize(image)

        self.assertEqual(name, "Palafin")
        self.assertLess(confidence, 50)

    def test_missing_palafin_mark_overrides_palafin_prediction(self):
        self.recognizer.classes = np.array(["Finizen", "Palafin", "Third"])
        self.recognizer.focused_class_id_set = {0, 1}
        self.recognizer.focused_class_ids = np.array([0, 1])
        self.recognizer.focused_centroids = np.array(
            [[0.8, 0.0], [1.0, 0.0]], dtype=np.float32
        )

        name, confidence, _ = self.recognizer.recognize(self.image)

        self.assertEqual(name, "Finizen")
        self.assertLess(confidence, 50)

    def test_silvally_color_corrects_confused_forms(self):
        self.recognizer.classes = np.array(
            ["Poison Silvally", "Psychic Silvally", "Third"]
        )
        for color, initial, expected in (
            ((240, 40, 170), "Poison Silvally", "Psychic Silvally"),
            ((130, 40, 200), "Psychic Silvally", "Poison Silvally"),
        ):
            with self.subTest(expected=expected):
                self.recognizer.classes[:2] = [initial, expected]
                image = Image.new("RGB", (224, 224))
                for x in range(90, 110):
                    for y in range(90, 110):
                        image.putpixel((x, y), color)
                name, confidence, _ = self.recognizer.recognize(image)
                self.assertEqual(name, expected)
                self.assertLessEqual(confidence, 50)

    def test_silvally_ambiguous_color_keeps_model_prediction(self):
        self.recognizer.classes = np.array(
            ["Poison Silvally", "Psychic Silvally", "Third"]
        )
        self.assert_prediction("Poison Silvally", 0.1)

    def test_silvally_color_does_not_override_other_species(self):
        image = Image.new("RGB", (224, 224), (240, 40, 170))
        self.assertEqual(self.recognizer.recognize(image)[0], "First")


class SpawnImageRecognitionTests(unittest.TestCase):
    def test_deerling_seasonal_spawn_images(self):
        source = Path("pokemon_images/training_data")
        examples = (
            (source / "Deerling" / "1492074968702517368.jpg", "Deerling"),
            (source / "Summer Deerling" / "1515602630372626523.jpg", "Summer Deerling"),
            (source / "Autumn Deerling" / "1444837446721208340.jpg", "Autumn Deerling"),
            (source / "Winter Deerling" / "1445168416565624932.jpg", "Winter Deerling"),
        )
        if not all(path.exists() for path, _ in examples):
            self.skipTest("Deerling training images are not available")
        recognizer = PokemonImageRecognizer()
        for path, expected in examples:
            with self.subTest(path=path), Image.open(path) as image:
                self.assertEqual(recognizer.recognize(image)[0], expected)
                self.assertEqual(recognizer.recognize(ImageOps.mirror(image))[0], expected)

    def test_nidoran_gender_on_spawn_images(self):
        source = Path("pokemon_images/training_data")
        male = source / "Nidoran♂" / "1568160619629117440.jpg"
        if not male.exists():
            male = source / "Nidoran" / male.name
        examples = (
            (male, "Nidoran♂"),
            (source / "Nidoran" / "1524241235340951724.jpg", "Nidoran"),
        )
        if not all(path.exists() for path, _ in examples):
            self.skipTest("Nidoran training images are not available")
        recognizer = PokemonImageRecognizer()
        for path, expected in examples:
            with self.subTest(path=path), Image.open(path) as image:
                self.assertEqual(recognizer.recognize(image)[0], expected)
                self.assertEqual(recognizer.recognize(ImageOps.mirror(image))[0], expected)

    def test_cofagrigus_spawn_image(self):
        path = Path("pokemon_images/training_data/Cofagrigus/image.png")
        if not path.exists():
            self.skipTest("Cofagrigus training image is not available")
        with Image.open(path) as image:
            recognizer = PokemonImageRecognizer()
            self.assertEqual(recognizer.recognize(image)[0], "Cofagrigus")
            self.assertEqual(
                recognizer.recognize(image.resize((384, 240)))[0], "Cofagrigus"
            )

    def test_geodude_spawn_images(self):
        source = Path("pokemon_images/training_data")
        examples = (
            (source / "Geodude" / "image.png", "Geodude"),
            (source / "Alolan Geodude" / "1495047848734232667.jpg", "Alolan Geodude"),
        )
        if not all(path.exists() for path, _ in examples):
            self.skipTest("Geodude training images are not available")
        recognizer = PokemonImageRecognizer()
        for path, expected in examples:
            with self.subTest(path=path), Image.open(path) as image:
                self.assertEqual(recognizer.recognize(image)[0], expected)
                self.assertEqual(
                    recognizer.recognize(image.resize((384, 240)))[0], expected
                )

    def test_rattata_spawn_images(self):
        source = Path("pokemon_images/training_data")
        examples = (
            (source / "Rattata" / "image.png", "Rattata"),
            (source / "Alolan Rattata" / "1498361641966895127.jpg", "Alolan Rattata"),
        )
        if not all(path.exists() for path, _ in examples):
            self.skipTest("Rattata training images are not available")
        recognizer = PokemonImageRecognizer()
        for path, expected in examples:
            with self.subTest(path=path), Image.open(path) as image:
                self.assertEqual(recognizer.recognize(image)[0], expected)
                self.assertEqual(
                    recognizer.recognize(image.resize((384, 240)))[0], expected
                )
                self.assertEqual(recognizer.recognize(ImageOps.mirror(image))[0], expected)

    def test_reported_rattata_spawn_image(self):
        path = Path("pokemon_images/training_data/Rattata/image copy.png")
        if not path.exists():
            self.skipTest("Reported Rattata spawn image is not available")
        recognizer = PokemonImageRecognizer()
        with Image.open(path) as image:
            for variant in (image, image.resize((384, 240)), ImageOps.mirror(image)):
                self.assertEqual(recognizer.recognize(variant)[0], "Rattata")

    def test_psychic_and_poison_silvally_spawn_images(self):
        source = Path("pokemon_images/training_data")
        examples = (
            (source / "Psychic Silvally" / "1526794714702151751.jpg", "Psychic Silvally"),
            (source / "Poison Silvally" / "1507166422860562583.jpg", "Poison Silvally"),
        )
        if not all(path.exists() for path, _ in examples):
            self.skipTest("Silvally training images are not available")
        recognizer = PokemonImageRecognizer()
        for path, expected in examples:
            with self.subTest(path=path), Image.open(path) as image:
                for variant in (image, image.resize((384, 240)), ImageOps.mirror(image)):
                    self.assertEqual(recognizer.recognize(variant)[0], expected)


if __name__ == "__main__":
    unittest.main()
