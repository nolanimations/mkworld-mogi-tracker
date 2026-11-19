import argparse
import ctypes
import logging
import logging.handlers
import os
import sys
import threading
import webbrowser

from . import APP_NAME, paths, server, updates
from .controller import Controller


def _setup_logging():
    handlers = [logging.handlers.RotatingFileHandler(paths.data_dir() / "tracker.log", maxBytes=300_000,
                                                     backupCount=1, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)


def _alert(text):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x40)
    except Exception:
        print(text)


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--browser", action="store_true", help="open the app in the default browser")
    parser.add_argument("--no-window", action="store_true", help="only run the local server (dev)")
    parser.add_argument("--data-dir", help="dev: keep settings and the last capture in this folder")
    parser.add_argument("--test-frames", help="dev: replay saved frames instead of capturing in-game")
    parser.add_argument("--test-video", help="dev: play a recording in real time as if it were the screen")
    parser.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.data_dir:
        os.environ["MKW_TRACKER_DATA_DIR"] = args.data_dir
    if args.test_frames:
        os.environ["MKW_TRACKER_TEST_FRAMES"] = args.test_frames
    if args.test_video:
        os.environ["MKW_TRACKER_TEST_VIDEO"] = args.test_video

    _setup_logging()
    log = logging.getLogger("mogi_tracker")
    updates.clean_up(wait=20 if args.after_update else 0)
    controller = Controller()
    try:
        _, url = server.start(controller)
    except server.AlreadyRunning:
        _alert(f"{APP_NAME} is already running.")
        return
    except OSError as e:
        _alert(f"{APP_NAME} could not start: {e}")
        return
    log.info("serving on %s", url)

    stop = threading.Event()

    def quit_app():
        stop.set()
        try:
            import webview
            for window in list(webview.windows):
                window.destroy()
        except Exception:
            pass
    controller.quit = quit_app

    try:
        if args.no_window:
            print(url)
            stop.wait()
        elif args.browser or not _open_window(url, log):
            webbrowser.open(url)
            stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()


def _open_window(url, log) -> bool:
    try:
        import webview

        webview.create_window(APP_NAME, url, width=1060, height=820, min_size=(900, 640),
                              background_color="#0a1030", text_select=True)
        webview.start(gui="edgechromium")
        return True
    except Exception:
        log.exception("could not open the app window, falling back to the browser")
        return False


if __name__ == "__main__":
    main()
