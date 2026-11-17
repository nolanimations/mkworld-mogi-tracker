# time to glue
import json
import logging
import os
import shutil
import threading
import time

import cv2
import numpy as np
from PIL import Image

from . import __version__, autocapture, capture, hotkey, ocr, paths, settings
from .session import TOTAL_RACES, Session

log = logging.getLogger(__name__)

MIN_SHARE = 2   # a capture counts only if at least 1/MIN_SHARE of the room was read


class Controller:
    def __init__(self):
        self.settings = settings.load()
        self.session = Session(self.settings["lobby"], self.settings["format"])
        self.lock = threading.RLock()
        self.changed_cond = threading.Condition()
        self.version = 0
        self.busy = False
        self.typing = False
        self.message = {"id": 0, "text": "", "tone": "info"}
        self.port = self.settings["port"]
        self.hotkey = hotkey.Hotkey(self.capture)
        if self.settings["hotkey"] and not self.hotkey.set(self.settings["hotkey"]):
            self.settings["hotkey"] = ""
        self.watcher = None
        self._watch_source = None
        self.watch_error = ""
        threading.Thread(target=self._warm_up, daemon=True).start()
        self._sync_watcher()

    # state
    def state(self) -> dict:
        with self.lock:
            st = self.session.snapshot(self.settings["my_tag"])
            st.update({
                "busy": self.busy,
                "message": self.message,
                "settings": {k: self.settings[k] for k in
                             ("source", "monitor", "my_tag", "mark_my_tag", "auto_copy", "auto_capture",
                              "overlay_layout", "background")},
                "hotkey": {"combo": self.hotkey.combo, "recording": self.hotkey.recording},
                "watching": {"on": self.watcher is not None, "error": self.watch_error},
                "overlay_url": f"http://127.0.0.1:{self.port}/overlay",
                "version": __version__,
            })
            return st

    def changed(self):
        with self.changed_cond:
            self.version += 1
            self.changed_cond.notify_all()

    def say(self, text, tone="info"):
        self.message = {"id": self.message["id"] + 1, "text": text, "tone": tone}

    def _save_settings(self):
        self.settings["lobby"], self.settings["format"] = self.session.lobby, self.session.format
        self.settings = settings.save(self.settings)

    def _warm_up(self):
        try:
            ocr.warm_up()
        except Exception as e:
            log.exception("the recognizer failed to load")
            self.say(f"The score reader could not be loaded: {e}", "bad")
            self.changed()

    # capture
    def capture(self):
        with self.lock:
            if self.busy or self.typing or self.hotkey.recording:
                return False
            self.busy = True
        self.changed()
        threading.Thread(target=self._capture_job, daemon=True).start()
        return True

    def _capture_job(self):
        try:
            lobby = self.session.lobby
            start = time.perf_counter()
            frames = []

            def taken():
                for frame in capture.stream(self.settings["source"], 1 if lobby == 12 else capture.BURST_COUNT,
                                            self.settings["monitor"]):
                    frames.append(frame)
                    yield frame

            result = ocr.analyze(taken(), lobby)
            seconds = time.perf_counter() - start
            self._save_last_capture(frames, {"lobby": lobby, "seconds": round(seconds, 2), "players": result["players"],
                                             "merged": result["merged"], "warnings": result["warnings"],
                                             "frames_read": result["frames_read"]})
            players = result["players"]
            if len(players) * MIN_SHARE < lobby:
                found = f"only {len(players)} players detected" if players else "no results found"
                self.say(f"Nothing changed: {found}. Capture while the results are on screen.", "bad")
                return
            rows = result["frames"][-1]["rows"]
            tidy = lobby != 12 or [r["ti"] for r in rows] == list(range(len(rows)))
            self._apply(players, lobby, tidy)
        except capture.CaptureError as e:
            self.say(str(e), "bad")
        except Exception as e:
            log.exception("capture failed")
            self.say(f"Capture failed: {e}", "bad")
        finally:
            self.busy = False
            self.changed()

    def _apply(self, players, lobby, tidy, auto=False):
        with self.lock:
            if auto and self.session.same_board(players):
                return     # already captured
            self.session.apply_capture(players, tidy_board=tidy)
            race = self.session.race_info()["number"]
        copied = self.settings["auto_copy"] and self._copy_scores()
        if len(players) < lobby:
            self.say(f"Only {len(players)} of {lobby} players were read.", "bad")
        elif auto:
            self.say(f"Race {race} captured" + (", scores copied" if copied else ""), "good")
        else:
            self.say("Scores copied." if copied else "", "good")

    @staticmethod
    def _save_last_capture(frames, record):
        """Helps diagnosing any malformed captures"""
        try:
            folder = paths.last_capture_dir()
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True, exist_ok=True)
            for i, img in enumerate(frames):
                if isinstance(img, np.ndarray):
                    img = Image.fromarray(cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_BGR2RGB))
                img.convert("RGB").save(folder / f"frame_{i}.jpg", "JPEG", quality=90)
            (folder / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            log.warning("could not save the last capture: %s", e)

    # auto-capture
    def _sync_watcher(self):
        want = self.settings["auto_capture"]
        source = (self.settings["source"], self.settings["monitor"])
        if self.watcher and (not want or source != self._watch_source):
            self.watcher.stop()
            self.watcher, self.watch_error = None, ""
        if want and not self.watcher:
            self._watch_source = source
            self.watcher = autocapture.Watcher(*source, lambda: self.session.lobby, self._auto_begin,
                                               self._auto_result, self._auto_error).start()

    def _auto_begin(self):
        with self.lock:
            if self.busy or self.hotkey.recording:
                return False
            self.busy = True
        self.changed()
        return True

    def _auto_result(self, outcome):
        try:
            lobby = outcome["lobby"]
            if outcome.get("missed") and outcome.get("seen", 0) * 4 < lobby:
                log.info("auto-capture: no scoreboard after all (%s players read)", outcome.get("seen", 0))
                return
            self._save_last_capture(outcome.get("frames", []), {
                "lobby": lobby, "auto": True, "missed": bool(outcome.get("missed")),
                "players": outcome.get("players", []), "warnings": outcome.get("warnings", [])})
            if outcome.get("failed"):
                self.say("Auto-capture could not read the scoreboard, see tracker.log", "bad")
            elif outcome.get("missed"):
                final = self.session.race_info()["number"] == TOTAL_RACES - 1
                self.say("Missed the final scoreboard. Add last race's points by hand" if final else
                         "Missed this race's scoreboard. It should catch up after the next race", "bad")
            else:
                self._apply(outcome["players"], lobby, outcome["tidy"], auto=True)
        except Exception as e:
            log.exception("auto-capture result failed")
            self.say(f"Capture failed: {e}", "bad")
        finally:
            self.busy = False
            self.changed()

    def _auto_error(self, text):
        self.watch_error = text
        if text:
            self.say(f"Auto-capture: {text}", "bad")
        self.changed()

    # actions
    def act(self, action, data):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return {"ok": False, "error": f"unknown action {action}"}
        if self.busy and action in self._BLOCKED_WHILE_BUSY:   # scores are about to change manually
            return {"ok": False, "error": "busy"}
        with self.lock:
            out = handler(data) or {"ok": True}
        self.changed()
        return out

    _BLOCKED_WHILE_BUSY = {"bank_all", "undo", "reset", "adjust", "suggestion", "settings"}

    def _do_capture(self, _):
        return {"ok": self.capture()}

    def _do_typing(self, data):
        self.typing = bool(data.get("on"))

    def _copy_scores(self) -> str:
        import pyperclip

        text = self.session.clipboard_text(self.settings["my_tag"], self.settings["mark_my_tag"])
        if text:
            try:
                pyperclip.copy(text)
            except Exception as e:
                log.warning("could not copy to the clipboard: %s", e)
                return ""
        return text

    def _do_copy(self, _):
        text = self._copy_scores()
        if not text:
            self.say("Nothing to copy")
            return {"ok": False}
        self.say(f"Copied: {text}", "good")
        return {"ok": True, "text": text}

    def _do_bank_all(self, _):
        if self.session.bank_all():
            self.say("Scores saved, ready for reopen", "good")
        else:
            self.say("No scores to save")

    def _do_undo(self, _):
        label = self.session.undo()
        if label:
            self._save_settings()
            self.say(f"Undone: {label}")

    def _do_reset(self, _):
        self.session.reset()
        self.say("New mogi, scores cleared")

    def _do_adjust(self, data):
        try:
            points = int(str(data.get("points", "")).strip())
        except ValueError:
            self.say("Points must be a whole number, like 12 or -3", "bad")
            return {"ok": False, "reason": "points"}
        if not points:
            return {"ok": False, "reason": "points"}
        out = self.session.adjust(data.get("tag", ""), points, create=bool(data.get("create")))
        if out["ok"]:
            self.say(f"{points:+} for {out['tag']}", "good")
        elif out["reason"] == "ambiguous":
            self.say(f"More than one tag starts like that ({', '.join(out['matches'])}). Type the full tag", "bad")
        elif out["tag"]:
            self.say(f"No team with the tag “{out['tag']}” yet", "bad")
        else:
            self.say("Type a tag first, or click a team", "bad")
        return out

    def _do_suggestion(self, data):
        sid = data.get("id", "")
        if data.get("apply"):
            done = self.session.apply_suggestion(sid)
            if done:
                self.say(f"Done: {done['button'][0].lower()}{done['button'][1:]}", "good")
        else:
            self.session.dismiss_suggestion(sid)

    def _do_settings(self, data):
        if data.get("lobby") in settings.OPTIONS["lobby"]:
            self.session.set_lobby(data["lobby"])
            if self.session.lobby == 12:
                self.say("capture once the scoreboard finishes adding points")
        if "format" in data:
            self.session.set_format(str(data["format"]))
        for key in ("source", "monitor", "my_tag", "mark_my_tag", "auto_copy", "auto_capture", "overlay_layout",
                    "background"):
            if key in data and (key not in settings.OPTIONS or data[key] in settings.OPTIONS[key]):
                self.settings[key] = data[key]
        if "source" in data:
            capture.release()
        self._save_settings()
        self._sync_watcher()

    def _do_hotkey(self, data):
        if data.get("clear"):
            self.hotkey.set("")
            self.settings["hotkey"] = ""
            self._save_settings()
            return
        self.hotkey.record(self._hotkey_recorded)

    def _hotkey_recorded(self):
        with self.lock:
            self.settings["hotkey"] = self.hotkey.combo
            self._save_settings()
        self.changed()

    def _do_open_folder(self, data):
        folder = paths.last_capture_dir()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)   # noqa S606

    def _do_open_licences(self, _):
        root = paths.bundle_root()
        for name in ("THIRD_PARTY_NOTICES.txt", "LICENSE"):
            if (root / name).is_file():
                os.startfile(root / name)   # noqa S606

    def _do_monitors(self, _):
        try:
            return {"ok": True, "monitors": capture.monitors()}
        except Exception as e:
            return {"ok": False, "error": str(e), "monitors": []}

    def close(self):
        self.hotkey.close()
        if self.watcher:
            self.watcher.stop()
        capture.release()
