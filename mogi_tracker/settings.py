import json
import threading

from . import paths, teams

DEFAULTS = {
    "lobby": 24,
    "format": "4v4",
    "source": "monitor",
    "monitor": 1,                # 1 = primary
    "hotkey": "down",
    "my_tag": "",
    "mark_my_tag": True,
    "auto_copy": False,
    "auto_capture": False,
    "overlay_layout": "bar",
    "background": "dark",
    "player_points": True,       # each player's points next to their name in the team rows
    "port": 12424,
    "scoring": "places",         # "classic": the old DC logic (session_classic.py), only set by hand in settings.json
}
OPTIONS = {
    "lobby": teams.LOBBY_SIZES,
    "source": ("monitor", "obs"),
    "overlay_layout": ("bar", "list"),
    "background": ("dark", "blue", "light"),
    "scoring": ("places", "classic"),
}

_lock = threading.Lock()


def _path():
    return paths.data_dir() / "settings.json"


def _clean(raw: dict) -> dict:
    out = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        if type(value) is not type(default):
            continue
        if key in OPTIONS and value not in OPTIONS[key]:
            continue
        out[key] = value
    if out["format"] not in teams.formats_for(out["lobby"]):
        out["format"] = DEFAULTS["format"]
    if not 1024 <= out["port"] <= 65535:
        out["port"] = DEFAULTS["port"]
    out["monitor"] = max(1, out["monitor"])
    out["my_tag"] = out["my_tag"].strip()[:16]
    return out


def load() -> dict:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    return _clean(raw)


def save(settings: dict) -> dict:
    cleaned = _clean(settings)
    with _lock:
        tmp = _path().with_suffix(".tmp")
        tmp.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_path())
    return cleaned
