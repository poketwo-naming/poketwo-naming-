#!/usr/bin/env python3
"""Train the compact transfer-learned Pokémon spawn classifier."""

import argparse
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sklearn.linear_model import LogisticRegression
from torchvision.models import MobileNet_V2_Weights, mobilenet_v2


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def extract_embeddings(
    source: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    paths = sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_SUFFIXES
        and path.name != "env_reps.png"
    )
    classes = np.asarray(sorted({path.parent.name for path in paths}))
    class_indexes = {name: index for index, name in enumerate(classes)}
    labels = np.asarray([class_indexes[path.parent.name] for path in paths])
    weights = MobileNet_V2_Weights.DEFAULT
    model = mobilenet_v2(weights=weights)
    model.classifier = torch.nn.Sequential(torch.nn.Identity())
    model.eval()
    transform = weights.transforms()
    batches = []

    with torch.inference_mode():
        for start in range(0, len(paths), 128):
            images = []
            for path in paths[start : start + 128]:
                with Image.open(path) as image:
                    images.append(transform(image.convert("RGB")))
            batches.append(model(torch.stack(images)).numpy())
            completed = min(start + 128, len(paths))
            print(f"Embedded {completed}/{len(paths)} images", flush=True)

    embeddings = np.concatenate(batches)
    return embeddings.astype(np.float32), labels, classes


def class_centroids(
    embeddings: np.ndarray,
    labels: np.ndarray,
    class_count: int,
) -> np.ndarray:
    centroids = np.zeros((class_count, embeddings.shape[1]), dtype=np.float32)
    np.add.at(centroids, labels, embeddings)
    counts = np.bincount(labels, minlength=class_count)
    centroids /= np.maximum(counts[:, None], 1)
    centroids /= np.maximum(
        np.linalg.norm(centroids, axis=1, keepdims=True),
        1e-8,
    )
    return centroids


def split_by_class(
    labels: np.ndarray,
    random_seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(random_seed)
    training_indexes = []
    validation_indexes = []

    for label in np.unique(labels):
        indexes = np.flatnonzero(labels == label)
        rng.shuffle(indexes)
        validation_count = max(1, round(len(indexes) * 0.2))
        validation_indexes.extend(indexes[:validation_count])
        training_indexes.extend(indexes[validation_count:])

    return np.asarray(training_indexes), np.asarray(validation_indexes)


def export_encoder(path: Path) -> None:
    model = mobilenet_v2(weights=MobileNet_V2_Weights.DEFAULT)
    model.classifier = torch.nn.Sequential(torch.nn.Identity())
    model.eval()
    torch.onnx.export(
        model,
        (torch.zeros(1, 3, 224, 224),),
        path,
        input_names=["image"],
        output_names=["embedding"],
        opset_version=18,
        dynamo=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=Path("pokemon_images/training_data"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("pokemon_image_model.npz"),
    )
    parser.add_argument(
        "--encoder-output",
        type=Path,
        default=Path("pokemon_image_encoder.onnx"),
    )
    parser.add_argument("--embeddings-cache", type=Path)
    parser.add_argument("--seed", type=int, default=3019)
    args = parser.parse_args()

    if args.embeddings_cache:
        with np.load(args.embeddings_cache, allow_pickle=False) as cache:
            embeddings = cache["X"]
            labels = cache["labels"]
            classes = cache["classes"]
    else:
        if not args.source.is_dir():
            parser.error(f"training data directory not found: {args.source}")
        embeddings, labels, classes = extract_embeddings(args.source)

    embeddings /= np.maximum(
        np.linalg.norm(embeddings, axis=1, keepdims=True),
        1e-8,
    )
    train_indexes, validation_indexes = split_by_class(labels, args.seed)
    validation_centroids = class_centroids(
        embeddings[train_indexes],
        labels[train_indexes],
        len(classes),
    )
    scores = embeddings[validation_indexes] @ validation_centroids.T
    predicted = np.argmax(scores, axis=1)
    correct = predicted == labels[validation_indexes]
    validation_accuracy = float(correct.mean())
    ranked_scores = np.partition(scores, -2, axis=1)[:, -2:]
    margins = ranked_scores[:, 1] - ranked_scores[:, 0]
    calibration = LogisticRegression().fit(margins[:, None], correct.astype(int))
    centroids = class_centroids(embeddings, labels, len(classes))

    export_encoder(args.encoder_output)
    np.savez_compressed(
        args.output,
        centroids=centroids,
        classes=classes,
        calibration_coefficient=calibration.coef_[0][0],
        calibration_intercept=calibration.intercept_[0],
        training_samples=len(embeddings),
        validation_accuracy=validation_accuracy,
    )
    print(
        f"Validation accuracy: {validation_accuracy:.2%} "
        f"({correct.sum()}/{len(validation_indexes)})"
    )
    print(
        f"Created {args.output} and {args.encoder_output} with "
        f"{len(classes)} Pokémon classes from {len(embeddings)} images."
    )


if __name__ == "__main__":
    main()
