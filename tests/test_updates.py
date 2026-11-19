import io
import json
import sys
import urllib.error

import pytest

from mogi_tracker import updates


DL = "https://github.com/nolanimations/mkworld-mogi-tracker/releases/download/v9.9.9/MKWorldMogiTracker.exe"


class _Response(io.BytesIO):
    url = DL

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _release(monkeypatch, tag, assets=None):
    body = json.dumps({"tag_name": tag, "html_url": "https://github.com/Nolanimations/mkworld-mogi-tracker/releases/tag/v1.0.1",
                       "assets": assets if assets is not None else
                       [{"name": updates.ASSET, "browser_download_url": DL, "size": 3}]})
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout: _Response(body.encode()))


def test_versions():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("1.10") == (1, 10, 0)
    assert updates.parse_version("v1.10.0") > updates.parse_version("v1.9.9")
    assert updates.parse_version("beta") is None


def test_only_a_newer_release_counts(monkeypatch):
    monkeypatch.setattr(updates, "__version__", "1.0.0")
    _release(monkeypatch, "v1.0.0")
    assert updates.latest() is None
    _release(monkeypatch, "v0.9.0")
    assert updates.latest() is None
    _release(monkeypatch, "v1.0.1")
    up = updates.latest()
    assert up["version"] == "1.0.1" and up["download"] == DL


def test_a_release_without_the_exe_links_to_the_page(monkeypatch):
    monkeypatch.setattr(updates, "__version__", "1.0.0")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _release(monkeypatch, "v2.0.0", assets=[])
    up = updates.latest()
    assert up["page"] and not updates.can_install(up)


def test_no_release_yet_or_offline_is_quiet(monkeypatch):
    def fail(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    monkeypatch.setattr(updates.urllib.request, "urlopen", fail)
    assert updates.latest() is None


def test_install_swaps_the_exe(monkeypatch, tmp_path):
    exe = tmp_path / updates.ASSET
    exe.write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout: _Response(b"new"))
    assert updates.install({"download": DL, "size": 3}) == exe
    assert exe.read_bytes() == b"new"
    assert (tmp_path / (updates.ASSET + ".old")).read_bytes() == b"old"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    updates.clean_up()
    assert sorted(p.name for p in tmp_path.iterdir()) == [updates.ASSET]


def test_a_broken_download_leaves_the_exe_alone(monkeypatch, tmp_path):
    exe = tmp_path / updates.ASSET
    exe.write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout: _Response(b"ne"))
    with pytest.raises(OSError):
        updates.install({"download": DL, "size": 3})
    assert sorted(p.name for p in tmp_path.iterdir()) == [updates.ASSET] and exe.read_bytes() == b"old"


def test_links_outside_the_repo_are_not_followed(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "__version__", "1.0.0")
    _release(monkeypatch, "v2.0.0", assets=[{"name": updates.ASSET, "size": 3,
                                             "browser_download_url": "https://evil.example/MKWorldMogiTracker.exe"}])
    up = updates.latest()
    assert up["download"] is None and up["page"].startswith("https://github.com/")
    exe = tmp_path / updates.ASSET
    exe.write_bytes(b"old")
    monkeypatch.setattr(sys, "executable", str(exe))
    with pytest.raises(OSError):
        updates.install({"download": "https://github.com.evil.example/x.exe", "size": 3})
    assert exe.read_bytes() == b"old"


def test_the_test_release_url_is_ignored_in_the_exe(monkeypatch):
    seen = []

    def urlopen(req, timeout):
        seen.append(req.full_url)
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("MKW_TRACKER_RELEASES", "https://evil.example/latest.json")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    updates.latest()
    assert seen == [f"https://api.github.com/repos/{updates.REPO}/releases/latest"]
