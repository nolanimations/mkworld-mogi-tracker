import os
import sys
from pathlib import Path

from . import APP_NAME


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))


def resource(*parts) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "mogi_tracker"
    return str(base.joinpath(*parts))


def data_dir() -> Path:
    override = os.environ.get("MKW_TRACKER_DATA_DIR")
    base = Path(override) if override else Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def last_capture_dir() -> Path:
    return data_dir() / "last_capture"
