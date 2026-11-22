import pytest

from mogi_tracker.session import Session, TABLE_11P, team_key

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
    assert s.clipboard_text() == "AB 30 | AC 20 | X 10 | Q 5 | @11"


def test_rejoin_at_zero_is_offered_once(s):
    t1 = race(race({}, names_12p()), names_12p())
    s.apply_capture(board(t1))
    before = totals_by_tag(s)["A"]
    t2 = race(t1, names_12p())
    lost = t1["A two"]
    t2["A two"] = 12          # came back at 0 and finished 2nd
    s.apply_capture(board(t2))
    assert [x["kind"] for x in s.suggestions] == ["rejoin"]
    assert f"Bank {lost} for A" == s.suggestions[0]["button"]
    s.apply_suggestion(s.suggestions[0]["id"])
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
    assert totals_by_tag(s)["B"] == 10 + 1 + 9
    s.undo()
    assert totals_by_tag(s)["B"] == 1 + 9 and [x["id"] for x in s.suggestions] == [sid]
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
    before = totals_by_tag(s)
    s.apply_capture(board(t2), tidy_board=True)
    kinds = [x["kind"] for x in s.suggestions]
    assert "comp11" in kinds
    assert ("note" in kinds) == (not keep_row)          # left the room: their points keep counting by themselves
    assert s.race_info()["delta"] == -15
    s.apply_suggestion("comp11")
    assert s.race_info() == {"number": 2, "of": 12, "left": 10, "grand": 164, "delta": 0}
    after = totals_by_tag(s)
    assert after["A"] - before["A"] == 12 + 10 + 5 and after["C"] - before["C"] == 7 + 0 + 2


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
    assert [r["short"] for r in s.standings()] == ["AB", "AC", "X", "Q"]


def test_greek_tags_keep_their_own_letter():
    from mogi_tracker.session import label_of, team_key
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


# real 6v6 test
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
    assert kinds == {"note", "comp11"}
    comp = next(x for x in s.suggestions if x["kind"] == "comp11")
    assert sum(a["points"] for a in comp["adds"]) == 15
    assert "fenx" in next(x for x in s.suggestions if x["kind"] == "note")["text"]

RACE12 = {"AX★Morven": 104, "AX": 104, "V$ pqzt": 102, "AX Dunn": 98, "V$ rolo": 90, "AX★4Taks": 89, "SX kai_pip": 84,
          "V$ Paz": 70, "V$ Tirane": 59, "V$ Rowlan": 55, "SX☆XORBEAS": 46, "V$ fenx'": 9}


def test_real_11_player_race_and_rejoin_add_up_per_team():
    """fenx leaves with 59, race 11 has 11 players, fenx is back at 0 and scores 9. Red must end on 532,
    blue on 452"""
    s = Session(12, "6v6")
    s.apply_capture(_board(RACE10))
    misread = {("VSPa2" if n == "V$ Paz" else "SX☆ORBES" if n == "SX☆XORBEAS" else "pqzt" if n == "V$ pqzt" else n): t
               for n, t in RACE11.items()}
    s.apply_capture(_board(misread))
    assert s.race_info()["delta"] == -15
    s.apply_suggestion("comp11")
    assert s.race_info() == {"number": 11, "of": 12, "left": 1, "grand": 902, "delta": 0}
    team_of = {m["name"]: r["total"] for r in s.standings() for m in r["members"]}
    assert team_of["SX☆ORBES"] == 485 and team_of["V$ rolo"] == 417
    s.apply_capture(_board(RACE12))
    assert [x["kind"] for x in s.suggestions] == ["note"]
    assert s.race_info() == {"number": 12, "of": 12, "left": 0, "grand": 984, "delta": 0}
    by_member = {m["name"]: r["total"] for r in s.standings() for m in r["members"]}
    assert by_member["V$ fenx'"] == 452 and by_member["AX★Morven"] == 532
    assert len(s.standings()) == 2


def test_bot_points_go_to_the_player_it_stood_in_for(s):
    """race 1 normal, race 2: B two (9 points) DCs and the bot Swoop scores 2, race 3: B two is back at 0 and
    finishes 5th (+8)"""
    t1 = race({}, names_12p())
    assert t1["B two"] == 9
    s.apply_capture(board(t1))
    racers = [n for n in names_12p() if n != "B two"]
    order2 = racers[:10] + ["Swoop"] + racers[10:]
    t2 = race({n: v for n, v in t1.items() if n != "B two"}, order2)
    assert t2["Swoop"] == 2
    s.apply_capture(board(t2))
    assert s.race_info() == {"number": 2, "of": 12, "left": 10, "grand": 164, "delta": 0}
    assert [x["kind"] for x in s.suggestions] == ["note"] and "Swoop" in s.suggestions[0]["text"]
    order3 = racers[:4] + ["B two"] + racers[4:]
    t3 = race({n: v for n, v in t2.items() if n != "Swoop"}, order3)
    t3["B two"] = 8
    s.apply_capture(board(t3))
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 246, "delta": 0}
    b = next(r for r in s.standings() if r["tag"] == "B")
    assert {m["name"]: m["total"] for m in b["members"]}["B two"] == 9 + 2 + 8
    assert b["total"] == t3["B one"] + 19
    assert not any(x["button"] for x in s.suggestions)


def test_missing_the_bot_race_still_works(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    racers = [n for n in names_12p() if n != "B two"]
    t2 = race({n: v for n, v in t1.items() if n != "B two"}, racers[:10] + ["Swoop"] + racers[10:])
    t3 = race({n: v for n, v in t2.items() if n != "Swoop"}, racers[:4] + ["B two"] + racers[4:])
    t3["B two"] = 8
    s.apply_capture(board(t3))
    assert [x["kind"] for x in s.suggestions] == ["rejoin"] and s.suggestions[0]["button"] == "Bank 9 for B"
    s.apply_suggestion(s.suggestions[0]["id"])
    assert s.race_info()["grand"] == 246 - 2 and s.race_info()["number"] == 3


def test_skipping_several_races_is_just_a_bigger_step(s):
    t = race({}, names_12p())
    s.apply_capture(board(t))
    for _ in range(3):
        t = race(t, list(reversed(names_12p())))
    s.apply_capture(board(t))
    assert s.suggestions == [] and s.race_info() == {"number": 4, "of": 12, "left": 8, "grand": 328, "delta": 0}


@pytest.mark.parametrize("back_with", [3, 12])
def test_bot_that_kept_the_points_then_player_back_at_0(s, back_with):
    """C one (8 points) DCs, bot Swoop keeps the points and finishes 12th, so it shows 9.
    Next race C one is back at 0. The 9 must stay with C, also when C one scores more than 9 straight away"""
    t1 = race({}, names_12p())
    assert t1["C one"] == 8
    s.apply_capture(board(t1))
    others = [n for n in names_12p() if n != "C one"]
    t2 = race({("Swoop" if n == "C one" else n): v for n, v in t1.items()}, others + ["Swoop"])
    assert t2["Swoop"] == 9
    s.apply_capture(board(t2))
    assert s.race_info() == {"number": 2, "of": 12, "left": 10, "grand": 164, "delta": 0}
    assert not any(x["button"] for x in s.suggestions)
    order = {3: others[:9] + ["C one"] + others[9:], 12: others[:1] + ["C one"] + others[1:]}[back_with]
    t3 = race({n: v for n, v in t2.items() if n != "Swoop"}, order)
    t3["C one"] = back_with
    s.apply_capture(board(t3))
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 246, "delta": 0}
    c = next(r for r in s.standings() if r["tag"] == "C")
    assert {m["name"]: m["total"] for m in c["members"]}["C one"] == 9 + back_with
    assert [x["kind"] for x in s.suggestions] == ["note"] and "C one is back" in s.suggestions[0]["text"]


def test_bot_scoring_more_than_the_player_had(s):
    t1 = race({}, names_12p())
    assert t1["D two"] == 5
    s.apply_capture(board(t1))
    others = [n for n in names_12p() if n != "D two"]
    t2 = race({n: v for n, v in t1.items() if n != "D two"}, others[:4] + ["Swoop"] + others[4:])
    assert t2["Swoop"] == 8
    s.apply_capture(board(t2))
    assert s.race_info() == {"number": 2, "of": 12, "left": 10, "grand": 164, "delta": 0}
    d = next(r for r in s.standings() if r["tag"] == "D")
    assert {m["name"]: m["total"] for m in d["members"]}["Swoop"] == 5 + 8


def test_rejoin_under_the_same_name_with_a_higher_score_is_offered(s):
    t1 = race({}, names_12p())
    s.apply_capture(board(t1))
    others = [n for n in names_12p() if n != "A two"]
    t2 = race({n: v for n, v in t1.items() if n != "A two"}, ["A two"] + others)
    assert t2["A two"] == 15 and t1["A two"] == 12
    s.apply_capture(board(t2))
    assert [x["kind"] for x in s.suggestions] == ["rejoin"] and s.suggestions[0]["button"] == "Bank 12 for A"
    s.apply_suggestion(s.suggestions[0]["id"])
    assert s.race_info()["delta"] == 0 and s.race_info()["grand"] == 164


def test_custom_tags_are_only_cosmetic(s):
    t = race({}, names_12p())
    s.apply_capture(board(t))
    assert s.set_custom_tag("A", "  V$  ") and s.set_custom_tag("B", "TSS")
    assert s.set_custom_tag("C", "C")             # the read tag typed again still counts as custom
    rows = {r["key"]: r for r in s.standings()}
    assert (rows["A"]["tag"], rows["A"]["short"], rows["A"]["read"], rows["A"]["custom"]) == ("V$", "V$", "A", True)
    assert rows["C"]["custom"] and not rows["D"]["custom"]
    assert s.clipboard_text().startswith("V$ 27 | TSS 19 | C 15 | D 11")
    t = race(t, names_12p())
    s.apply_capture(board(t))
    assert {r["key"]: r["total"] for r in s.standings()}["A"] == 54
    assert s.resolve_tag("v$") == ("ok", "A") and s.resolve_tag("TS") == ("ok", "B") and s.resolve_tag("A") == ("ok", "A")
    assert s.adjust("TSS", 5)["ok"] and {r["key"]: r["total"] for r in s.standings()}["B"] == 43
    assert not s.set_custom_tag("Z", "nope")


def test_custom_tag_limit_reset_undo_and_new_mogi(s):
    s.apply_capture(board(race({}, names_12p())))
    s.set_custom_tag("A", "Nolanimations")
    assert s.custom["A"] == "Nolanimati"       # Nintendo 10 character limit
    s.set_custom_tag("A", "   ")
    assert "A" not in s.custom
    s.set_custom_tag("A", "V$")
    assert s.undo_label() == "tag change"
    s.undo()
    assert "A" not in s.custom
    s.set_custom_tag("A", "V$")
    s.reset()
    assert s.custom == {}


def test_mogi_that_starts_with_11_players_gets_an_open_spot_until_a_sub_joins(s):
    # 2v2, F two never shows up: F one's team is a player short
    racers = [n for n in names_12p() if n != "F two"]
    t1 = race({}, racers, TABLE_11P)
    s.apply_capture(board(t1))
    comp = next(x for x in s.suggestions if x["kind"] == "comp11")
    assert "open spot on F" in comp["text"]
    s.apply_suggestion("comp11")
    assert s.race_info() == {"number": 1, "of": 12, "left": 11, "grand": 82, "delta": 0}
    assert totals_by_tag(s)["F"] == t1["F one"] + 1 + 1             # F one's +1 and the open spot's +1
    # race 2: still 11
    t2 = race(t1, racers[::-1], TABLE_11P)
    s.apply_capture(board(t2))
    assert [x["kind"] for x in s.suggestions] == ["comp11"]
    s.apply_suggestion("comp11")
    assert s.race_info()["grand"] == 164
    # race 3: a sub fills the spot from 0 and inherits its 2 points
    t3 = race(t2, racers + ["F sub"], TABLE_12P)
    s.apply_capture(board(t3))
    assert [x["kind"] for x in s.suggestions] == ["note"]
    assert "F sub took the open spot on F, the 2 points it held count for them" in s.suggestions[0]["text"]
    members = {m["name"]: m["total"] for r in s.standings() for m in r["members"]}
    assert members["F sub"] == t3["F sub"] + 2
    assert s.race_info() == {"number": 3, "of": 12, "left": 9, "grand": 246, "delta": 0}


def test_race_1_with_a_missed_row_is_no_11_player_start(s):
    t1 = race({}, names_12p())
    s.apply_capture(board({n: v for n, v in t1.items() if v != 1}))   # 12th place not read: the 15 is still there
    assert s.suggestions == [] and all(not pl.get("open") for pl in s.places)
    s2 = Session(lobby=12, fmt="2v2")
    s2.apply_capture(board({n: v for n, v in t1.items() if v != 15}), tidy_board=False)   # the winner's row missed
    assert s2.suggestions == [] and all(not pl.get("open") for pl in s2.places)


def test_short_tags_are_the_first_character_unless_two_teams_share_it():
    s = Session(lobby=12, fmt="2v2")
    tags = ["-50", "C", "Cr", "N", "T1", "50"]
    s.apply_capture(board(race({}, [f"{t} {n}" for t in tags for n in ("x", "y")])))
    short = {r["tag"]: r["short"] for r in s.standings()}
    assert short["-50"] == "-" and short["N"] == "N" and short["T1"] == "T" and short["50"] == "5"
    assert short["C"] == "C" and short["CR"] == "CR"       # both start with C so show in full


FFA_NAMES = ["Lantern", "メロメロ", "Moth", "I:·I 9000K", "メカニカル", "ゆきだるま", "Mothra812", "I:·I Tirane",
             "L◇たまごやき", "Nolanimati", "Goatman4000", "Goatwoman"]


def test_ffa_every_player_is_their_own_row_with_their_full_name():
    s = Session(lobby=12, fmt="FFA")
    t1 = race({}, FFA_NAMES)
    s.apply_capture(board(t1))
    rows = s.standings()
    assert len(rows) == 12 and [r["tag"] for r in rows] == FFA_NAMES
    assert all(r["short"] == r["tag"] for r in rows)
    assert s.clipboard_text().split("\n")[:3] == ["Lantern 15", "メロメロ 12", "Moth 10"]
    assert s.format_hint() is None
    t2 = race(t1, FFA_NAMES[::-1])
    s.apply_capture(board({("Mothra8l2" if n == "Mothra812" else n): v for n, v in t2.items()}))
    assert {r["tag"]: r["total"] for r in s.standings()}["Mothra812"] == t2["Mothra812"]
    assert s.race_info()["grand"] == 164


def test_ffa_bot_keeps_the_points_of_the_player_it_replaced():
    s = Session(lobby=12, fmt="FFA")
    t1 = race({}, FFA_NAMES)
    s.apply_capture(board(t1))
    had = t1["Moth"]
    t2 = race({("Swoop" if n == "Moth" else n): v for n, v in t1.items()}, FFA_NAMES[:2] + ["Swoop"] + FFA_NAMES[3:])
    s.apply_capture(board(t2))
    totals = {r["tag"]: r["total"] for r in s.standings()}
    assert totals["Moth"] == t2["Swoop"] and t2["Swoop"] == had + 10
    assert s.race_info()["delta"] == 0


def test_ffa_11_player_start_gets_its_own_open_spot_row():
    s = Session(lobby=12, fmt="FFA")
    t1 = race({}, FFA_NAMES[:11], TABLE_11P)
    s.apply_capture(board(t1))
    s.apply_suggestion("comp11")
    totals = {r["tag"]: r["total"] for r in s.standings()}
    assert totals["Open spot"] == 1 and s.race_info()["grand"] == 82
    t2 = race(t1, FFA_NAMES, TABLE_12P)                                     # GOATWOMAN TAKES OVER!!! graaaaaah
    s.apply_capture(board(t2))
    totals = {r["tag"]: r["total"] for r in s.standings()}
    assert "Open spot" not in totals and totals["Goatwoman"] == t2["Goatwoman"] + 1


def test_switching_to_ffa_mid_mogi_keeps_every_players_points():
    s = Session(lobby=12, fmt="2v2")
    t = race({}, names_12p())
    s.apply_capture(board(t))
    s.set_format("FFA")
    assert {r["tag"]: r["total"] for r in s.standings()} == t
    s.set_format("2v2")
    assert totals_by_tag(s) == {"A": 27, "B": 19, "C": 15, "D": 11, "E": 7, "F": 3}


def test_team_rooms_are_never_hinted_to_be_ffa():
    s = Session(lobby=12, fmt="2v2")
    s.apply_capture(board(race({}, FFA_NAMES)))             # 12 different first letters... almost
    assert s.format_hint() != "FFA"
