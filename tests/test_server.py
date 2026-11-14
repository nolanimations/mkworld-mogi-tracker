import json
import urllib.error
import urllib.request

import pytest

from mogi_tracker import server


class FakeController:
    def __init__(self, port):
        self.settings = {"port": port}
        self.port = port
        self.version = 0
        self.acted = []
        import threading
        self.changed_cond = threading.Condition()

    def state(self):
        return {"teams": []}

    def act(self, action, data):
        self.acted.append((action, data))
        return {"ok": True}


@pytest.fixture
def running(tmp_path, monkeypatch):
    monkeypatch.setenv("MKW_TRACKER_DATA_DIR", str(tmp_path))
    ctrl = FakeController(23511)
    srv, url = server.start(ctrl)
    yield ctrl, url
    srv.shutdown()
    srv.server_close()


def post(url, token):
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json", "X-Token": token})
    return urllib.request.urlopen(req, timeout=5)


def test_second_copy_is_refused(running):
    ctrl, _ = running
    with pytest.raises(server.AlreadyRunning):
        server.start(FakeController(ctrl.port))


def test_changes_need_the_page_token(running):
    ctrl, url = running
    with pytest.raises(urllib.error.HTTPError) as e:
        post(url + "api/capture", "wrong")
    assert e.value.code == 403 and ctrl.acted == []
    page = urllib.request.urlopen(url, timeout=5).read().decode()
    token = page.split('MKW_TOKEN = "')[1].split('"')[0]
    assert json.loads(post(url + "api/capture", token).read()) == {"ok": True}
    assert ctrl.acted == [("capture", {})]


def test_other_hosts_and_paths_are_refused(running):
    _, url = running
    req = urllib.request.Request(url + "api/state", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(url + "static/../../run.py", timeout=5)
    assert e.value.code == 404
