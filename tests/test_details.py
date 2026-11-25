import pytest

from mogi_tracker import ocr
from mogi_tracker.session import Session, TABLE_11P, TABLE_12P, TABLE_24P

NAMES = [f"{t} {n}" for t in "ABCDEF" for n in ("one", "two")]
NAMES_24 = [f"{t} {n}" for t in "ABCDEF" for n in ("ann", "bob", "cid", "dot")]


def board(totals, finish={}):
    return [{"full_name": n, "white_score": t, "green_score": 0, "finish": finish.get(n)} for n, t in totals.items()]


def race(totals, order, table=TABLE_12P):
    out = dict(totals)
    for name, pts in zip(order, table):
        out[name] = out.get(name, 0) + pts
    return out


def without(name):
    return [n for n in NAMES if n != name]


def members(s):
    return {m["name"]: m for r in s.standings() for m in r["members"]}


def finishes(s):
    return {n: m["last"] and (m["last"]["from"] if m["last"]["from"] == m["last"]["to"] else
                              (m["last"]["from"], m["last"]["to"])) for n, m in members(s).items()}


def placed(order):
    return {n: i + 1 for i, n in enumerate(order)}


@pytest.fixture
def s():
    s = Session(12, "2v2")
    s.t1 = race({}, NAMES)
    s.apply_capture(board(s.t1))
    s.t2 = race(s.t1, NAMES[::-1])
    return s


def test_positions_of_the_last_race_and_ranks_in_the_mogi(s):
    assert finishes(s) == placed(NAMES)
    order = NAMES[6:] + NAMES[:6]
    t2 = race(s.t1, order)
    s.apply_capture(board(t2))
    assert finishes(s) == placed(order)
    assert members(s)["D one"]["last"] == {"from": 1, "to": 1, "points": 15}
    ranks = {n: 1 + sum(o > t for o in t2.values()) for n, t in t2.items()}
    assert {n: m["rank"] for n, m in members(s).items()} == ranks
    assert {n: m["mogi"] for n, m in members(s).items()} == t2


def test_missed_race_has_no_positions(s):
    s.apply_capture(board(race(s.t2, NAMES)))
    assert set(finishes(s).values()) == {None}
    s.apply_capture(board(race(race(s.t2, NAMES), NAMES[::-1])))
    assert finishes(s) == placed(NAMES[::-1])


def test_started_mid_mogi():
    s = Session(12, "2v2")
    t = race(race(race({}, NAMES), NAMES[::-1]), NAMES)
    s.apply_capture(board(t))
    assert set(finishes(s).values()) == {None}
    assert members(s)["A one"]["rank"] == 1


def test_11_player_race(s):
    order = without("C one")
    t2 = race({n: s.t1[n] for n in order}, order, TABLE_11P)
    s.apply_capture(board(t2))
    assert finishes(s) == {**placed(order), "C one": None}
    s.apply_suggestion("comp11")
    assert members(s)["A one"]["mogi"] == t2["A one"] + 3
    s.apply_capture(board(race({**t2, "C one": 0}, order + ["C one"])))          # rejoined
    assert finishes(s) == placed(order + ["C one"])


def test_absent_player_that_stays_on_the_board_in_an_11_player_race(s):
    order = without("C one")
    s.apply_capture(board(race(s.t1, order, TABLE_11P)))
    assert finishes(s) == {**placed(order), "C one": None}


def test_10_player_race_gives_no_positions(s):
    order = NAMES[:10]
    s.apply_capture(board(race({n: s.t1[n] for n in order}, order, TABLE_11P)))
    assert set(finishes(s).values()) == {None}


def test_rejoin_with_a_lower_total_and_a_guessed_one(s):
    order = without("A one") + ["A one"]
    s.apply_capture(board(race({**s.t1, "A one": 0}, order)))
    assert finishes(s) == placed(order)
    s = Session(12, "2v2")
    t = race({}, NAMES)
    s.apply_capture(board(t))
    order = ["F two"] + without("F two")                                        # had 1, now 15
    s.apply_capture(board(race({**t, "F two": 0}, order)))
    assert finishes(s) == {**placed(order), "F two": None}


def test_bot_for_a_player(s):
    order = without("B one")[:5] + ["Swoop"] + without("B one")[5:]
    s.apply_capture(board(race({n: s.t1[n] for n in without("B one")}, order)))
    assert finishes(s) == placed(order)
    assert members(s)["Swoop"]["mogi"] == s.t1["B one"] + 7


def test_one_misread_total_doesnt_hide_the_others(s):
    t = {**s.t2, "A two": s.t2["A two"] + 30}
    s.apply_capture(board(t))
    assert finishes(s) == {**placed(NAMES[::-1]), "A two": None}


def test_two_players_with_the_same_points_have_no_position(s):
    s.apply_capture(board({**s.t2, "A two": s.t2["A two"] + 1}))                   # 11th and 10th both gained 3
    assert finishes(s) == {**placed(NAMES[::-1]), "A two": None, "B one": None}


def test_capturing_the_same_race_again_keeps_the_positions(s):
    s.apply_capture(board(s.t2))
    s.apply_capture(board(s.t2))
    assert finishes(s) == placed(NAMES[::-1])
    t3 = race(s.t2, NAMES)
    s.apply_capture(board({**t3, "B one": 99}))                                   # misread, then read right
    assert finishes(s)["B one"] is None
    s.apply_capture(board(t3))
    assert finishes(s) == placed(NAMES)


def test_undo_goes_back_to_the_race_before(s):
    s.apply_capture(board(s.t2))
    s.undo()
    assert finishes(s) == placed(NAMES)


@pytest.mark.parametrize("by", ["bank all", "suggestion"])
def test_reopen_keeps_the_players_points(s, by):
    s.apply_capture(board(s.t2))
    if by == "bank all":
        s.bank_all()
    s.apply_capture(board(race({}, NAMES)))
    if by == "suggestion":
        assert members(s)["A one"]["mogi"] == 15
        s.apply_suggestion("room")
    assert finishes(s) == placed(NAMES)
    got = members(s)
    assert {n: m["mogi"] for n, m in got.items()} == race(s.t2, NAMES)
    assert got["A one"]["total"] == 15
    assert got["A one"]["rank"] == 1 + sum(m["mogi"] > got["A one"]["mogi"] for m in got.values())
    s.bank_all()                                                                   # second reopen
    s.apply_capture(board(race({}, NAMES[::-1])))
    assert {n: m["mogi"] for n, m in members(s).items()} == race(race(s.t2, NAMES), NAMES[::-1])


def test_two_reopens_taken_from_the_question(s):
    s.apply_capture(board(s.t2))
    total = s.t2
    for order in (NAMES[::-1], NAMES[3:] + NAMES[:3]):
        room = race({}, order)
        s.apply_capture(board(room))
        s.apply_suggestion("room")
        s.apply_capture(board(race(room, NAMES)))
        total = race(race(total, order), NAMES)
    assert {n: m["mogi"] for n, m in members(s).items()} == total


def test_reopen_after_1_race_has_positions(s):
    s.apply_capture(board(race({}, NAMES[::-1])))                                  # F two had 1, now 15
    assert finishes(s) == placed(NAMES[::-1])


def test_after_a_reopen_a_new_player_starts_at_0(s):
    s.apply_capture(board(s.t2))
    s.bank_all()
    names = without("E two") + ["E zzqx"]
    s.apply_capture(board(race({}, names)))
    assert members(s)["E zzqx"]["mogi"] == 1
    assert members(s)["E one"]["mogi"] == s.t2["E one"] + race({}, names)["E one"]


def test_undo_and_new_mogi_forget_a_banked_room(s):
    s.bank_all()
    s.undo()
    assert members(s)["A one"]["mogi"] == 15 and s.old_room == []
    s.bank_all()
    s.reset()
    s.apply_capture(board(s.t1))
    assert members(s)["A one"]["mogi"] == 15


def test_24p_board_in_race_order_gives_exact_positions():
    s = Session(24, "4v4")
    t = race({}, NAMES_24, TABLE_24P)
    s.apply_capture(board(t, placed(NAMES_24)))
    assert finishes(s) == placed(NAMES_24)
    t = race(race(t, NAMES_24, TABLE_24P), NAMES_24[::-1], TABLE_24P)               # also after a missed race
    s.apply_capture(board(t, placed(NAMES_24[::-1])))
    assert finishes(s) == placed(NAMES_24[::-1])
    s.apply_capture(board(t))                                                      # again, but the board has re-sorted
    assert finishes(s) == placed(NAMES_24[::-1])


def test_24p_board_that_was_captured_late_gives_a_range_for_equal_points():
    s = Session(24, "4v4")
    t = race({}, NAMES_24, TABLE_24P)
    s.apply_capture(board(t))
    got = finishes(s)
    assert [got[n] for n in NAMES_24[:6]] == [1, 2, 3, (4, 5), (4, 5), (6, 7)] and got[NAMES_24[-1]] == 24


def test_24p_player_that_wasnt_read_has_no_position():
    s = Session(24, "4v4")
    t = race({}, NAMES_24, TABLE_24P)
    s.apply_capture(board(t))
    t = race(t, NAMES_24[::-1], TABLE_24P)
    s.apply_capture(board({n: v for n, v in t.items() if n != "C bob"}))
    assert finishes(s)["C bob"] is None and finishes(s)["F dot"] == 1
    t = race(t, NAMES_24, TABLE_24P)
    s.apply_capture(board(t))
    assert finishes(s)["C bob"] is None and finishes(s)["A ann"] == 1


def test_24p_player_that_wasnt_read_doesnt_count_for_the_next_race():
    s = Session(24, "4v4")
    t = race({}, NAMES_24, TABLE_24P)
    s.apply_capture(board(t))
    t = race(t, NAMES_24, TABLE_24P)
    s.apply_capture(board({n: v for n, v in t.items() if n != "F dot"}))            # 1 point
    t = race(t, NAMES_24, TABLE_24P)
    s.apply_capture(board(t))                                                      # 1 more, 2 since it was last read
    assert finishes(s)["F dot"] is None and finishes(s)["F cid"] == (22, 23)


def merged(gains, total=50):
    return [{"rank": r, "name": f"P{r}", "gain": g, "total": total} for r, g in enumerate(gains, 1)]


def test_ocr_takes_the_rank_as_the_position_only_in_race_order():
    assert [p["finish"] for p in ocr.to_players(merged(TABLE_24P))] == list(range(1, 25))
    assert {p["finish"] for p in ocr.to_players(merged([0] * 24))} == {None}
    assert {p["finish"] for p in ocr.to_players(merged(TABLE_24P[::-1]))} == {None}      # re-sorted by total
    one_off = merged(TABLE_24P)
    one_off[4]["gain"] = 0
    assert ocr.to_players(one_off)[4]["finish"] == 5
    twice = merged(TABLE_24P)
    twice[4]["rank"] = 4
    assert [p["finish"] for p in ocr.to_players(twice)][2:6] == [3, None, None, 6]
    assert ocr.to_players([]) == []


def test_positions_survive_a_format_change(s):
    s.apply_capture(board(s.t2))
    s.set_format("FFA")
    assert finishes(s) == placed(NAMES[::-1])


def test_snapshot_is_json(s):
    import json
    assert json.loads(json.dumps(s.snapshot()))["teams"][0]["members"][0]["last"]["points"] == 15
