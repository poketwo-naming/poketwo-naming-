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
REFINEMENT_MATCH_THRESHOLD = 0.96
PALAFIN_MARK_PIXEL_THRESHOLD = 46
SILVALLY_COLOR_PIXEL_THRESHOLD = 100
FOCUSED_CROP_CLASSES = (
    "Finizen",
    "Palafin",
    "Hero Palafin",
    "Squawkabilly",
    "Blue Plumage Squawkabilly",
    "White Plumage Squawkabilly",
    "Yellow Plumage Squawkabilly",
)


def _preprocess_rgb(image: Image.Image) -> np.ndarray:
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


def preprocess(image: Image.Image) -> np.ndarray:
    """Match the MobileNet preprocessing used while training."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    return _preprocess_rgb(image)


def _preprocess_focused_rgb(image: Image.Image) -> np.ndarray:
    crop_side = max(1, round(min(image.size) * 0.7))
    left = (image.width - crop_side) // 2
    top = (image.height - crop_side) // 2
    focused = image.crop((left, top, left + crop_side, top + crop_side))
    return _preprocess_rgb(focused)


def _has_palafin_mark(image: Image.Image) -> bool:
    scale = RESIZE_SIZE / min(image.size)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.BILINEAR,
    )
    left = (resized.width - IMAGE_SIZE) // 2
    top = (resized.height - IMAGE_SIZE) // 2
    pixels = np.asarray(
        resized.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE)),
        dtype=np.int16,
    )
    red, green, blue = pixels.transpose(2, 0, 1)
    mark_pixels = (red > green + 15) & (blue > green + 10) & (red > 80)
    return int(np.count_nonzero(mark_pixels)) >= PALAFIN_MARK_PIXEL_THRESHOLD


def _silvally_color_form(image: Image.Image) -> str | None:
    pixels = np.asarray(
        ImageOps.fit(image, (IMAGE_SIZE, IMAGE_SIZE), method=Image.Resampling.BILINEAR),
        dtype=np.int16,
    )[30:194, 35:189]
    red, green, blue = pixels.transpose(2, 0, 1)
    colored = (red > 70) & (blue > 60) & (red > green + 25) & (blue > green + 20)
    pink = int(np.count_nonzero(colored & (red > blue + 15)))
    purple = int(np.count_nonzero(colored & (blue > red + 15)))
    if pink >= SILVALLY_COLOR_PIXEL_THRESHOLD and pink > 3 * purple:
        return "Psychic Silvally"
    if purple >= SILVALLY_COLOR_PIXEL_THRESHOLD and purple > 3 * pink:
        return "Poison Silvally"
    return None


def preprocess_focused(image: Image.Image) -> np.ndarray:
    """Zoom the centered Pokémon for fine-grained lookalike recognition."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    return _preprocess_focused_rgb(image)


class PokemonImageRecognizer:
    """Classify Pokémon images with transfer-learned class centroids."""

    def __init__(
        self,
        model_path: str | Path = "pokemon_image_model.npz",
        encoder_path: str | Path = "pokemon_image_encoder.onnx",
        refinement_path: str | Path = "pokemon_image_refinements.npz",
    ):
        self.model_path = Path(model_path)
        self.encoder_path = Path(encoder_path)
        # A small encoder is faster without a large per-session CPU thread pool.
        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(self.encoder_path),
            sess_options=session_options,
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
        with np.load(refinement_path, allow_pickle=False) as refinements:
            self.refinement_embeddings = refinements["embeddings"].astype(
                np.float32
            )
            self.refinement_labels = refinements["labels"]
            self.refinement_classes = refinements["classes"]
            self.focused_centroids = (
                refinements["focused_centroids"].astype(np.float32)
                if "focused_centroids" in refinements.files
                else np.empty((0, self.centroids.shape[1]), dtype=np.float32)
            )
            self.focused_class_ids = (
                refinements["focused_class_ids"].astype(np.int64)
                if "focused_class_ids" in refinements.files
                else np.empty(0, dtype=np.int64)
            )
        self.refinement_class_ids = {
            int(label) for label in np.unique(self.refinement_labels)
        }
        self.focused_class_id_set = set(self.focused_class_ids.tolist())

    def recognize(self, image: Image.Image) -> tuple[str, float, float]:
        """Return the Pokémon class, calibrated confidence, and elapsed seconds."""
        started = perf_counter()
        image = ImageOps.exif_transpose(image).convert("RGB")
        input_tensor = np.expand_dims(_preprocess_rgb(image), axis=0)
        outputs = self.session.run(None, {self.input_name: input_tensor})
        embedding = np.asarray(outputs[0])[0]
        embedding = embedding / max(float(np.linalg.norm(embedding)), 1e-8)
        scores = np.einsum("ij,j->i", self.centroids, embedding)
        top_two = np.argpartition(scores, -2)[-2:]
        second_best, best = top_two[np.argsort(scores[top_two])]
        predicted_name = str(self.classes[best])
        if int(best) in self.focused_class_id_set:
            focused_tensor = np.expand_dims(_preprocess_focused_rgb(image), axis=0)
            focused_outputs = self.session.run(
                None,
                {self.input_name: focused_tensor},
            )
            focused_embedding = np.asarray(focused_outputs[0])[0]
            focused_embedding /= max(float(np.linalg.norm(focused_embedding)), 1e-8)
            focused_scores = self.focused_centroids @ focused_embedding
            focused_order = np.argsort(focused_scores)[::-1]
            focused_best = int(focused_order[0])
            predicted_name = str(self.classes[self.focused_class_ids[focused_best]])
            margin = float(
                focused_scores[focused_order[0]] - focused_scores[focused_order[1]]
            )
        elif len(self.refinement_labels):
            refinement_scores = np.einsum(
                "ij,j->i", self.refinement_embeddings, embedding
            )
            if (
                best in self.refinement_class_ids
                or float(np.max(refinement_scores)) >= REFINEMENT_MATCH_THRESHOLD
            ):
                sorted_indexes = np.argsort(refinement_scores)[::-1]
                refined_label = int(self.refinement_labels[sorted_indexes[0]])
                predicted_name = str(self.classes[refined_label])
                other_label_score = next(
                    float(refinement_scores[index])
                    for index in sorted_indexes
                    if self.refinement_labels[index] != refined_label
                )
                margin = float(
                    refinement_scores[sorted_indexes[0]] - other_label_score
                )
            else:
                margin = float(scores[best] - scores[second_best])
        else:
            margin = float(scores[best] - scores[second_best])
        color_override = False
        if predicted_name in ("Psychic Silvally", "Poison Silvally"):
            color_form = _silvally_color_form(image)
            if color_form is not None and color_form != predicted_name:
                predicted_name = color_form
                color_override = True
        if predicted_name in ("Finizen", "Palafin"):
            mark_name = "Palafin" if _has_palafin_mark(image) else "Finizen"
            if mark_name != predicted_name:
                predicted_name = mark_name
                margin = -margin
        logit = self.calibration_coefficient * margin + self.calibration_intercept
        confidence = float(100 / (1 + np.exp(-np.clip(logit, -30, 30))))
        if color_override:
            confidence = min(confidence, 50.0)
        return predicted_name, confidence, perf_counter() - started
