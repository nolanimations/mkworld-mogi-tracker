import pytest

from mogi_tracker import ocr


def test_missing_model_gives_a_readable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="README"):
        ocr.Reader(str(tmp_path))
