"""The OCR model is obfuscated by having the exe unpack its files into a temporary folder. The packed file is the model XOR-ed with a fixed keystream and
is turned back into a model in memory. It's still gonna be nicked by someone determined, but I hope the license encourages enough people to just ask me for it instead.
"""
import hashlib

import numpy as np

MAGIC = b"MKWMOGI1"
_SALT = b"mkworld-mogi-tracker/recognizer/v1"


def _keystream(n: int) -> np.ndarray:
    return np.frombuffer(hashlib.shake_256(_SALT).digest(n), np.uint8)


def pack(model: bytes) -> bytes:
    data = np.frombuffer(model, np.uint8)
    return MAGIC + (data ^ _keystream(len(data))).tobytes()


def unpack(blob: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not a packed model")
    data = np.frombuffer(blob, np.uint8, offset=len(MAGIC))
    return (data ^ _keystream(len(data))).tobytes()
