import logging
import threading

log = logging.getLogger(__name__)


class Hotkey:
    def __init__(self, on_press):
        self._on_press = on_press
        self._handle = None
        self._lock = threading.Lock()
        self.combo = ""
        self.recording = False

    def set(self, combo) -> bool:
        """Bind `combo` ("down", "ctrl+f9", ...), "" unbinds"""
        import keyboard

        with self._lock:
            if self._handle is not None:
                try:
                    keyboard.remove_hotkey(self._handle)
                except (KeyError, ValueError):
                    pass
                self._handle = None
            self.combo = ""
            if not combo:
                return True
            try:
                self._handle = keyboard.add_hotkey(combo, self._on_press, suppress=False)
            except Exception as e:
                log.warning("could not bind hotkey %r: %s", combo, e)
                return False
            self.combo = combo
            return True

    def record(self, on_done):
        import keyboard

        if self.recording:
            return
        self.recording = True
        previous = self.combo
        self.set("")   # so pressing the old hotkey while choosing a new one doesn't capture lol

        def wait():
            try:
                combo = keyboard.read_hotkey(suppress=False)
                if combo in ("esc", "escape"):
                    combo = ""
                if not self.set(combo):
                    self.set(previous)
            except Exception as e:
                log.warning("hotkey recording failed: %s", e)
                self.set(previous)
            finally:
                self.recording = False
                on_done()

        threading.Thread(target=wait, daemon=True).start()

    def close(self):
        try:
            self.set("")
        except Exception:
            pass
