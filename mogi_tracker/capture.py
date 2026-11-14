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


def _frames(source, count, monitor):
    test_folder = os.environ.get("MKW_TRACKER_TEST_FRAMES")
    if test_folder:
        return _from_test_folder(test_folder, count)
    return _from_obs(count) if source == "obs" else _from_monitor(count, monitor)


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
