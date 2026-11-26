"""Camera sources with fake devices"""
import threading

import cv2
import numpy as np
import pytest

from mogi_tracker import capture, controller, settings

DEVICES = ["Webcam", "AVerMedia HD Capture GC573 1", "OBS Virtual Camera", "Elgato HD60 X", "Elgato HD60 X"]


class FakeCamera:
    opened, frames, size, made = [], {}, {}, []

    def __init__(self, index, api):
        self.index, self.w, self.h = index, 640, 480
        FakeCamera.made.append(index)

    def isOpened(self):
        return self.index in FakeCamera.opened

    def set(self, prop, value):
        w, h = FakeCamera.size.get(self.index, (1920, 1080))
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            self.w = w
        elif prop == cv2.CAP_PROP_FRAME_HEIGHT:
            self.h = h

    def read(self):
        if not FakeCamera.frames.get(self.index, True):
            return False, None
        return True, np.full((self.h, self.w, 3), self.index, np.uint8)

    def release(self):
        pass


@pytest.fixture(autouse=True)
def devices(monkeypatch):
    capture.release()
    FakeCamera.opened, FakeCamera.frames, FakeCamera.size, FakeCamera.made = [0, 1, 2, 3, 4], {}, {}, []
    monkeypatch.setattr(capture, "_device_names", lambda: list(DEVICES))
    monkeypatch.setattr(cv2, "VideoCapture", FakeCamera)
    monkeypatch.delenv("MKW_TRACKER_TEST_FRAMES", raising=False)
    monkeypatch.delenv("MKW_TRACKER_TEST_VIDEO", raising=False)
    yield
    capture.release()


def test_other_lists_every_camera_but_obs_and_tells_duplicates_apart():
    assert capture.cameras() == ["Webcam", "AVerMedia HD Capture GC573 1", "Elgato HD60 X", "Elgato HD60 X (2)"]


def test_a_camera_is_found_by_name_also_when_the_order_changed(monkeypatch):
    assert capture.check_camera("camera", "Elgato HD60 X (2)") == (1920, 1080)
    assert FakeCamera.made == [4]
    capture.release()
    monkeypatch.setattr(capture, "_device_names", lambda: DEVICES[::-1])
    capture.check_camera("camera", "AVerMedia HD Capture GC573 1")
    assert FakeCamera.made[-1] == 3
    capture.check_camera("obs", "")
    assert FakeCamera.made[-1] == 2


def test_busy_capture_card_says_why():
    FakeCamera.opened = [0, 2]
    with pytest.raises(capture.CaptureError, match="could not be opened. Is something else using it.*use Virtual Camera instead"):
        capture.check_camera("camera", "AVerMedia HD Capture GC573 1")


def test_capture_card_that_opens_but_gives_nothing():
    FakeCamera.frames[1] = False
    with pytest.raises(capture.CaptureError, match="gave nothing. Is something else using it"):
        list(capture.stream("camera", 1, 1, "AVerMedia HD Capture GC573 1"))
    assert FakeCamera.made == [1, 1]                  # try again


def test_unplugged_or_not_picked_yet():
    with pytest.raises(capture.CaptureError, match="doesn't seem to be connected"):
        capture.check_camera("camera", "Razer Ripsaw")
    with pytest.raises(capture.CaptureError, match=r"Pick a camera first \(Settings > Capture From > Other\)"):
        capture.check_camera("camera", "")


def test_obs_keeps_its_own_messages():
    FakeCamera.opened = []
    with pytest.raises(capture.CaptureError, match="OBS Virtual Camera could not be opened. Press Start Virtual Camera"):
        capture.check_camera("obs", "")


def test_picture_that_isnt_16_by_9():
    FakeCamera.size[1] = (1280, 1024)
    with pytest.raises(capture.CaptureError, match="1280×1024, which is not 16:9. Set it to 1920×1080, or use OBS Virtual Camera instead"):
        capture.check_camera("camera", "AVerMedia HD Capture GC573 1")


def test_frames_from_the_card_and_the_feed():
    frames = list(capture.stream("camera", 2, 1, "AVerMedia HD Capture GC573 1"))
    assert [f.size for f in frames] == [(1920, 1080)] * 2 and capture.camera_size() == (1920, 1080)
    feed = capture.Feed("camera", 1, "Elgato HD60 X")
    assert feed.grab(1060).shape == (1080, 860, 3) and int(feed.grab()[0, 0, 0]) == 3
    assert capture.camera_size() == (1920, 1080)
    capture.release()
    assert capture.camera_size() is None


def make_controller(monkeypatch, checks):
    c = controller.Controller.__new__(controller.Controller)
    c.settings = dict(settings.DEFAULTS)
    c.lock, c.watcher, c.watch_error, c._watch_source = threading.RLock(), None, "", None
    c.message = {"id": 0, "text": "", "tone": "info"}
    c.session = type("S", (), {"lobby": 24, "format": "4v4"})()
    monkeypatch.setattr(settings, "save", lambda s: s)
    monkeypatch.setattr(c, "changed", lambda: None, raising=False)
    monkeypatch.setattr(threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: checks.append(target(*args))})())
    return c


@pytest.mark.parametrize("size, tone, text", [((1920, 1080), "good", "works (1920×1080)"),
                                              ((1280, 720), "bad", "sends 1280×720. Fine for 12p, but 24p will probably fail")])
def test_picking_a_camera_checks_it(monkeypatch, size, tone, text):
    FakeCamera.size[1] = size
    checks = []
    c = make_controller(monkeypatch, checks)
    c._do_settings({"source": "camera", "camera": "AVerMedia HD Capture GC573 1"})
    assert len(checks) == 1 and c.message["tone"] == tone and text in c.message["text"]
    c._do_settings({"background": "blue"})
    assert len(checks) == 1                            # nothing about the camera changed


def test_a_busy_card_is_told_when_picked(monkeypatch):
    FakeCamera.opened = []
    checks = []
    c = make_controller(monkeypatch, checks)
    c._do_settings({"source": "camera", "camera": "Elgato HD60 X (2)"})
    assert c.message["tone"] == "bad" and "Is something else using it" in c.message["text"]


def test_auto_capture_watches_the_picked_camera(monkeypatch):
    made = []
    monkeypatch.setattr(controller.autocapture, "Watcher", lambda *a, camera="": made.append((a[:2], camera)) or
                        type("W", (), {"start": lambda self: self, "stop": lambda self: None})())
    c = make_controller(monkeypatch, [])
    c._do_settings({"source": "camera", "camera": "Elgato HD60 X", "auto_capture": True})
    c._do_settings({"camera": "Webcam"})
    assert made == [(("camera", 1), "Elgato HD60 X"), (("camera", 1), "Webcam")]
