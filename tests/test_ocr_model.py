import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from mogi_tracker import ocr


def test_missing_model_gives_a_readable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="README"):
        ocr.Reader(str(tmp_path))


def test_crops_are_read_in_parallel_but_answered_in_order():
    class Model:
        def run(self, _, inputs):
            n = round(float(inputs["x"][0, 0, 0, 0]))
            time.sleep((8 - n) * 0.01)                      # the first one takes the longest
            probs = np.zeros((1, 4, 9), np.float32)
            probs[0, :, [0]] = 0.5
            probs[0, 1:3, n] = 0.8                          # the same letter twice in a row is one letter
            return [probs]
    reader = ocr.Reader.__new__(ocr.Reader)
    reader.session, reader.input_name, reader.classes = Model(), "x", ["", *"abcdefgh"]
    reader.pool = ThreadPoolExecutor(4)
    reader._prepare = lambda crop: np.full((3, 48, 320), crop, np.float32)
    out = reader.recognise([1, 2, 3, 4, 5, 6, 7, 8])
    assert [t for t, _ in out] == list("abcdefgh")
    assert all(abs(conf - 0.8) < 1e-6 for _, conf in out)
    assert reader.recognise([]) == []
