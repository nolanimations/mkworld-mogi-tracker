import threading

import pytest

from mogi_tracker import settings
from mogi_tracker.controller import Controller
from mogi_tracker.session import Session, TABLE_11P

TABLE_12P = [15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
NAMES = [f"{t} {n}" for t in "ABCDEF" for n in ("one", "two")]


def board(totals):
    return [{"full_name": n, "white_score": t, "green_score": 0} for n, t in totals.items()]


def race(totals, order, table=TABLE_12P):
    out = dict(totals)
    for name, pts in zip(order, table):
        out[name] = out.get(name, 0) + pts
    return out


def without(name):
    return [n for n in NAMES if n != name]


def capture(s, totals):
    s.apply_capture(board(totals))
    return s.accept_corrections()


def questions(s):
    return [x["button"] for x in s.suggestions if x["button"]]


def notes(s):
    return [x["text"] for x in s.suggestions if not x["button"]]


def total(s, tag):
    return next(r["total"] for r in s.standings() if r["tag"] == tag)


@pytest.fixture
def s():
    s = Session(12, "2v2")
    t = race({}, NAMES)
    assert capture(s, t) == []
    s.t2 = race(t, NAMES)
    assert capture(s, s.t2) == []
    return s


def rejoined(s, order=None):
    return race({**s.t2, "C one": 0}, order or without("C one") + ["C one"])


def test_rejoin_is_banked_with_a_note(s):
    done = capture(s, rejoined(s))
    assert [x["kind"] for x in done] == ["rejoin"]
    assert questions(s) == [] and notes(s) == ["C one DC'd and rejoined, added 16 points to C"]
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 246, "delta": 0}
    assert total(s, "C") == rejoined(s)["C one"] + rejoined(s)["C two"] + 16


def test_bot_points_of_a_missed_race_are_banked_too(s):
    t3 = race(s.t2, without("C one")[:4] + ["C one"] + without("C one")[4:])        # bot got 5th
    t4 = race({**t3, "C one": 0}, without("C one") + ["C one"])
    assert len(capture(s, t4)) == 1
    assert notes(s) == ["C one DC'd and rejoined, added 24 points to C: 16 from before and 8 from a bot in a race that "
                        "wasn't captured"]
    assert s.race_info()["delta"] == 0 and s.race_info()["number"] == 4


def test_missed_11_player_race_is_still_asked(s):
    t3 = race(s.t2, without("C one"), TABLE_11P)
    t4 = race({**t3, "C one": 0}, without("C one") + ["C one"])
    assert capture(s, t4) == []
    assert questions(s) == ["Bank 16 for C"]


def test_captured_11_player_race_gets_the_correction(s):
    t3 = race({n: s.t2[n] for n in without("C one")}, without("C one"), TABLE_11P)
    assert [x["kind"] for x in capture(s, t3)] == ["comp11"]
    assert questions(s) == [] and s.race_info()["grand"] == 246
    assert any(n.startswith("11 player race, added 15 points: +3 for 1st (A one)") for n in notes(s))
    assert any("left the room" in n for n in notes(s))           # other notes stay


def test_11_player_race_or_a_rejoin_that_won(s):
    s = Session(12, "2v2")
    t = race({}, NAMES)
    capture(s, t)
    assert t["A one"] == 15
    t2 = race({**t, "A one": 0}, ["A one"] + without("A one"))
    assert t2["A one"] == 15
    assert capture(s, t2) == []
    assert questions(s) == ["Add 15 points"]


def test_reopened_room_is_banked(s):
    assert [x["kind"] for x in capture(s, race({}, NAMES))] == ["room"]
    assert notes(s) == ["Looks like a reopen, banked the old room's 164 points"]
    assert s.race_info()["number"] == 3 and s.race_info()["delta"] == 0 and questions(s) == []


def test_misread_total_is_asked_not_banked(s):
    t3 = race(s.t2, NAMES)
    assert capture(s, {**t3, "B one": 3}) == []                   # 30 read as 3
    assert questions(s) == ["Bank 20 for B"]
    assert capture(s, race(t3, NAMES)) == []                      # read right again
    assert total(s, "B") == 4 * 10 + 4 * 9


def test_82_points_dont_make_a_misread_add_up():
    s = Session(12, "2v2")
    t = dict.fromkeys(NAMES, 0)
    for _ in range(6):
        t = race(t, NAMES)
    t = {**t, "A one": 82, "A two": t["A two"] + 8}                # 492 points
    capture(s, t)
    t2 = race(t, NAMES)
    assert capture(s, {**t2, "A one": 80, "A two": t2["A two"] + 17}) == []
    assert questions(s) == ["Bank 82 for A"]


def test_a_total_read_as_0_is_no_rejoin_with_a_bots_points(s):
    t4 = race(race(s.t2, NAMES), NAMES)                            # race 3 isn't captured
    assert capture(s, {**t4, "F one": 0}) == []
    assert questions(s) == [f"Bank {s.t2['F one']} for F"]


def test_offer_left_open_still_works_after_bank_all_and_after_a_reopen(s):
    t3 = rejoined(s)
    s.apply_capture(board(t3))
    s.bank_all()
    s.apply_suggestion(next(x["id"] for x in s.suggestions if x["kind"] == "rejoin"))
    assert total(s, "C") == t3["C one"] + t3["C two"] + 16


def test_guess_from_the_missing_points_is_asked():
    s = Session(12, "2v2")
    t = race({}, NAMES)
    capture(s, t)
    t2 = race({n: v for n, v in t.items() if n != "A two"}, ["A two"] + without("A two"))
    assert capture(s, t2) == []
    assert questions(s) == ["Bank 12 for A"] and "only add up" in s.suggestions[0]["text"]


def test_two_rejoins_in_one_race_are_checked_together(s):
    t3 = race({**s.t2, "C one": 0, "D one": 0}, [n for n in NAMES if n not in ("C one", "D one")] + ["C one", "D one"])
    assert len(capture(s, t3)) == 2
    assert s.race_info()["delta"] == 0 and len(notes(s)) == 2
    assert s.undo() == "2 corrections"
    assert questions(s) == ["Bank 16 for C", "Bank 12 for D"]


def test_undo_takes_back_only_the_correction_and_asks_again(s):
    capture(s, rejoined(s))
    assert s.undo_label() == "bank 16 for C"
    s.undo()
    assert questions(s) == ["Bank 16 for C"] and notes(s) == []
    assert s.race_info()["grand"] == 246 - 16
    assert s.undo_label() == "capture"


def test_recapture_after_undo_asks_for_that_race_only(s):
    t3 = rejoined(s)
    capture(s, t3)
    s.undo(), s.undo()
    assert s.race_info()["number"] == 2
    assert capture(s, t3) == []
    assert questions(s) == ["Bank 16 for C"]
    s.dismiss_suggestion(s.suggestions[0]["id"])
    t4 = race({**t3, "E one": 0}, without("E one") + ["E one"])
    assert [x["button"] for x in capture(s, t4)] == [f"Bank {t3['E one']} for E"]


def test_recapture_that_reads_something_else_is_accepted_again(s):
    capture(s, rejoined(s))
    s.undo(), s.undo()
    other = rejoined(s, ["C one"] + without("C one"))
    assert len(capture(s, other)) == 1


def test_undoing_just_the_capture_is_no_objection(s):
    t3 = rejoined(s)
    s.apply_capture(board(t3))
    s.undo()
    assert len(capture(s, t3)) == 1


def test_new_mogi_forgets_what_was_undone(s):
    capture(s, rejoined(s))
    s.undo()
    s.reset()
    capture(s, race({}, NAMES)), capture(s, s.t2)
    assert len(capture(s, rejoined(s))) == 1


def test_capturing_the_same_board_again_does_nothing(s):
    capture(s, rejoined(s))
    before = s.grand_total()
    assert capture(s, rejoined(s)) == [] and s.grand_total() == before


@pytest.mark.parametrize("missed, accepted", [(0, 1), (1, 1), (3, 0)])
def test_24p_rejoin(missed, accepted):
    table = [15, 12, 10, 9, 9, 8, 8, 7, 7, 6, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 1]
    names = [f"{t} {n}" for t in "ABCDEF" for n in ("ann", "bob", "cid", "dot")]
    s = Session(24, "4v4")
    t = race(race({}, names, table), names, table)
    capture(s, t)
    had, others = t["B bob"], [n for n in names if n != "B bob"]
    for _ in range(missed):
        t = race(t, names, table)
    assert len(capture(s, race({**t, "B bob": 0}, others + ["B bob"], table))) == accepted
    assert questions(s) == ([] if accepted else [f"Bank {had + 8 * missed} for B"])
    assert accepted == 0 or s.race_info()["delta"] == 0


@pytest.mark.parametrize("on", [True, False])
def test_controller_accepts_before_it_copies(s, on, monkeypatch):
    c = Controller.__new__(Controller)
    c.session, c.settings, c.lock = s, {**settings.DEFAULTS, "auto_accept": on, "auto_copy": True}, threading.RLock()
    copied = []
    monkeypatch.setattr(c, "_copy_scores", lambda: copied.append(s.clipboard_text()) or True, raising=False)
    monkeypatch.setattr(c, "say", lambda *a: None, raising=False)
    c._apply(board(rejoined(s)), 12, True)
    assert questions(s) == ([] if on else ["Bank 16 for C"])
    assert copied[0].startswith("A 81") and (f"C {total(s, 'C')}" in copied[0])
    assert settings.DEFAULTS["auto_accept"] is False
