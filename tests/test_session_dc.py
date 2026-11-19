from mogi_tracker.ocr import POINTS_TABLE_24
from mogi_tracker.session import Session

NAMES_24 = [f"{t} p{i}" for t in "ABCDEF" for i in range(4)]
TABLE_12P = [15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
NAMES_12 = [f"{t} {n}" for t in "ABCDEF" for n in ("one", "two")]


def board(totals):
    return [{"full_name": n, "white_score": t, "green_score": 0} for n, t in totals.items()]


def race(totals, order, table):
    out = dict(totals)
    for name, pts in zip(order, table):
        out[name] = out.get(name, 0) + pts
    return out


def place_of(s, name):
    return next(m["total"] for r in s.standings() for m in r["members"] if m["name"] == name)


def team_total(s, tag):
    return next(r["total"] for r in s.standings() if r["tag"] == tag)


def test_24p_bot_from_0_then_player_back():
    s = Session(24, "4v4")
    t1 = race({}, NAMES_24, POINTS_TABLE_24)
    s.apply_capture(board(t1))
    had = t1["B p1"]
    others = [n for n in NAMES_24 if n != "B p1"]
    t2 = race({n: v for n, v in t1.items() if n != "B p1"}, others[:20] + ["Swoop"] + others[20:], POINTS_TABLE_24)
    s.apply_capture(board(t2))
    assert s.race_info() == {"number": 2, "of": 12, "left": 10, "grand": 288, "delta": 0}
    t3 = race({n: v for n, v in t2.items() if n != "Swoop"}, ["B p1"] + others, POINTS_TABLE_24)
    s.apply_capture(board(t3))
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 432, "delta": 0}
    assert place_of(s, "B p1") == had + t2["Swoop"] + 15
    assert not any(x["button"] for x in s.suggestions)


def test_24p_bot_that_kept_the_points_then_player_back():
    s = Session(24, "4v4")
    t1 = race({}, NAMES_24, POINTS_TABLE_24)
    s.apply_capture(board(t1))
    others = [n for n in NAMES_24 if n != "C p0"]
    t2 = race({("Swoop" if n == "C p0" else n): v for n, v in t1.items()}, others + ["Swoop"], POINTS_TABLE_24)
    s.apply_capture(board(t2))
    assert s.race_info()["grand"] == 288 and s.race_info()["delta"] == 0
    kept = t2["Swoop"]
    t3 = race({n: v for n, v in t2.items() if n != "Swoop"}, ["C p0"] + others, POINTS_TABLE_24)
    s.apply_capture(board(t3))
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 432, "delta": 0}
    assert place_of(s, "C p0") == kept + 15


def test_24p_partial_read_with_a_bot_falls_back_quietly():
    """manual 24p captures can miss rows: the race can't be checked, don't bank twice"""
    s = Session(24, "4v4")
    t1 = race({}, NAMES_24, POINTS_TABLE_24)
    s.apply_capture(board(t1))
    others = [n for n in NAMES_24 if n != "B p1"]
    t2 = race({n: v for n, v in t1.items() if n != "B p1"}, others[:20] + ["Swoop"] + others[20:], POINTS_TABLE_24)
    partial = {n: v for n, v in list(t2.items())[:18]}
    partial["Swoop"] = t2["Swoop"]
    s.apply_capture(board(partial))
    assert s.race_info()["grand"] <= 288


def test_two_bots_on_different_teams_in_24p():
    """2 players from 2 teams both DC, two bots from 0 take their places in the same race. The room adds up but which bot
    raced for whom can't be known from names"""
    s = Session(24, "4v4")
    t1 = race({}, NAMES_24, POINTS_TABLE_24)
    s.apply_capture(board(t1))
    gone = {"A p0", "F p3"}
    others = [n for n in NAMES_24 if n not in gone]
    t2 = race({n: v for n, v in t1.items() if n not in gone}, others[:10] + ["Swoop"] + others[10:] + ["Kamek"],
              POINTS_TABLE_24)
    s.apply_capture(board(t2))
    assert s.race_info() == {"number": 2, "of": 12, "left": 10, "grand": 288, "delta": 0}
    notes = [x["text"] for x in s.suggestions if x["kind"] == "note"]
    assert len(notes) == 2 and not any(x["button"] for x in s.suggestions)


def test_three_rejoins_in_12p_get_a_card_each():
    s = Session(12, "2v2")
    t1 = race(race({}, NAMES_12, TABLE_12P), NAMES_12, TABLE_12P)
    s.apply_capture(board(t1))
    back = {n: TABLE_12P[NAMES_12.index(n)] for n in ("A one", "C two", "F one")}
    t2 = race(t1, NAMES_12, TABLE_12P)
    t2.update(back)
    s.apply_capture(board(t2))
    cards = [x for x in s.suggestions if x["kind"] == "rejoin"]
    assert sorted(x["button"] for x in cards) == sorted(f"Bank {t1[n]} for {n[0]}" for n in back)
    for x in cards:
        s.apply_suggestion(x["id"])
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 246, "delta": 0}


def test_two_rejoins_in_24p_get_a_card_each():
    s = Session(24, "4v4")
    t1 = race(race({}, NAMES_24, POINTS_TABLE_24), NAMES_24, POINTS_TABLE_24)
    s.apply_capture(board(t1))
    t2 = race(t1, NAMES_24, POINTS_TABLE_24)
    for n in ("B p2", "E p0"):
        t2[n] = POINTS_TABLE_24[NAMES_24.index(n)]
    s.apply_capture(board(t2))
    cards = [x for x in s.suggestions if x["kind"] == "rejoin"]
    assert len(cards) == 2
    for x in cards:
        s.apply_suggestion(x["id"])
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 432, "delta": 0}


def test_two_rejoins_without_a_drop_are_not_pinned_on_someone_else():
    """B p2 and E p0 rejoined and happen to have their old totals again"""
    s = Session(24, "4v4")
    t1 = race({}, NAMES_24, POINTS_TABLE_24)
    s.apply_capture(board(t1))
    t2 = race(t1, NAMES_24, POINTS_TABLE_24)
    for n in ("B p2", "E p0"):
        t2[n] = POINTS_TABLE_24[NAMES_24.index(n)]
    s.apply_capture(board(t2))
    assert not [x for x in s.suggestions if x["kind"] == "rejoin"]
    assert s.race_info()["delta"] == -12


def test_24p_player_not_read_yet_does_not_take_a_missing_players_place():
    # two partial reads: the first misses "E Pazzy", the second misses "C Koopa" while "E Pazzy" shows up for the
    # first time. Pazzy is not a stand-in for Koopa, just a player the app had not seen yet
    names = ["A Mario", "A Luigi", "A Peach", "A Daisy", "B Yoshi", "B Wario", "B Toad", "B Rosa", "C Koopa", "C Birdo",
             "C Pauline", "C Cow", "D Dunn", "D rolo", "D pqzt", "D Morven", "E Pazzy", "E Tirane", "E Rowlan",
             "E Taks", "F Nolanima", "F Vela", "F Xorbeas", "F kai_pip"]
    s = Session(24, "4v4")
    t1 = race({}, names, POINTS_TABLE_24)
    s.apply_capture(board({n: v for n, v in t1.items() if n != "E Pazzy"}), tidy_board=False)
    t2 = race(t1, names[::-1], POINTS_TABLE_24)
    s.apply_capture(board({n: v for n, v in t2.items() if n != "C Koopa"}), tidy_board=False)
    assert place_of(s, "E Pazzy") == t2["E Pazzy"]
    t3 = race(t2, names, POINTS_TABLE_24)
    s.apply_capture(board(t3))
    assert [x["kind"] for x in s.suggestions if x["kind"] != "note"] == []
    assert place_of(s, "C Koopa") == t3["C Koopa"] and place_of(s, "E Pazzy") == t3["E Pazzy"]
    assert s.race_info()["delta"] == 0


def test_24p_bot_that_stays_several_races_is_not_back():
    """a stand-in read three times in a row is still the stand-in, not a rejoin that banks its points again"""
    s = Session(24, "4v4")
    t = race({}, NAMES_24, POINTS_TABLE_24)
    s.apply_capture(board(t))
    others = [n for n in NAMES_24 if n != "B p1"]
    order = others[:20] + ["Swoop"] + others[20:]
    t = {n: v for n, v in t.items() if n != "B p1"}
    for r in range(2, 6):
        t = race(t, order, POINTS_TABLE_24)
        s.apply_capture(board(t))
        assert s.race_info() == {"number": r, "of": 12, "left": 12 - r, "grand": 144 * r, "delta": 0}
        assert not any("is back" in x["text"] for x in s.suggestions)
