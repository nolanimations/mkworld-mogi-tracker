import pytest

from mogi_tracker.session_classic import Session, TABLE_11P, team_key

TAGS = "ABCDEF"
TABLE_12P = [15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


def names_12p():
    return [f"{t} {n}" for t in TAGS for n in ("one", "two")]


def board(totals: dict):
    return [{"full_name": n, "white_score": t, "green_score": 0} for n, t in totals.items()]


def race(totals: dict, order: list, table=TABLE_12P):
    out = dict(totals)
    for name, pts in zip(order, table):
        out[name] = out.get(name, 0) + pts
    return out


@pytest.fixture
def s():
    return Session(lobby=12, fmt="2v2")


def totals_by_tag(session):
    return {r["tag"]: r["total"] for r in session.standings()}


def test_capture_groups_players_into_teams(s):
    t = race({}, names_12p())
    s.apply_capture(board(t))
    assert totals_by_tag(s) == {"A": 27, "B": 19, "C": 15, "D": 11, "E": 7, "F": 3}
    info = s.race_info()
    assert (info["number"], info["left"], info["delta"]) == (1, 11, 0)
    assert s.suggestions == []


def test_gain_trend_and_gap_after_second_capture(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    assert s.standings()[0]["gain"] is None
    t2 = race(t1, list(reversed(names_12p())))
    s.apply_capture(board(t2))
    rows = {r["tag"]: r for r in s.standings()}
    assert rows["F"]["gain"] == 27 and rows["A"]["gain"] == 3
    assert rows["A"]["trend"] == "same" and rows["A"]["rank"] == 1 and rows["F"]["rank"] == 1   # tied on 30
    assert s.race_info()["number"] == 2


def test_points_missing_is_reported(s):
    t = race({}, names_12p())
    t["F two"] = 0
    s.apply_capture(board(t))
    assert s.race_info()["delta"] == -1


def test_bank_all_and_undo(s):
    s.apply_capture(board(race({}, names_12p())))
    assert s.bank_all()
    assert s.live == {} and s.bank["A"] == 27 and totals_by_tag(s)["A"] == 27
    assert s.undo() == "bank all"
    assert s.bank == {} and s.live["A"] == 27
    assert s.undo() == "capture"
    assert s.standings() == []
    assert s.undo() is None


def test_bank_all_then_new_room_adds_up(s):
    t = race({}, names_12p())
    s.apply_capture(board(t))
    s.bank_all()
    s.apply_capture(board(t))
    assert totals_by_tag(s)["A"] == 54
    assert s.suggestions == []
    assert s.race_info()["number"] == 2


def test_adjust_by_first_character(s):
    s.apply_capture(board(race({}, names_12p())))
    assert s.adjust("b", 10) == {"ok": True, "tag": "B", "points": 10}
    assert totals_by_tag(s)["B"] == 29
    assert s.undo() == "+10 B"
    assert totals_by_tag(s)["B"] == 19


def test_adjust_needs_full_tag_when_first_character_is_shared():
    s = Session(24, "4v4")
    s.bank = {"AB": 10, "AC": 20, "X": 5}
    s.display = {"AB": "Ab", "AC": "AC", "X": "X"}
    r = s.adjust("a", 5)
    assert r["ok"] is False and r["reason"] == "ambiguous" and r["matches"] == ["Ab", "AC"]
    assert s.adjust("ac", 5)["ok"] and s.bank["AC"] == 25
    assert s.adjust("x", 1)["ok"]


def test_exact_tag_wins_over_longer_tags():
    s = Session(24, "4v4")
    s.bank = {"A": 10, "AB": 20}
    assert s.adjust("A", 5)["ok"] and s.bank["A"] == 15


def test_adjust_unknown_tag_needs_confirmation(s):
    r = s.adjust("Zed", 7)
    assert r == {"ok": False, "reason": "unknown", "tag": "Zed"}
    assert s.adjust("Zed", 7, create=True)["ok"]
    assert totals_by_tag(s) == {"Zed": 7}


def test_lookalike_letters_are_one_team():
    assert team_key("l0") == team_key("IO")


def test_clipboard_text(s):
    t = race({}, names_12p())
    s.apply_capture(board(t))
    assert s.clipboard_text() == "A 27 | B 19 | C 15 | D 11 | E 7 | F 3 | @11"
    assert s.clipboard_text(my_tag="c") == "A 27 | B 19 | **C** 15 | D 11 | E 7 | F 3 | @11"
    assert s.clipboard_text(my_tag="c", mark_mine=False).startswith("A 27 | B 19 | C 15")


def test_clipboard_final_race_is_at_zero(s):
    t = {}
    for _ in range(12):
        t = race(t, names_12p())
    s.apply_capture(board(t))
    assert s.race_info()["number"] == 12
    assert s.clipboard_text().endswith(" | @0")
    assert Session().clipboard_text() == ""


def test_clipboard_keeps_full_tag_when_first_character_collides():
    s = Session(24, "4v4")
    s.bank = {"AB": 30, "AC": 20, "X1": 10, "Q": 5}
    s.display = {"AB": "Ab", "AC": "AC", "X1": "X1", "Q": "Queen"}
    assert s.clipboard_text() == "AB 30 | AC 20 | X1 10 | Q 5 | @11"


def test_rejoin_at_zero_is_offered_once(s):
    t1 = race(race({}, names_12p()), names_12p())
    s.apply_capture(board(t1))
    before = totals_by_tag(s)["A"]
    t2 = race(t1, names_12p())
    lost = t1["A two"]
    t2["A two"] = 12          # came back at 0 and finished 2nd
    s.apply_capture(board(t2))
    assert [x["id"] for x in s.suggestions] == ["pts:atwo"]
    assert f"Bank {lost} for A" == s.suggestions[0]["button"]
    s.apply_suggestion("pts:atwo")
    assert totals_by_tag(s)["A"] == before + 15 + 12
    assert s.suggestions == []
    assert s.race_info()["delta"] == 0
    s.apply_capture(board(race(t2, names_12p())))
    assert s.suggestions == []


def test_suggestion_can_be_dismissed_and_undone(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    t2 = dict(t1)
    t2["B one"] = 1
    s.apply_capture(board(t2))
    sid = s.suggestions[0]["id"]
    s.apply_suggestion(sid)
    assert s.bank["B"] == 10
    s.undo()
    assert s.bank == {} and [x["id"] for x in s.suggestions] == [sid]
    s.dismiss_suggestion(sid)
    assert s.suggestions == []


def test_new_room_without_banking_is_one_suggestion(s):
    t1 = race(race({}, names_12p()), names_12p())
    s.apply_capture(board(t1))
    old = totals_by_tag(s)
    t2 = race({}, list(reversed(names_12p())))
    s.apply_capture(board(t2))
    assert [x["id"] for x in s.suggestions] == ["room"]
    s.apply_suggestion("room")
    new = totals_by_tag(s)
    assert new["A"] == old["A"] + 3 and new["F"] == old["F"] + 27
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 246, "delta": 0}


def eleven_player_race(totals, absent, keep_row):
    present = [n for n in names_12p() if n != absent]
    out = race(totals, present, TABLE_11P)
    if not keep_row:
        del out[absent]
    return out, present


@pytest.mark.parametrize("keep_row", [True, False])
def test_eleven_player_race_offers_the_correction(s, keep_row):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    t2, present = eleven_player_race(t1, "C two", keep_row)
    s.apply_capture(board(t2), tidy_board=True)
    ids = [x["id"] for x in s.suggestions]
    assert "comp11" in ids
    assert ("pts:ctwo" in ids) == (not keep_row)
    assert s.race_info()["delta"] != 0
    for sid in ids:
        s.apply_suggestion(sid)
    assert s.race_info() == {"number": 2, "of": 12, "left": 10, "grand": 164, "delta": 0}
    assert s.bank["A"] == 5 and s.bank["C"] == (2 if keep_row else 2 + t1["C two"])


def test_second_eleven_player_race_in_a_row(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    t2, _ = eleven_player_race(t1, "C two", keep_row=False)
    s.apply_capture(board(t2))
    for sid in [x["id"] for x in s.suggestions]:
        s.apply_suggestion(sid)
    t3 = race(t2, [n for n in names_12p() if n != "C two"], TABLE_11P)
    s.apply_capture(board(t3))
    assert [x["id"] for x in s.suggestions] == ["comp11"]
    s.apply_suggestion("comp11")
    assert s.race_info()["delta"] == 0 and s.race_info()["number"] == 3


def test_full_race_is_never_mistaken_for_eleven_players(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    s.apply_capture(board(race(t1, names_12p())))
    assert s.suggestions == []


def test_skipped_capture_gives_no_correction(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    t2, _ = eleven_player_race(t1, "C two", keep_row=True)
    t3 = race(t2, names_12p())
    s.apply_capture(board(t3))
    assert s.suggestions == []


def test_hole_in_the_board_is_a_misread_not_a_disconnect(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    t2 = race(t1, names_12p())
    del t2["B one"]
    s.apply_capture(board(t2), tidy_board=False)
    assert s.suggestions == []


def test_partial_24p_read_suggests_nothing():
    s = Session(24, "4v4")
    names = [f"{t} p{i}" for t in "ABCDEF" for i in range(4)]
    t1 = {n: 5 + i for i, n in enumerate(names)}
    s.apply_capture(board(t1))
    t2 = {n: v + 3 for n, v in list(t1.items())[:20]}
    s.apply_capture(board(t2))
    assert s.suggestions == []


def test_same_name_twice_is_left_alone(s):
    names = names_12p()
    t1 = [(n, 20) for n in names[:10]] + [("m", 30), ("m", 4)]
    as_board = lambda rows: [{"full_name": n, "white_score": t, "green_score": 0} for n, t in rows]
    s.apply_capture(as_board(t1))
    t2 = [(n, 25) for n in names[:10]] + [("m", 9), ("m", 31)]
    s.apply_capture(as_board(t2))
    assert s.suggestions == []


def test_slightly_different_reading_of_a_name_is_the_same_player(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    t2 = race(t1, names_12p())
    t2["A onee"] = t2.pop("A one")
    s.apply_capture(board(t2))
    assert s.suggestions == []


def test_format_change_regroups_without_new_capture():
    s = Session(12, "2v2")
    names = [f"{t}{u} x{i}" for t in "AB" for u in "12" for i in range(3)]
    s.apply_capture(board({n: 10 for n in names}))
    s.set_format("3v3")
    assert sorted(r["total"] for r in s.standings()) == [30, 30, 30, 30]
    s.set_format("6v6")
    assert sorted(r["total"] for r in s.standings()) == [60, 60]


def test_my_tag_marks_the_row(s):
    s.apply_capture(board(race({}, names_12p())))
    assert [r["tag"] for r in s.standings(my_tag="d") if r["mine"]] == ["D"]
    assert not any(r["mine"] for r in s.standings(my_tag=""))


def test_reset_can_be_undone(s):
    s.apply_capture(board(race({}, names_12p())))
    s.reset()
    assert s.standings() == []
    assert s.undo() == "new mogi"
    assert len(s.standings()) == 6


def test_short_labels_follow_the_clipboard_rule():
    s = Session(24, "4v4")
    s.bank = {"AB": 30, "AC": 20, "X1": 10, "Q": 5}
    s.display = {"AB": "Ab", "AC": "AC", "X1": "X1", "Q": "Queen"}
    assert [r["short"] for r in s.standings()] == ["AB", "AC", "X1", "Q"]


def test_greek_tags_keep_their_own_letter():
    from mogi_tracker.session_classic import label_of, team_key
    from mogi_tracker.teams import upper_latin
    assert label_of("μ") == "μ" and team_key("μ") == "μ"       # the capital of μ is M, could be confusing
    assert label_of("ab") == "AB" and upper_latin("é★x") == "É★X"
    assert label_of("ねこ") == "ねこ"
    s = Session(24, "4v4")
    s.apply_capture([{"full_name": n, "white_score": 10, "green_score": 0}
                     for n in ("μ 1st", "μ-Bran", "μ2nd", "μ Lia", "M a", "M b", "M c", "M d")] +
                    [{"full_name": f"{t} {k}", "white_score": 5, "green_score": 0} for t in "ABCD" for k in range(4)])
    tags = {t["tag"] for t in s.standings()}
    assert "μ" in tags and "M" in tags


# test from a 6v6 I did
RACE10 = {"V$ pqzt": 93, "AX★Morven": 88, "AX": 85, "AX★4Taks": 78, "AX Dunn": 78, "V$ rolo": 75, "SX kai_pip": 75,
          "V$ fenx'": 59, "V$ Tirane": 55, "V$ Paz": 53, "V$ Rowlan": 47, "SX☆XORBEAS": 34}
RACE11 = {"AX★Morven": 97, "V$ pqzt": 94, "AX": 89, "AX Dunn": 88, "V$ rolo": 87, "AX★4Taks": 84, "SX kai_pip": 78,
          "V$ Paz": 58, "V$ Tirane": 57, "V$ Rowlan": 54, "SX☆XORBEAS": 42}


def _board(totals):
    return [{"full_name": n, "white_score": t, "green_score": 0} for n, t in totals.items()]


def test_11_player_race_is_spotted_even_with_a_misread_name():
    s = Session(12, "6v6")
    s.apply_capture(_board(RACE10))
    misread = {("VSPa2" if n == "V$ Paz" else "SX☆ORBES" if n == "SX☆XORBEAS" else n): t for n, t in RACE11.items()}
    s.apply_capture(_board(misread))
    kinds = {x["kind"] for x in s.suggestions}
    assert kinds == {"left", "comp11"}
    comp = next(x for x in s.suggestions if x["kind"] == "comp11")
    assert sum(a["points"] for a in comp["adds"]) == 15
    assert "fenx" in next(x for x in s.suggestions if x["kind"] == "left")["text"]
