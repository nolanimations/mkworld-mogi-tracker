"""Grab frames of the game: a screenshot of a monitor or OBS Virtual Camera"""
import glob
import os
import queue
import threading
import time

from PIL import Image

BURST_COUNT = 5        # for 24p
BURST_INTERVAL = 0.5
OBS_NAME = "OBS Virtual Camera"
OBS_SIZE = (1920, 1080)
OBS_FLUSH_READS = 3

_lock = threading.Lock()
_camera = None
_test_index = 0


class CaptureError(Exception):
    """6767676767"""


def monitors() -> list:
    import mss

    with mss.mss() as sct:
        return [{"index": i, "width": m["width"], "height": m["height"]} for i, m in enumerate(sct.monitors) if i > 0]


def _check_shape(img, what, advice):
    w, h = img.size
    if abs(w / h - 16 / 9) > 0.02:
        raise CaptureError(f"{what} is {w}×{h}, which is not 16:9. {advice}")


def _from_monitor(count, monitor):
    import mss

    with mss.mss() as sct:
        if not 1 <= monitor < len(sct.monitors):
            monitor = 1
        area = sct.monitors[monitor]
        for i in range(count):
            shot = sct.grab(area)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            _check_shape(img, "That screen", "Show the game fullscreen on a 16:9 screen, or use OBS Virtual "
                                             "Camera")
            yield img
            if i < count - 1:
                time.sleep(BURST_INTERVAL)


def _obs_index():
    try:
        import comtypes
        from pygrabber.dshow_graph import FilterGraph

        comtypes.CoInitialize()
        try:
            devices = FilterGraph().get_input_devices()
        finally:
            comtypes.CoUninitialize()
    except Exception as e:
        raise CaptureError(f"Could not list camera devices ({e}).")
    for index, name in enumerate(devices):
        if OBS_NAME in name:
            return index
    raise CaptureError("OBS Virtual Camera not found. Press Start Virtual Camera in OBS first.")


def _open_camera():
    import cv2

    cam = cv2.VideoCapture(_obs_index(), cv2.CAP_DSHOW)
    if not cam.isOpened():
        raise CaptureError("Could not open OBS Virtual Camera. Is another program using it?")
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, OBS_SIZE[0])
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, OBS_SIZE[1])
    return cam


def _from_obs(count):
    import cv2

    global _camera
    if _camera is None:
        _camera = _open_camera()
    for _ in range(OBS_FLUSH_READS):
        _camera.read()
    ok, frame = _camera.read()
    if not ok:
        release()
        _camera = _open_camera()
        ok, frame = _camera.read()
    if not ok:
        release()
        raise CaptureError("OBS Virtual Camera gave nothing. Press Start Virtual Camera in OBS.")
    for i in range(count):
        if i:
            time.sleep(BURST_INTERVAL)
            ok, frame = _camera.read()
            if not ok:
                continue
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        _check_shape(img, "OBS Virtual Camera's picture", "Set the OBS output to a 16:9 aspect ratio (eg. 1920×1080).")
        yield img


def _from_test_folder(folder, count):
    """Development only (MKW_TRACKER_TEST_FRAMES): yield images from a folder of frame_*.png, so I don't have to constantly test in-game"""
    global _test_index
    sets = sorted(d for d in glob.glob(os.path.join(folder, "*")) if os.path.isdir(d)) or [folder]
    chosen = sets[_test_index % len(sets)]
    _test_index += 1
    files = sorted(glob.glob(os.path.join(chosen, "frame_*.*")))
    if not files:
        raise CaptureError(f"No frame_* images in {chosen}")
    for f in files[:max(count, 1)]:
        yield Image.open(f).convert("RGB")


class _TestVideo:
    """Dev only (MKW_TRACKER_TEST_VIDEO): play a video in real time in the bg as if it were the screen"""

    def __init__(self, path):
        import cv2

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise CaptureError(f"Could not open {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.start = time.monotonic()
        self.pos = -1
        self.frame = None

    def grab(self):
        """BGR ndarray of the current frame"""
        want = int((time.monotonic() - self.start) * self.fps)
        while self.pos < want:
            ok = self.cap.grab()
            if not ok:
                self.frame = None if self.frame is None else self.frame * 0
                return self.frame
            self.pos += 1
            if self.pos == want:
                self.frame = self.cap.retrieve()[1]
        return self.frame


_video = None


def _test_video():
    global _video
    path = os.environ.get("MKW_TRACKER_TEST_VIDEO")
    if not path:
        return None
    if _video is None:
        _video = _TestVideo(path)
    return _video


def _from_test_video(count):
    import cv2

    for i in range(count):
        if i:
            time.sleep(BURST_INTERVAL)
        frame = _test_video().grab()
        if frame is not None:
            yield Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def _frames(source, count, monitor):
    test_folder = os.environ.get("MKW_TRACKER_TEST_FRAMES")
    if test_folder:
        return _from_test_folder(test_folder, count)
    if _test_video():
        return _from_test_video(count)
    return _from_obs(count) if source == "obs" else _from_monitor(count, monitor)


class Feed:
    """One frame at a time for the autocapture watcher as a BGR ndarray"""

    def __init__(self, source="monitor", monitor=1):
        self.source, self.monitor = source, monitor
        self._sct = None

    def grab(self, x_from=0):
        if self.source == "monitor" and not _test_video():
            return self._grab_monitor(x_from)
        if _test_video():
            with _lock:
                frame = _test_video().grab()
            if frame is None:
                raise CaptureError("The test video gave nothing.")
        else:
            frame = self._grab_obs()
        return frame[:, int(x_from * frame.shape[1] / 1920):]

    def _grab_monitor(self, x_from):
        import mss
        import numpy as np

        if self._sct is None:
            self._sct = mss.mss()
        monitors = self._sct.monitors
        mon = monitors[self.monitor if 1 <= self.monitor < len(monitors) else 1]
        w, h = mon["width"], mon["height"]
        if abs(w / h - 16 / 9) > 0.02:
            raise CaptureError(f"That screen is {w}×{h}, which is not 16:9. Show the game fullscreen on a 16:9 screen, "
                               "or use OBS Virtual Camera")
        left = int(x_from * w / 1920)
        area = {"left": mon["left"] + left, "top": mon["top"], "width": w - left, "height": h}
        return np.asarray(self._sct.grab(area))[:, :, :3]

    def _grab_obs(self):
        global _camera
        with _lock:
            if _camera is None:
                _camera = _open_camera()
            for _ in range(OBS_FLUSH_READS):
                _camera.read()
            ok, frame = _camera.read()
        if not ok:
            release()
            raise CaptureError("No OBS Virtual Camera found. Press Start Virtual Camera in OBS.")
        h, w = frame.shape[:2]
        if abs(w / h - 16 / 9) > 0.02:
            raise CaptureError(f"OBS Virtual Camera's picture is {w}×{h}, which is not 16:9. Set the OBS output to a "
                               "16:9 aspect ratio (eg. 1920×1080).")
        return frame

    def close(self):
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


def stream(source="monitor", count=BURST_COUNT, monitor=1):
    """Yield up to `count` frames (PIL images) as they are taken.

    Each frame is handled by its own thread so reading one frame does not delay grabbing the
    next one
    """
    q = queue.Queue()

    def produce():
        try:
            with _lock:
                for frame in _frames(source, count, monitor):
                    q.put(frame)
        except Exception as e:
            q.put(e)
        finally:
            q.put(None)

    threading.Thread(target=produce, daemon=True).start()
    while True:
        item = q.get()
        if item is None:
            return
        if isinstance(item, Exception):
            raise item if isinstance(item, CaptureError) else CaptureError(f"Could not capture: {item}")
        yield item


def release():
    global _camera
    if _camera is not None:
        try:
            _camera.release()
        except Exception:
            pass
        _camera = None
