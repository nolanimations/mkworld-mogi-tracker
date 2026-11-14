"""Prepare the OCR model for a release build
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mogi_tracker import modelpack  # noqa: E402

MODEL = ROOT / "mogi_tracker" / "model" / "rec.onnx"
PACKED = ROOT / "mogi_tracker" / "model" / "rec.bin"
NOTICE = {
    "copyright": "Copyright (c) 2026 Nolanimations. All rights reserved.",
    "licence": "Part of MKWorld Mogi Tracker. Please don’t redistribute it without asking. Based on PaddleOCR PP-OCRv4 (Apache License 2.0). "
}


def main():
    import onnx
    import onnxruntime as ort

    if not MODEL.is_file():
        raise SystemExit(f"{MODEL} is missing: the OCR model is not part of the source code (see README).")
    model = onnx.load(str(MODEL))
    del model.metadata_props[:]
    for key, value in NOTICE.items():
        model.metadata_props.add(key=key, value=value)
    stamped = model.SerializeToString()

    # the stamp is metadata only, the readings must not change
    x = np.random.default_rng(0).standard_normal((4, 3, 48, 320)).astype(np.float32)
    before = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    after = ort.InferenceSession(modelpack.unpack(modelpack.pack(stamped)), providers=["CPUExecutionProvider"])
    a = before.run(None, {before.get_inputs()[0].name: x})[0]
    b = after.run(None, {after.get_inputs()[0].name: x})[0]
    if not np.array_equal(a, b):
        raise SystemExit("the packed model gives different output; not writing it")

    PACKED.write_bytes(modelpack.pack(stamped))
    print(f"packed {MODEL.name} -> {PACKED.name} ({PACKED.stat().st_size / 1e6:.1f} MB), output identical")


if __name__ == "__main__":
    main()
