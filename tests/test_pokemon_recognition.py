import math
import unittest
from unittest.mock import Mock

import numpy as np
from PIL import Image

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

    def test_focused_prediction_and_confidence(self):
        self.recognizer.focused_class_id_set = {0}
        self.recognizer.focused_class_ids = np.array([1, 2])
        self.recognizer.focused_centroids = np.array(
            [[0.8, 0.0], [0.6, 0.0]], dtype=np.float32
        )
        self.assert_prediction("Second", 0.2)
        self.assertEqual(self.recognizer.session.run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
