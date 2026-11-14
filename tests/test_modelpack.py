import os

import pytest

from mogi_tracker import modelpack


def test_pack_round_trip_and_hides_the_model():
    model = os.urandom(5000) + b"onnx graph and weights" * 50
    packed = modelpack.pack(model)
    assert packed.startswith(modelpack.MAGIC)
    assert b"onnx graph and weights" not in packed
    assert modelpack.unpack(packed) == model


def test_unpack_refuses_other_files():
    with pytest.raises(ValueError):
        modelpack.unpack(b"\x08\x07not a packed model")
