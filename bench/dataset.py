"""Build step of the bench image: the pictures the pipelines are measured on.

They come from Imagenette, a public subset of ImageNet with 10 easy classes.
The archive is read as a stream, so only the pictures that are kept touch the disk:
- 20 per class from the validation split become the evaluation set, 224x224;
- 6 per class from the training split calibrate the int8 models, and stay in the build;
- one sprite with a small copy of every evaluation picture, for the web page.
"""
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

from PIL import Image

URL = "https://s3.amazonaws.com/fast-ai-imageclas/imagenette2-320.tgz"
# folder name in the archive (a WordNet id) -> position among the 1000 classes of ImageNet
CLASSES = {
    "n01440764": 0,  # tench
    "n02102040": 217,  # English springer
    "n02979186": 482,  # cassette player
    "n03000684": 491,  # chain saw
    "n03028079": 497,  # church
    "n03394916": 566,  # French horn
    "n03417042": 569,  # garbage truck
    "n03425413": 571,  # gas pump
    "n03445777": 574,  # golf ball
    "n03888257": 701,  # parachute
}
PER_CLASS = {"val": 20, "train": 6}
SIZE = 224
TILE = 96
COLUMNS = 20


def crop(data: bytes) -> Image.Image:
    """The usual ImageNet framing: short side to 256, then the central 224x224."""
    image = Image.open(io.BytesIO(data)).convert("RGB")
    scale = 256 / min(image.size)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.BICUBIC)
    left, top = (image.width - SIZE) // 2, (image.height - SIZE) // 2
    return image.crop((left, top, left + SIZE, top + SIZE))


def read_archive() -> dict[str, dict[str, list[bytes]]]:
    """The first pictures of every class, by split, as they come in the archive."""
    taken = {split: {wnid: [] for wnid in CLASSES} for split in PER_CLASS}
    missing = sum(PER_CLASS.values()) * len(CLASSES)
    with urllib.request.urlopen(URL) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
        for member in archive:
            parts = member.name.split("/")
            if missing == 0:
                break
            if not member.isfile() or len(parts) != 4 or parts[1] not in taken or parts[2] not in CLASSES:
                continue
            bucket = taken[parts[1]][parts[2]]
            if len(bucket) < PER_CLASS[parts[1]]:
                bucket.append(archive.extractfile(member).read())
                missing -= 1
    if missing:
        sys.exit(f"the archive ended with {missing} pictures still missing")
    return taken


def main(out: Path, calibration: Path) -> None:
    taken = read_archive()
    (out / "data" / "images").mkdir(parents=True)
    (out / "public").mkdir(parents=True)
    calibration.mkdir(parents=True)

    # one class after the other in turn, so that any stretch of the set holds all of them
    labels = []
    rows = -(-PER_CLASS["val"] * len(CLASSES) // COLUMNS)
    sprite = Image.new("RGB", (COLUMNS * TILE, rows * TILE))
    for round_ in range(PER_CLASS["val"]):
        for wnid, label in CLASSES.items():
            image = crop(taken["val"][wnid][round_])
            image.save(out / "data" / "images" / f"{len(labels):03d}.jpg", quality=95)
            small = image.resize((TILE, TILE), Image.Resampling.LANCZOS)
            sprite.paste(small, (len(labels) % COLUMNS * TILE, len(labels) // COLUMNS * TILE))
            labels.append(label)
    (out / "data" / "labels.json").write_text(json.dumps(labels))
    sprite.save(out / "public" / "sprite.jpg", quality=86, optimize=True)
    (out / "public" / "samples.json").write_text(json.dumps({"tile": TILE, "columns": COLUMNS, "labels": labels}))

    number = 0
    for wnid in CLASSES:
        for data in taken["train"][wnid]:
            crop(data).save(calibration / f"{number:03d}.jpg", quality=95)
            number += 1
    print(f"{len(labels)} evaluation pictures, {number} calibration pictures")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
