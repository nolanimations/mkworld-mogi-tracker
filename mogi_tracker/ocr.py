"""Leaderboard OCR with a small recognizer trained on synthetic Mario Kart World leaderboard text.

No vision-language model: every row's fields (rank / name / +N / total) are cropped at fixed columns and read by
a ~22 MB text recognizer (ONNX, CPU). It never has to be told where a leaderboard is scrolled
to, because rows are located per frame, then identified by their printed rank, so frames taken at any
scroll offset can merge. The recognizer was trained only on synthetic text, no game files are part of this repo.

Coordinates below are 1920x1080-normalised.
"""
import collections
import difflib
import logging
import math
import os
import re
import time
import unicodedata

import cv2
import numpy as np

from . import paths

log = logging.getLogger(__name__)

# Layout
ROW_PITCH = 77.0          # 24p, rows repeat every 77.0 px, only the scroll phase is unknown
ROW_PITCH_12P = 76.955    # 12p, static
ROW_TOP_12P = 37.0
BOARD_TOP_MIN = 30
BOARD_BOTTOM_MAX = 1062
CROP_H = 66
BASELINE_IN_ROW = 51.5
CROP_TOP_IN_ROW = BASELINE_IN_ROW - 45
FIELD_CROPS = {"name": (1267, 1667), "total": (1735, 1830), "gain": (1650, 1745), "rank": (1100, 1190)}

POINTS_TABLE_24 = [15, 12, 10, 9, 9, 8, 8, 7, 7, 6, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 1]

MODEL_H, MODEL_W = 48, 320

_reader = None


# Recognizer
class Reader:
    """Batch recognizer over BGR field crops: recognise(crops) -> [(text, confidence)]."""

    def __init__(self, model_dir):
        import onnxruntime as ort

        plain, packed = os.path.join(model_dir, "rec.onnx"), os.path.join(model_dir, "rec.bin")
        if os.path.isfile(plain):
            model = plain
        elif os.path.isfile(packed):
            from . import modelpack

            with open(packed, "rb") as f:
                model = modelpack.unpack(f.read())
        else:
            raise FileNotFoundError(
                "OCR model not found (mogi_tracker/model/rec.onnx). It is not part of the source code, "
                "see 'The OCR model' in the README.")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, min(8, (os.cpu_count() or 4) // 2))
        self.session = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        with open(os.path.join(model_dir, "dict.txt"), encoding="utf-8") as f:
            self.classes = f.read().split("\n")

    @staticmethod
    def _prepare(crop):
        h, w = crop.shape[:2]
        w1 = max(8, int(round(w * MODEL_H / h)))
        img = cv2.resize(crop, (w1, MODEL_H), interpolation=cv2.INTER_AREA)
        rw = min(MODEL_W, int(math.ceil(MODEL_H * (img.shape[1] / MODEL_H))))
        img = cv2.resize(img, (rw, MODEL_H)).astype(np.float32).transpose(2, 0, 1) / 255.0
        out = np.zeros((3, MODEL_H, MODEL_W), np.float32)
        out[:, :, :rw] = (img - 0.5) / 0.5
        return out

    def recognise(self, crops, batch=8):
        results = []
        for i in range(0, len(crops), batch):
            x = np.stack([self._prepare(c) for c in crops[i:i + batch]])
            probs = self.session.run(None, {self.input_name: x})[0]
            idx, conf = probs.argmax(axis=2), probs.max(axis=2)
            for row_idx, row_conf in zip(idx, conf):
                keep = np.ones(len(row_idx), bool)
                keep[1:] = row_idx[1:] != row_idx[:-1]
                keep &= row_idx != 0
                text = "".join(self.classes[j] for j in row_idx[keep])
                results.append((text, float(row_conf[keep].mean()) if keep.any() else 0.0))
        return results


def get_reader():
    global _reader
    if _reader is None:
        _reader = Reader(paths.resource("model"))
    return _reader


def warm_up():
    """Run one dummy crop so the first capture isn't slow"""
    get_reader().recognise([np.zeros((CROP_H, 400, 3), np.uint8)])


# Frame geometry
def to_bgr(img):
    """PIL image or ndarray -> BGR ndarray at 1920x1080"""
    if not isinstance(img, np.ndarray):
        img = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    if abs(w / h - 16 / 9) > 0.02:
        return None
    return img if (w, h) == (1920, 1080) else cv2.resize(img, (1920, 1080), interpolation=cv2.INTER_AREA)


def comb_phase(img, lo=76.9, hi=77.1):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sig = np.concatenate([np.median(np.abs(np.diff(g[:, 1075:1900], axis=0)), axis=1), [0]])
    best = (-1.0, ROW_PITCH, 0.0)
    for pitch in np.arange(lo, hi + 1e-6, 0.05):
        for phase in np.arange(0, pitch, 0.5):
            idx = np.round(np.arange(phase, len(sig), pitch)).astype(int)
            idx = idx[idx < len(sig)]
            s = sig[idx].mean()
            if s > best[0]:
                best = (s, pitch, phase)
    return best[1], best[2], best[0] / max(float(np.mean(sig)), 1e-6)


def row_tops(img, lobby):
    if lobby == 12:
        return [ROW_TOP_12P + k * ROW_PITCH_12P for k in range(12)]
    pitch, phase, _ = comb_phase(img)
    tops, t = [], phase - pitch * int(phase // pitch + 1)
    while t + pitch <= BOARD_BOTTOM_MAX:
        if t >= BOARD_TOP_MIN:
            tops.append(t)
        t += pitch
    return tops


def crop_field(img, kind, top):
    x0, x1 = FIELD_CROPS[kind]
    y0 = int(round(top + CROP_TOP_IN_ROW))
    if y0 < 0 or y0 + CROP_H > img.shape[0]:
        return None
    return img[y0:y0 + CROP_H, x0:x1]


# Text clean-up
def fix_lookalikes(name):
    """Stuff like O/0 and I/l are incredibly hard to tell apart. Conservative rules: a 0 that starts
    a word and is followed by a lowercase letter is an O, an O/o directly between digits is a 0, an I between two
    lowercase letters is an l."""
    out = list(name)
    for i, ch in enumerate(name):
        prev = name[i - 1] if i else " "
        nxt = name[i + 1] if i + 1 < len(name) else " "
        if ch == "0" and not prev.isalnum() and nxt.isalpha() and nxt.islower():
            out[i] = "O"
        elif ch in "Oo" and prev.isdigit() and nxt.isdigit():
            out[i] = "0"
        elif ch == "I" and prev.isalpha() and prev.islower() and nxt.isalpha() and nxt.islower():
            out[i] = "l"
    return "".join(out)


_num = re.compile(r"^[+-]?\d+$")


def parse_int(text, signed=False):
    t = text.replace(" ", "")
    if not _num.match(t) or (not signed and t[0] in "+-"):
        return None
    return int(t)


# One frame
def read_frame(img, lobby=24):
    img = to_bgr(img)
    if img is None:
        raise ValueError("frame is not 16:9")
    tops = row_tops(img, lobby)
    kinds = ["name", "total"] + (["gain", "rank"] if lobby == 24 else [])
    jobs = [(ti, kind, crop_field(img, kind, top)) for ti, top in enumerate(tops) for kind in kinds]
    jobs = [(ti, kind, c) for ti, kind, c in jobs if c is not None]
    reads = get_reader().recognise([c for _, _, c in jobs]) if jobs else []
    per_row = collections.defaultdict(dict)
    for (ti, kind, _), read in zip(jobs, reads):
        per_row[ti][kind] = read

    rows = []
    for ti, top in enumerate(tops):
        f = per_row[ti]
        if "name" not in f or "total" not in f:
            continue
        total = parse_int(f["total"][0])
        if total is None:
            continue
        row = {"top": top, "ti": ti, "name": fix_lookalikes(f["name"][0].strip()), "total": total, "gain": 0,
               "rank": None, "conf": min(f["name"][1], f["total"][1])}
        if lobby == 24:
            rank = parse_int(f["rank"][0]) if "rank" in f else None
            gain = parse_int(f["gain"][0], signed=True) if "gain" in f else None
            row["rank"] = rank if rank is not None and 1 <= rank <= 24 else None
            row["gain"] = gain if gain is not None else 0
            # the OCR model is trained with +N digits in mind but 12p doesn't need those, +N not being there shouldn't lower the confidence of the model
            row["conf"] = min(row["conf"], f["rank"][1], f["gain"][1] if "gain" in f and f["gain"][0].strip() else 1.0)
        rows.append(row)

    if lobby == 24:
        rows = _infer_missing_ranks(rows)
    elif rows:
        for r in rows:
            r["rank"] = 1 + sum(o["total"] > r["total"] for o in rows)
    return rows


def _infer_missing_ranks(rows):
    known = [r for r in rows if r["rank"] is not None]
    kept = []
    for r in rows:
        if r["rank"] is None:
            cands = []
            prev = [k for k in known if k["ti"] < r["ti"]]
            nxt = [k for k in known if k["ti"] > r["ti"]]
            if prev:
                cands.append((r["ti"] - prev[-1]["ti"], prev[-1]["rank"] + (r["ti"] - prev[-1]["ti"])))
            if nxt:
                cands.append((nxt[0]["ti"] - r["ti"], nxt[0]["rank"] - (nxt[0]["ti"] - r["ti"])))
            cands = [c for c in cands if 1 <= c[1] <= 24]
            if not cands:
                continue
            r["rank"] = min(cands)[1]          # nearest neighbour
            r["conf"] = min(r["conf"], 0.5)
        kept.append(r)
    return kept


# Several frames
def _nfkc(s):
    return unicodedata.normalize("NFKC", s)


def _tie_slots(frame_rows):
    mult = collections.Counter()
    grouped = []
    for rows in frame_rows:
        g = collections.defaultdict(list)
        for r in sorted(rows, key=lambda r: r["top"]):
            g[r["rank"]].append(r)
        grouped.append(g)
        for rank, lst in g.items():
            mult[rank] = max(mult[rank], len(lst))
    ref = {}   # (rank, k) -> reference name
    for g in grouped:
        for rank, lst in g.items():
            if len(lst) == mult[rank]:
                for k, r in enumerate(lst):
                    ref.setdefault((rank, k), _nfkc(r["name"]))
    out = []
    for g in grouped:
        assigned = []
        for rank, lst in g.items():
            if len(lst) == mult[rank]:
                assigned += [((rank, k), r) for k, r in enumerate(lst)]
            else:
                free = list(range(mult[rank]))
                for r in lst:
                    nm = _nfkc(r["name"])
                    k = max(free, key=lambda k: difflib.SequenceMatcher(None, nm, ref.get((rank, k), "")).ratio())
                    free.remove(k)
                    assigned.append(((rank, k), r))
        out.append(assigned)
    return out


def merge_frames(frame_rows):
    """Merge by printed rank. gain+total is invariant while scores animate, votes are weighted by
    recognizer confidence. Returns (players sorted by rank, warnings)"""
    obs = collections.defaultdict(list)
    for assigned in _tie_slots(frame_rows):
        for slot, r in assigned:
            obs[slot].append(r)
    players, warnings = [], []
    for slot in sorted(obs):
        rows = obs[slot]
        name_w, sum_w = collections.Counter(), collections.Counter()
        for r in rows:
            name_w[_nfkc(r["name"])] += r["conf"]
            sum_w[r["gain"] + r["total"]] += r["conf"]
        name = name_w.most_common(1)[0][0]
        best_sum = sum_w.most_common(1)[0][0]
        pick = next(r for r in rows if r["gain"] + r["total"] == best_sum)
        if len(sum_w) > 1:
            warnings.append(f"#{slot[0]}: frames disagree on score {dict(sum_w)}, using {best_sum}")
        players.append({"rank": slot[0], "name": name, "gain": pick["gain"], "total": pick["total"], "seen": len(rows)})
    return players, warnings


def _gain_too_big(p):
    return p["gain"] > POINTS_TABLE_24[min(p["rank"], 24) - 1]


def is_complete(players, lobby_size):
    if len(players) != lobby_size:
        return False
    return lobby_size != 24 or not any(_gain_too_big(p) for p in players)


def analyze(images, lobby_size=24):
    frames, merged, warnings = [], [], []
    for img in images:
        start = time.perf_counter()
        rows = read_frame(img, lobby_size)
        frames.append({"rows": rows, "seconds": round(time.perf_counter() - start, 2)})
        log.info("frame %d: %d rows in %ss", len(frames), len(rows), frames[-1]["seconds"])
        merged, warnings = merge_frames([f["rows"] for f in frames])
        if is_complete(merged, lobby_size):
            break
    if len(merged) != lobby_size:
        warnings.append(f"read {len(merged)} of {lobby_size} players")
    if lobby_size == 24:
        warnings += [f"#{p['rank']}: +{p['gain']} is more than {p['rank']}th place can score"
                     for p in merged if _gain_too_big(p)]
    for w in warnings:
        log.warning(w)
    return {
        "players": [{"full_name": p["name"], "white_score": p["total"], "green_score": p["gain"]} for p in merged],
        "merged": merged,
        "warnings": warnings,
        "frames_read": len(frames),
        "frames": frames,
    }
