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

from pokemon_recognition import PokemonImageRecognizer, preprocess  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_CLASSES = [
    "Alolan Meowth",
    "Alolan Rattata",
    "Blipbug",
    "Luxray",
    "Pikipek",
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
        print(f"{name}: {len(paths)} images")

    np.savez_compressed(
        args.output,
        embeddings=np.stack(embeddings),
        labels=np.asarray(labels),
        classes=recognizer.classes,
    )


if __name__ == "__main__":
    main()
