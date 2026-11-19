"""Auto-capture (EXPERIMENTAL)

While racing the watcher does a light check 5 times a second and keeps only the last second of it
Once it sees something that looks like the results it checks 5-10 times a second.
When it's certain that it's actually a scoreboard, it reads the board

From testing I found that boards score ratio 4-11 with edges 4.5-15, racing stays under ratio 3 apart from a few spikes, and
dark or flat screens reach high ratios but edges under 4. Over a dark track a semi-transparent board can have only
2-3 rows with a clear edge, which for some reason looks very similar to the track voting screens, hence the rank check.
"""
import collections
import logging
import queue
import threading
import time

import cv2
import numpy as np

from . import capture, ocr

log = logging.getLogger(__name__)

IDLE_RATE = 5           # checks per second while racing
FAST_RATE = 5           # checks per second once a scoreboard-like thing shows up
SCROLL_RATE = 10
SCROLL_SECONDS = 2.0
HINTS = ((2.5, 2.0, 0), (2.0, 3.0, 3))   # (ratio, edge, rows), could be a board, look closer
BOARD = (4.5, 5.0, 2)   # (ratio, edge, rows): looks like a board, placement column determines the verdict
CONFIRM_CHECKS = 5
GIVE_UP_SECONDS = 2.5
KEEP_SECONDS = 6.0
GONE_SECONDS = 1.5      # if it doesn't receive a hint for this long it assumes the scoreboard is gone
READ_EVERY = 1.0
RANK_TRIES = 3
KEEP_FROM_X = 1060
WITH_GAINS = 0.8
LOOKBACK_SECONDS = 1.0
STALE_FRAMES = 4

IDLE, ARMED, READING, DONE = "idle", "armed", "reading", "done"


def _looks(signal, need):
    return all(have >= want for have, want in zip(signal, need))


def _hint(signal):
    return any(_looks(signal, need) for need in HINTS)


class Detector:

    def __init__(self):
        self.state = IDLE
        self.armed_at = None
        self.board_checks = 0
        self.quiet_since = None
        self.last_t = None

    def interval(self):
        if self.state in (IDLE, DONE):
            return 1 / IDLE_RATE
        scrolling = self.last_t is not None and self.last_t - self.armed_at < SCROLL_SECONDS
        return 1 / (SCROLL_RATE if scrolling else FAST_RATE)

    def finish(self):
        if self.state in (ARMED, READING):
            self.state = DONE

    def step(self, t, ratio, edge, rows):
        signal = (ratio, edge, rows)
        hint = _hint(signal)
        events = []
        self.last_t = t
        if self.state == IDLE:
            if hint:
                self.state, self.armed_at, self.quiet_since = ARMED, t, None
                self.board_checks = int(_looks(signal, BOARD))
                events += ["arm", "keep"]
            return events

        if self.state in (ARMED, READING) and hint and t - self.armed_at <= KEEP_SECONDS:
            events.append("keep")
        quiet = self._quiet_for(t, hint)
        if self.state == ARMED:
            self.board_checks += _looks(signal, BOARD)
            if self.board_checks >= CONFIRM_CHECKS:
                self.state = READING
                events.append("confirm")
            elif (quiet >= GONE_SECONDS or t - self.armed_at > KEEP_SECONDS or
                  (t - self.armed_at > GIVE_UP_SECONDS and not self.board_checks)):
                self.state = IDLE
                return events + ["drop"]
        elif quiet >= GONE_SECONDS:
            self.state = IDLE
            events.append("gone")
        return events

    def _quiet_for(self, t, hint):
        if hint:
            self.quiet_since = None
            return 0.0
        if self.quiet_since is None:
            self.quiet_since = t
        return t - self.quiet_since


def same_reads(a, b):
    def key(rows):
        return sorted(r["total"] + r["gain"] for r in rows)
    return bool(a) and bool(b) and key(a) == key(b)


def _keep(part):
    h, w = part.shape[:2]
    size = (1920 - KEEP_FROM_X, 1080)
    if not h or abs(w / h - size[0] / size[1]) > 0.03:
        return None
    if (w, h) == size:
        return np.array(part)
    return cv2.resize(np.ascontiguousarray(part), size, interpolation=cv2.INTER_AREA)


def _is_board(kept):
    picks = []
    for k in (len(kept) - 1, len(kept) // 2, 0)[:RANK_TRIES]:
        if 0 <= k < len(kept) and k not in picks:
            picks.append(k)
    return any(ocr.ranks_in_order(_full(kept[k])) for k in picks)


def _full(kept):
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[:, KEEP_FROM_X:] = kept
    return img


class Watcher:

    def __init__(self, source, monitor, lobby, begin, result, error):
        self.source, self.monitor, self.lobby = source, monitor, lobby
        self._begin, self._result, self._error = begin, result, error
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="autocapture", daemon=True)
        self._job = None

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._job:
            self._job.end()

    def cancel(self):
        job = self._job
        if job:
            job.end()

    # loop
    def _run(self):
        feed = capture.Feed(self.source, self.monitor)
        det = Detector()
        kept = []
        lookback = collections.deque(maxlen=max(1, round(LOOKBACK_SECONDS * IDLE_RATE)))
        failing = False
        try:
            while not self._stop.is_set():
                t0 = time.monotonic()
                try:
                    frame = feed.grab(KEEP_FROM_X)
                except capture.CaptureError as e:
                    if not failing:
                        self._error(str(e))
                    failing = True
                    self._stop.wait(5)
                    continue
                if failing:
                    failing = False
                    self._error("")
                was_idle = det.state == IDLE
                events = det.step(t0, *ocr.board_signal(frame, KEEP_FROM_X))
                if "arm" in events:
                    kept = list(lookback)   # a board fading in is hard to see
                    lookback.clear()
                small = _keep(frame) if "keep" in events or (was_idle and det.state == IDLE) else None
                if "keep" in events and small is not None:
                    if self._job:
                        self._job.add(small)
                    else:
                        kept.append(small)
                elif det.state == IDLE and small is not None:
                    lookback.append(small)
                if self._job:
                    self._job.latest(frame)
                if "drop" in events:
                    kept = []
                if "confirm" in events:
                    self._start_job(det, kept, frame)
                    kept = []
                if self._job and (det.state != READING or
                                  (self._job.windowed and time.monotonic() - det.armed_at > KEEP_SECONDS)):
                    self._job.end()
                if "gone" in events:
                    self._job = None
                self._stop.wait(max(0.0, det.interval() - (time.monotonic() - t0)))
        except Exception:
            log.exception("auto-capture stopped")
            self._error("Auto-capture stopped working, see tracker.log")
        finally:
            feed.close()

    def _start_job(self, det, kept, frame):
        lobby = self.lobby()
        if not _is_board(kept or [k for k in (_keep(frame),) if k is not None]):
            log.info("auto-capture: looks like a scoreboard, but no ranks in order")
            det.finish()
            return
        if not self._begin():
            det.finish()
            return
        job = _Read24(kept) if lobby == 24 else _Read12()
        job.latest(frame)
        self._job = job

        def run():
            try:
                outcome = job.run()
            except Exception:
                log.exception("auto-capture read failed")
                outcome = {"failed": True}
            outcome["lobby"] = lobby
            det.finish()
            self._result(outcome)

        threading.Thread(target=run, name="autocapture-read", daemon=True).start()


def _row_unread(frame, rows):
    read = {r["ti"] for r in rows}
    tops = ocr.row_tops(frame, 12)
    team = ocr.team_board(frame, tops)
    return any(ocr.rank_at(frame, top, team) for k, top in enumerate(tops) if k not in read)


def _one_row_per_rank(rows):
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["top"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            out.append(r)
    return out


class _Read24:
    windowed = True

    def __init__(self, kept):
        self.q = queue.Queue()
        for k in kept:
            self.q.put(k)
        self.ended = False

    def add(self, kept):
        if not self.ended:
            self.q.put(kept)

    def latest(self, frame):
        pass

    def end(self):
        if not self.ended:
            self.ended = True
            self.q.put(None)

    def _frames(self, read):
        while True:
            item = self.q.get()
            if item is None:
                return
            read.append(_full(item))
            yield read[-1]

    @staticmethod
    def _usable(merged):
        return (ocr.is_complete(merged, 24) and not any(p["contested"] for p in merged)
                and all(p["support"] >= 2 for p in merged))

    def run(self):
        read, used, merged, warnings, stale, mode = [], [], [], [], 0, ocr.TeamMode()
        for img in self._frames(read):
            team = mode.check(img, 24)
            rows = ocr.read_frame(img, 24, team=team)
            if mode.on:
                used = [u for u in used if u[1]]
            if not rows or sum(1 for r in rows if r["gain"]) < WITH_GAINS * len(rows):
                continue    # the board may already be re-sorting
            used.append((_one_row_per_rank(rows), team))
            before = {p["rank"]: p["support"] for p in merged}
            merged, warnings = ocr.merge_frames([rows for rows, _ in used])
            if self._usable(merged):
                break
            # after the scroll every frame shows the same top rows, once a few in a row add nothing for the
            # ranks that still need a second look, more frames won't help
            needy = [p for p in merged if before.get(p["rank"], 0) < 2]
            stale = 0 if any(p["support"] > before.get(p["rank"], 0) for p in needy) else stale + 1
            if stale >= STALE_FRAMES:
                break
        self.end()
        players = [{"full_name": p["name"], "white_score": p["total"], "green_score": p["gain"]} for p in merged]
        usable = self._usable(merged)
        log.info("auto-capture: 24p read %d players from %d of %d frames (usable=%s)",
                 len(merged), len(used), len(read), usable)
        if not usable:
            return {"missed": True, "seen": len(merged), "players": players, "warnings": warnings, "frames": read}
        return {"players": players, "tidy": True, "warnings": warnings, "frames": read}


class _Read12:
    windowed = False

    def __init__(self):
        self._frame = None
        self._lock = threading.Lock()
        self._ended = threading.Event()

    def add(self, kept):
        pass

    def latest(self, frame):
        with self._lock:
            self._frame = frame

    def end(self):
        self._ended.set()

    def run(self):
        before, before_frame, seen = None, None, 0
        while True:
            start = time.monotonic()
            with self._lock:
                part = self._frame
            kept = _keep(part) if part is not None else None
            frame = _full(kept) if kept is not None else None
            rows = ocr.read_frame(frame, 12, gains=True) if frame is not None else []
            if rows and len(rows) < 12 and _row_unread(frame, rows):
                rows = []
            if len(rows) * 2 >= 12 and same_reads(rows, before):
                players = [{"full_name": r["name"], "white_score": r["total"], "green_score": r["gain"]} for r in rows]
                return {"players": players, "tidy": [r["ti"] for r in rows] == list(range(len(rows))),
                        "warnings": [], "frames": [before_frame, frame]}
            before, before_frame, seen = rows, frame, max(seen, len(rows))
            if self._ended.wait(max(0.0, READ_EVERY - (time.monotonic() - start))):
                return {"missed": True, "seen": seen, "frames": [f for f in (frame,) if f is not None]}
