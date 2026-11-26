"""Grab frames of the game: a screenshot of a monitor, OBS Virtual Camera or another camera device (a capture card)"""
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
_camera_for = None               # (source, camera name)
_camera_size = None              # (width, height)
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


def _device_names():
    try:
        import comtypes
        from pygrabber.dshow_graph import FilterGraph

        comtypes.CoInitialize()
        try:
            return FilterGraph().get_input_devices()
        finally:
            comtypes.CoUninitialize()
    except Exception as e:
        raise CaptureError(f"Could not list camera devices ({e}).")


def _labels(names):
    """Two devices with the same name"""
    seen, out = {}, []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return out


def cameras() -> list:
    return [label for label in _labels(_device_names()) if OBS_NAME not in label]


def _shown(source, camera):
    return OBS_NAME if source == "obs" else camera


def _busy(source, camera, what):
    if source == "obs":
        return CaptureError(f"OBS Virtual Camera {what}. Press Start Virtual Camera in OBS")
    return CaptureError(f"{camera} {what}. Is something else using it? Most capture cards only work with one program at a "
                        "time, so if you want to use OBS for example, use Virtual Camera instead")


def _device_index(source, camera):
    labels = _labels(_device_names())
    for index, label in enumerate(labels):
        if (OBS_NAME in label) if source == "obs" else label == camera:
            return index
    if source == "obs":
        raise CaptureError("OBS Virtual Camera not found. Start Virtual Camera first")
    if not camera:
        raise CaptureError("Pick a camera first (Settings > Capture From > Other)")
    raise CaptureError(f"{camera} doesn't seem to be connected")


def _open_camera(source, camera):
    import cv2

    cam = cv2.VideoCapture(_device_index(source, camera), cv2.CAP_DSHOW)
    if not cam.isOpened():
        cam.release()
        raise _busy(source, camera, "could not be opened")
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, OBS_SIZE[0])
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, OBS_SIZE[1])
    return cam


def _read_camera(source, camera):
    """The newest frame (BGR) of the camera, call with _lock held"""
    global _camera, _camera_for, _camera_size
    if _camera_for != (source, camera):
        release()
    for attempt in range(2):
        if _camera is None:
            _camera = _open_camera(source, camera)
            _camera_for = (source, camera)
        for _ in range(OBS_FLUSH_READS):
            _camera.read()
        ok, frame = _camera.read()
        if ok and frame is not None:
            _camera_size = (frame.shape[1], frame.shape[0])
            return frame
        release()
    raise _busy(source, camera, "gave nothing")


def _check_camera_shape(frame, source, camera):
    h, w = frame.shape[:2]
    if abs(w / h - 16 / 9) > 0.02:
        advice = "Set the OBS output to a 16:9 aspect ratio (eg. 1920×1080)" if source == "obs" else \
            "Set it to 1920×1080, or use OBS Virtual Camera instead"
        raise CaptureError(f"{_shown(source, camera)}'s picture is {w}×{h}, which is not 16:9. {advice}")


def camera_size():
    return _camera_size if _camera is not None else None


def check_camera(source, camera):
    with _lock:
        frame = _read_camera(source, camera)
    _check_camera_shape(frame, source, camera)
    return frame.shape[1], frame.shape[0]


def _from_camera(count, source, camera):
    import cv2

    frame = _read_camera(source, camera)
    for i in range(count):
        if i:
            time.sleep(BURST_INTERVAL)
            ok, frame = _camera.read()
            if not ok:
                continue
        _check_camera_shape(frame, source, camera)
        yield Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


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


def _frames(source, count, monitor, camera=""):
    test_folder = os.environ.get("MKW_TRACKER_TEST_FRAMES")
    if test_folder:
        return _from_test_folder(test_folder, count)
    if _test_video():
        return _from_test_video(count)
    if source in ("obs", "camera"):
        return _from_camera(count, source, camera)
    return _from_monitor(count, monitor)


class Feed:
    """One frame at a time for the autocapture watcher as a BGR ndarray"""

    def __init__(self, source="monitor", monitor=1, camera=""):
        self.source, self.monitor, self.camera = source, monitor, camera
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
            with _lock:
                frame = _read_camera(self.source, self.camera)
            _check_camera_shape(frame, self.source, self.camera)
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

    def close(self):
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


def stream(source="monitor", count=BURST_COUNT, monitor=1, camera=""):
    """Yield up to `count` frames (PIL images) as they are taken.

    Each frame is handled by its own thread so reading one frame does not delay grabbing the
    next one
    """
    q = queue.Queue()

    def produce():
        try:
            with _lock:
                for frame in _frames(source, count, monitor, camera):
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
    global _camera, _camera_for
    if _camera is not None:
        try:
            _camera.release()
        except Exception:
            pass
        _camera, _camera_for = None, None
