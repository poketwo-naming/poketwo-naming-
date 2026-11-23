#!/usr/bin/env python3
"""Build nearest-neighbour refinement embeddings for commonly confused Pokémon.

When the main classifier predicts one of these classes, the bot re-checks the
image against every stored example of all of them.
"""

import argparse
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokemon_recognition import (  # noqa: E402
    FOCUSED_CROP_CLASSES,
    PokemonImageRecognizer,
    preprocess,
    preprocess_focused,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_CLASSES = [
    "Alolan Geodude",
    "Alolan Meowth",
    "Alolan Rattata",
    "Autumn Deerling",
    "Blipbug",
    "Brionne",
    "Cofagrigus",
    "Deerling",
    "Geodude",
    "Jellicent",
    "Luxray",
    "Malamar",
    "Munkidori",
    "Nidoran",
    "Nidoran♂",
    "Noivern",
    "Oinkologne",
    "Pikipek",
    "Rattata",
    "Sableye",
    "Summer Deerling",
    "Trevenant",
    "Winter Deerling",
    "Zygarde",
    *FOCUSED_CROP_CLASSES,
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="pokemon_images/training_data")
    parser.add_argument("--output", default="pokemon_image_refinements.npz")
    parser.add_argument("classes", nargs="*", default=DEFAULT_CLASSES)
    args = parser.parse_args()

    recognizer = PokemonImageRecognizer()
    class_ids = {str(name): i for i, name in enumerate(recognizer.classes)}
    embeddings, labels = [], []
    focused_embeddings, focused_labels = [], []
    for name in args.classes:
        folder = Path(args.source) / name
        paths = sorted(
            p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES
        )
        for path in paths:
            with Image.open(path) as image:
                tensor = np.expand_dims(preprocess(image), axis=0)
            embedding = np.asarray(
                recognizer.session.run(None, {recognizer.input_name: tensor})[0]
            )[0]
            embedding = embedding / max(float(np.linalg.norm(embedding)), 1e-8)
            embeddings.append(embedding.astype(np.float16))
            labels.append(class_ids[name])
            if name in FOCUSED_CROP_CLASSES:
                focused_tensor = np.expand_dims(preprocess_focused(image), axis=0)
                focused_embedding = np.asarray(
                    recognizer.session.run(
                        None,
                        {recognizer.input_name: focused_tensor},
                    )[0]
                )[0]
                focused_embedding /= max(
                    float(np.linalg.norm(focused_embedding)),
                    1e-8,
                )
                focused_embeddings.append(focused_embedding.astype(np.float32))
                focused_labels.append(class_ids[name])
        print(f"{name}: {len(paths)} images")

    focused_class_ids = np.asarray(
        [class_ids[name] for name in FOCUSED_CROP_CLASSES if name in args.classes],
        dtype=np.int64,
    )
    if len(focused_class_ids) < 2:
        focused_class_ids = np.empty(0, dtype=np.int64)
    if len(focused_class_ids) >= 2 and focused_embeddings:
        focused_embeddings_array = np.stack(focused_embeddings)
        focused_labels_array = np.asarray(focused_labels, dtype=np.int64)
        focused_centroids = np.stack(
            [
                focused_embeddings_array[focused_labels_array == class_id].mean(axis=0)
                for class_id in focused_class_ids
            ]
        )
        focused_centroids /= np.maximum(
            np.linalg.norm(focused_centroids, axis=1, keepdims=True),
            1e-8,
        )
    else:
        focused_centroids = np.empty((0, recognizer.centroids.shape[1]), dtype=np.float32)

    np.savez_compressed(
        args.output,
        embeddings=np.stack(embeddings),
        labels=np.asarray(labels),
        classes=recognizer.classes,
        focused_centroids=focused_centroids,
        focused_class_ids=focused_class_ids,
    )


if __name__ == "__main__":
    main()
