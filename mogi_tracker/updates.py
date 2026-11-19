"""Checks the GitHub releases for a newer version, and lets the exe replace itself"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import APP_NAME, __version__

log = logging.getLogger(__name__)

REPO = "nolanimations/mkworld-mogi-tracker"
ASSET = "MKWorldMogiTracker.exe"
RELEASES = f"https://github.com/{REPO}/releases"
_HEADERS = {"User-Agent": APP_NAME.replace(" ", ""), "Accept": "application/vnd.github+json"}


def from_repo(url) -> bool:
    return isinstance(url, str) and url.lower().startswith(RELEASES.lower() + "/")


def parse_version(text):
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", (text or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def latest():
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    if not getattr(sys, "frozen", False):
        url = os.environ.get("MKW_TRACKER_RELEASES") or url     # dev: test the check from source only
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            release = json.load(r)
    except Exception as e:
        log.info("update check: %s", e)
        return None
    new = parse_version(release.get("tag_name"))
    if not new or new <= parse_version(__version__):
        return None
    asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET), None) or {}
    page, download = release.get("html_url"), asset.get("browser_download_url")
    return {"version": ".".join(map(str, new)), "page": page if from_repo(page) else RELEASES,
            "download": download if from_repo(download) else None, "size": asset.get("size")}


def can_install(update) -> bool:
    return bool(getattr(sys, "frozen", False) and update and update.get("download"))


def _old(exe):
    return exe.with_name(exe.name + ".old")


def install(update) -> Path:
    if not from_repo(update.get("download")):
        raise OSError("the download is not from the tracker's GitHub releases")
    exe = Path(sys.executable)
    new = exe.with_name(exe.name + ".new")
    req = urllib.request.Request(update["download"], headers={"User-Agent": _HEADERS["User-Agent"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(new, "wb") as f:
            if not r.geturl().startswith("https://"):      # GitHub redirects to its file storage, over https only
                raise OSError("the download was redirected away from https")
            shutil.copyfileobj(r, f, 1 << 20)
        if update.get("size") and new.stat().st_size != update["size"]:
            raise OSError("the download was incomplete")
        _old(exe).unlink(missing_ok=True)
        exe.rename(_old(exe))
    except BaseException:
        new.unlink(missing_ok=True)
        raise
    try:
        new.rename(exe)
    except OSError:
        _old(exe).rename(exe)
        new.unlink(missing_ok=True)
        raise
    return exe


def start(exe):
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    args = [a for a in sys.argv[1:] if a != "--after-update"]
    subprocess.Popen([str(exe), *args, "--after-update"], env=env, close_fds=True)


def clean_up(wait=0):
    if not getattr(sys, "frozen", False):
        return
    deadline = time.monotonic() + wait
    while True:
        try:
            _old(Path(sys.executable)).unlink(missing_ok=True)
            return
        except OSError:
            if time.monotonic() >= deadline:
                return      # next time then
            time.sleep(0.3)
