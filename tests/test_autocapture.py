import numpy as np

from mogi_tracker import autocapture, ocr
from mogi_tracker.autocapture import ARMED, DONE, IDLE, READING, Detector, same_reads
from mogi_tracker.session import Session

RACING, DARK, HINT_ONLY, BOARD = (1.5, 2.0, 1), (40.0, 0.1, 0), (3.5, 4.0, 3), (8.0, 10.0, 9)
SPIKE = (6.3, 6.0, 6)        # similar to scoreboard, but only for a few tenths of a second
ONE_EDGE = (11.7, 11.0, 1)    # one very strong edge that just so happens to line up


def play(steps, det=None):
    """steps: [(seconds, (ratio, edge))]; checks at the detector's own pace. Returns [(t, events)]"""
    det = det or Detector()
    t, out = 0.0, []
    for seconds, signal in steps:
        end = t + seconds
        while t < end - 1e-9:
            events = det.step(t, *signal)
            if events:
                out.append((round(t, 2), events))
            t += det.interval()
    return det, out


def names(out):
    return [e for _, events in out for e in events]


def test_racing_and_short_spikes_never_confirm():
    det, out = play([(20, RACING), (0.4, SPIKE), (5, RACING), (0.4, SPIKE), (5, RACING)])
    assert "confirm" not in names(out)
    assert det.state == IDLE


def test_a_single_strong_edge_is_no_board():
    det, out = play([(2, RACING), (10, ONE_EDGE), (2, RACING)])
    assert "confirm" not in names(out)


def test_dark_and_flat_screens_do_not_even_arm():
    det, out = play([(5, RACING), (3, DARK), (5, RACING)])
    assert out == [] and det.state == IDLE


def test_board_confirms_after_a_second_and_keeps_frames_from_the_first_hint():
    det, out = play([(3, RACING), (0.4, HINT_ONLY), (6, BOARD)])
    ev = names(out)
    assert ev[:2] == ["arm", "keep"]
    confirm_at = next(t for t, e in out if "confirm" in e)
    armed_at = out[0][0]
    assert 0.4 <= confirm_at - armed_at <= 1.8
    keeps = [t for t, e in out if "keep" in e]
    assert keeps[0] == armed_at
    assert max(keeps) - armed_at <= autocapture.KEEP_SECONDS   # nothing after the board sorts
    assert det.state == READING


def test_a_flickering_board_still_confirms_and_keeps_its_first_frames():
    weak = (4.0, 5.7, 5)                  # board over a dark track for a moment: hint, but not board-like
    steps = [(2, RACING), (0.4, HINT_ONLY), (0.4, BOARD), (1.4, weak), (0.2, BOARD), (1.0, weak), (2, BOARD)]
    det, out = play(steps)
    assert "drop" not in names(out) and names(out).count("confirm") == 1
    assert names(out)[:2] == ["arm", "keep"]


def test_a_board_over_a_bright_track_arms_on_its_rows():
    det, out = play([(2, RACING), (1, (2.4, 3.7, 4))])
    assert names(out)[:1] == ["arm"]


def test_a_hint_that_is_no_board_is_dropped():
    det, out = play([(2, RACING), (4, HINT_ONLY), (2, RACING)])
    assert "drop" in names(out) and "confirm" not in names(out)
    assert det.state == IDLE


def test_one_read_per_board_then_waits_for_it_to_go():
    det = Detector()
    det, out = play([(1, RACING), (2, BOARD)], det)
    assert names(out).count("confirm") == 1
    det.finish()
    assert det.state == DONE
    det, out = play([(10, BOARD)], det)
    assert "confirm" not in names(out) and det.state == DONE
    det, out = play([(3, RACING)], det)
    assert names(out) == ["gone"] and det.state == IDLE
    det, out = play([(2, BOARD)], det)          # next race
    assert "confirm" in names(out)


def test_board_gone_before_a_read_still_ends_the_read():
    det, out = play([(1, RACING), (1.4, BOARD), (3, RACING)])
    assert "confirm" in names(out) and names(out)[-1] == "gone"


def test_slow_checks_while_racing():
    det = Detector()
    assert det.interval() == 1 / autocapture.IDLE_RATE
    det.step(0, *BOARD)
    assert det.state == ARMED and det.interval() == 1 / autocapture.SCROLL_RATE
    det.step(autocapture.SCROLL_SECONDS + 0.1, *BOARD)
    assert det.interval() == 1 / autocapture.FAST_RATE


def _board_image(w=1920, h=1080, pitch=77.0, phase=20.0):
    rng = np.random.default_rng(0)
    img = (rng.random((h, w, 3)) * 30 + 60).astype(np.uint8)
    sy = h / 1080
    y = phase
    while y < 1080:
        top = int(y * sy)
        img[top:top + max(1, int(3 * sy)), int(1050 * w / 1920):] = 200
        y += pitch
    return img


def test_board_signal_tells_rows_from_noise_and_black():
    assert autocapture._looks(ocr.board_signal(_board_image()), autocapture.BOARD)
    noise = (np.random.default_rng(1).random((1080, 1920, 3)) * 255).astype(np.uint8)
    assert not autocapture._hint(ocr.board_signal(noise))
    assert ocr.board_signal(np.zeros((1080, 1920, 3), np.uint8)) == (0.0, 0.0, 0)
    few = _board_image()
    few[300:] = 70
    assert ocr.board_signal(few)[2] <= 4


def test_board_signal_works_at_other_resolutions():
    assert autocapture._looks(ocr.board_signal(_board_image(2560, 1440)), autocapture.BOARD)


def test_board_signal_on_the_grabbed_right_part_matches_the_full_frame():
    for w, h in ((1920, 1080), (3840, 2160)):
        img = _board_image(w, h)
        part = img[:, int(autocapture.KEEP_FROM_X * w / 1920):]
        full, right = ocr.board_signal(img), ocr.board_signal(part, autocapture.KEEP_FROM_X)
        assert abs(full[0] - right[0]) < 0.3 and abs(full[1] - right[1]) < 0.3 and full[2] == right[2]
        kept = autocapture._keep(part)
        assert kept.shape == (1080, 1920 - autocapture.KEEP_FROM_X, 3)


def test_same_reads_compares_final_totals():
    a = [{"name": "Alpha", "total": 10, "gain": 5}, {"name": "Beta", "total": 20, "gain": 0}]
    b = [{"name": "Beta", "total": 20, "gain": 0}, {"name": "Alpha", "total": 15, "gain": 0}]
    assert same_reads(a, b)
    assert not same_reads(a, [{"name": "Alpha", "total": 10, "gain": 0}, b[0]])
    assert not same_reads([], [])
    assert not same_reads(a, None)
    flipped = [{"name": "=★ Alpha", "total": 15, "gain": 0}, {"name": "Beta", "total": 20, "gain": 0}]
    assert same_reads(b, flipped)


def test_same_board_is_not_captured_twice():
    s = Session(12, "FFA")
    board = [{"full_name": f"P{i}", "white_score": 12 - i, "green_score": 0} for i in range(12)]
    assert not s.same_board(board)
    s.apply_capture(board)
    assert s.same_board(board)
    later = [dict(p, green_score=1) for p in board]
    assert not s.same_board(later)


def _fake_ranks(monkeypatch, texts):
    """rank column reads `texts` top to bottom"""
    monkeypatch.setattr(ocr, "row_tops", lambda img, lobby: [40 + 77 * k for k in range(len(texts))])

    class Reader:
        def recognise(self, crops):
            return [(t, 0.9) for t in texts[:len(crops)]]
    monkeypatch.setattr(ocr, "get_reader", lambda: Reader())


def test_ranks_in_order_tells_a_board_from_other_rows(monkeypatch):
    img = np.zeros((1080, 1920, 3), np.uint8)
    for texts, board in ((["12", "13", "14", "15", "16"], True),
                         (["1", "2", "2", "4", "5"], True),
                         (["1", "2", "3", "4", "4", "6", "7", "8", "9", "10", "10", "12"], True),
                         (["3", "3", "3", "6", "7"], True),
                         (["1", "2", "4", "6", "8"], False),
                         (["", "7", "8", "", "9", "10"], True),         # some ranks unreadable
                         (["", "", "", "", ""], False),                 # just some bs
                         (["3", "17", "8", "2", "11"], False),
                         (["5", "6", "", "", ""], False)):               # too little info
        _fake_ranks(monkeypatch, texts)
        assert ocr.ranks_in_order(img) is board, texts


def test_24p_read_skips_frames_without_plus_points(monkeypatch):
    def row(rank, name, total, gain):
        return {"rank": rank, "name": name, "total": total, "gain": gain, "conf": 0.9, "top": rank * 77, "ti": rank}
    scroll = [row(r, f"P{r}", 0, ocr.POINTS_TABLE_24[r - 1]) for r in range(1, 25)]
    sorted_board = [row(r, f"P{25 - r}", r, 0) for r in range(1, 25)]
    frames = iter([sorted_board, scroll, sorted_board, scroll])
    monkeypatch.setattr(ocr, "read_frame", lambda img, lobby: next(frames))
    job = autocapture._Read24([np.zeros((1080, 1920 - autocapture.KEEP_FROM_X, 3), np.uint8)] * 4)
    job.end()
    out = job.run()
    assert "missed" not in out and len(out["players"]) == 24
    assert {p["full_name"]: p["white_score"] + p["green_score"] for p in out["players"]}["P1"] == 15


def test_24p_read_with_a_misread_total_is_a_miss_not_wrong_scores(monkeypatch):
    def row(rank, total):
        return {"rank": rank, "name": f"P{rank}", "total": total, "gain": ocr.POINTS_TABLE_24[rank - 1], "conf": 0.9,
                "top": rank * 77, "ti": rank}
    good = [row(r, 30) for r in range(1, 25)]
    misread = [row(r, 30) for r in range(1, 24)] + [row(24, 3)]
    monkeypatch.setattr(ocr, "read_frame", lambda img, lobby: misread)
    job = autocapture._Read24([np.zeros((1080, 1920 - autocapture.KEEP_FROM_X, 3), np.uint8)])
    job.end()
    assert job.run()["missed"]
    frames = iter([misread, good, good])
    monkeypatch.setattr(ocr, "read_frame", lambda img, lobby: next(frames))
    job = autocapture._Read24([np.zeros((1080, 1920 - autocapture.KEEP_FROM_X, 3), np.uint8)] * 3)
    job.end()
    out = job.run()
    assert "missed" not in out
    assert sum(p["white_score"] + p["green_score"] for p in out["players"]) == 24 * 30 + 144


def test_24p_board_with_a_rejoined_player_is_fine(monkeypatch):
    rows = [{"rank": r, "name": f"P{r}", "total": 0 if r == 14 else 40, "gain": ocr.POINTS_TABLE_24[r - 1],
             "conf": 0.9, "top": r * 77, "ti": r} for r in range(1, 25)]
    monkeypatch.setattr(ocr, "read_frame", lambda img, lobby: rows)
    job = autocapture._Read24([np.zeros((1080, 1920 - autocapture.KEEP_FROM_X, 3), np.uint8)] * 2)
    job.end()
    assert "missed" not in job.run()


def test_24p_frames_where_points_are_being_added_are_left_out(monkeypatch):
    def row(rank, name, total, gain):
        return {"rank": rank, "name": name, "total": total, "gain": gain, "conf": 0.9, "top": rank * 77, "ti": rank}
    scroll = [row(r, f"P{r}", 10, ocr.POINTS_TABLE_24[r - 1]) for r in range(1, 25)]
    resorting = [row(r, f"P{25 - r}", 50, 3 if r < 4 else 0) for r in range(1, 25)]
    frames = iter([scroll, resorting, resorting, scroll])
    monkeypatch.setattr(ocr, "read_frame", lambda img, lobby: next(frames))
    job = autocapture._Read24([np.zeros((1080, 1920 - autocapture.KEEP_FROM_X, 3), np.uint8)] * 4)
    job.end()
    out = job.run()
    assert "missed" not in out
    assert {p["full_name"] for p in out["players"]} == {f"P{r}" for r in range(1, 25)}


def test_24p_own_row_pinned_at_the_bottom_is_no_tie(monkeypatch):
    def row(rank, top):
        return {"rank": rank, "name": f"P{rank}", "total": 20, "gain": ocr.POINTS_TABLE_24[rank - 1], "conf": 0.9,
                "top": top, "ti": top}
    top = [row(r, r) for r in range(1, 13)] + [row(18, 13)]
    bottom = [row(r, r) for r in range(6, 19)] + [row(18, 14)]
    rest = [row(r, r) for r in range(12, 25)]
    frames = iter([top, bottom, rest, top, bottom, rest])
    monkeypatch.setattr(ocr, "read_frame", lambda img, lobby: next(frames))
    job = autocapture._Read24([np.zeros((1080, 1920 - autocapture.KEEP_FROM_X, 3), np.uint8)] * 6)
    job.end()
    out = job.run()
    assert "missed" not in out and len(out["players"]) == 24


def test_12p_board_with_11_players_is_taken(monkeypatch):
    rows = [{"rank": k + 1, "name": f"P{k}", "total": 30 - k, "gain": 0, "conf": 0.9, "top": 37 + 77 * k, "ti": k}
            for k in range(11)]
    monkeypatch.setattr(ocr, "read_frame", lambda img, lobby, gains=False: rows)
    job = autocapture._Read12()
    job.latest(np.zeros((1080, 1920 - autocapture.KEEP_FROM_X, 3), np.uint8))
    monkeypatch.setattr(autocapture, "READ_EVERY", 0.01)
    out = job.run()
    assert "missed" not in out and len(out["players"]) == 11 and out["tidy"]
