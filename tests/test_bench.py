"""The arithmetic of the benchmark, without the models: those need the bench image."""
import numpy as np
import pytest

import bench


def test_the_numbers_of_a_run():
    # four pictures in two seconds, three of them right; the model alone took 10, 20, 30 and 40 ms
    result = bench.summarize([0, 217, 482, 9], [0, 217, 482, 491], [0.01, 0.02, 0.03, 0.04], 2.0)

    assert result["fps"] == 2.0
    assert result["accuracy"] == 75.0
    assert result["latency_ms"] == 25.0
    assert result["images"] == 4
    assert result["predictions"] == [0, 217, 482, 9]


def test_a_picture_becomes_what_the_model_wants():
    image_module = pytest.importorskip("PIL.Image")
    grey = image_module.new("RGB", (224, 224), (128, 128, 128))

    pixels = bench.preprocess(grey, 160)

    assert pixels.shape == (1, 3, 160, 160) and pixels.dtype == np.float32
    # mid grey, minus the mean of ImageNet, over its deviation, channel by channel
    expected = (128 / 255 - bench.MEAN) / bench.STD
    assert np.allclose(pixels[0, :, 0, 0], expected, atol=1e-5)
