"""Pokémon spawn image recognition using a compact ONNX encoder."""

from pathlib import Path
from time import perf_counter

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps


IMAGE_SIZE = 224
RESIZE_SIZE = 232
MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None]
STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None]


def preprocess(image: Image.Image) -> np.ndarray:
    """Match the MobileNet preprocessing used while training."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = RESIZE_SIZE / min(image.size)
    resized_size = (
        round(image.width * scale),
        round(image.height * scale),
    )
    image = image.resize(resized_size, Image.Resampling.BILINEAR)
    left = (image.width - IMAGE_SIZE) // 2
    top = (image.height - IMAGE_SIZE) // 2
    image = image.crop(
        (left, top, left + IMAGE_SIZE, top + IMAGE_SIZE)
    )
    pixels = np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255
    return ((pixels - MEAN) / STD).astype(np.float32)


class PokemonImageRecognizer:
    """Classify Pokémon images with transfer-learned class centroids."""

    def __init__(
        self,
        model_path: str | Path = "pokemon_image_model.npz",
        encoder_path: str | Path = "pokemon_image_encoder.onnx",
    ):
        self.model_path = Path(model_path)
        self.encoder_path = Path(encoder_path)
        self.session = ort.InferenceSession(
            str(self.encoder_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name

        with np.load(self.model_path, allow_pickle=False) as model:
            self.centroids = model["centroids"]
            self.classes = model["classes"]
            self.calibration_coefficient = float(model["calibration_coefficient"])
            self.calibration_intercept = float(model["calibration_intercept"])
            self.training_samples = int(model["training_samples"])
            self.validation_accuracy = float(model["validation_accuracy"])

    def recognize(self, image: Image.Image) -> tuple[str, float, float]:
        """Return the Pokémon class, calibrated confidence, and elapsed seconds."""
        started = perf_counter()
        input_tensor = np.expand_dims(preprocess(image), axis=0)
        outputs = self.session.run(None, {self.input_name: input_tensor})
        embedding = np.asarray(outputs[0])[0]
        embedding = embedding / max(float(np.linalg.norm(embedding)), 1e-8)
        scores = self.centroids @ embedding
        top_two = np.argpartition(scores, -2)[-2:]
        second_best, best = top_two[np.argsort(scores[top_two])]
        margin = float(scores[best] - scores[second_best])
        logit = self.calibration_coefficient * margin + self.calibration_intercept
        confidence = float(100 / (1 + np.exp(-np.clip(logit, -30, 30))))
        return str(self.classes[best]), confidence, perf_counter() - started
