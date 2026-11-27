import pytest

from mogi_tracker import session_classic
from mogi_tracker.session import Session, TABLE_11P, _common_tag, _without_tag

from test_session import FFA_NAMES, board, race

GK = ["GK Pebble", "GK★Tumble", "GK Rover", "GK♪Dinko", "GK plum", "GK Cobble"]
VS = ["V$ Thistle", "V$ Rook", "V$ mallow", "V$ Lorne", "V$ Kestrel", "V$ Brine"]


def play_6v6(races, s=None):
    s = s or Session(12, "6v6")
    t = {}
    for r in range(races):
        t = race(t, (GK + VS) if r % 2 else (VS + GK))
        s.apply_capture(board(t))
    return s, t


def team_totals(s):
    return {r["tag"]: r["total"] for r in s.standings()}


def test_tags_then_players_without_their_tag():
    s, t = play_6v6(2)
    assert s.indivs_text() == ("GK\nPebble 21\nTumble 17\nRover 14\nDinko 12\nplum 10\nCobble 8\n\n"
                               "V$\nThistle 21\nRook 17\nmallow 14\nLorne 12\nKestrel 10\nBrine 8")


@pytest.mark.parametrize("eleven", [False, True])
def test_a_sub_and_the_player_they_replaced_each_get_a_line_with_their_races(eleven):
    s, t = play_6v6(5)
    racers = [n for n in GK + VS if n != "GK Pebble"]
    t = {n: v for n, v in t.items() if n != "GK Pebble"}
    if eleven:                                      # race 6 with 11
        t = race(t, racers, TABLE_11P)
        s.apply_capture(board(t))
        s.apply_suggestion("comp11")
    for _ in range(7 - eleven):
        t = race(t, racers + ["GK Zanzibar"])
        s.apply_capture(board(t))
    gk = s.indivs_text().split("\n\n")[0].split("\n")
    assert gk[-2:] == (["Pebble (5 races) 48+1", "Zanzibar (6 races) 6"] if eleven else
                       ["Pebble (5 races) 48", "Zanzibar (7 races) 7"])
    assert sum(sum(parts) for _, lines, extra in s.indivs()[:1] for _, parts, _ in lines) == team_totals(s)["GK"]


def test_a_rejoin_is_one_line_as_an_addition():
    s, t = play_6v6(3)
    t["GK Rover"] = 0
    t = race(t, GK + VS)
    s.apply_capture(board(t))
    s.apply_suggestion(next(x["id"] for x in s.suggestions if x["kind"] == "rejoin"))
    assert "Rover 10+18" in s.indivs_text().split("\n")            # 10 since the rejoin, 18 before


def test_points_added_by_hand_are_a_penalty_or_bonus_line():
    s, _ = play_6v6(2)
    s.adjust("GK", -5)
    s.adjust("V$", 3)
    vs, gk = s.indivs_text().split("\n\n")                          # V$ is ahead now
    assert gk.endswith("\nPenalty -5") and vs.endswith("\nBonus +3")


def eleven_player_start(sub):
    s = Session(lobby=12, fmt="2v2")
    names = [f"{t} {n}" for t in "ABCDEF" for n in ("one", "two")]
    racers = [n for n in names if n != "F two"]
    t = race({}, racers, TABLE_11P)
    s.apply_capture(board(t))
    s.apply_suggestion("comp11")
    for r in range(2, 13):
        t = race(t, racers + (["F sub"] if sub and r > 2 else []))
        s.apply_capture(board(t))
    return s


def test_no_sub_ever_joined_the_team_gets_the_open_spots_corrections_as_a_bonus():
    f = eleven_player_start(sub=False).indivs_text().split("\n\n")[-1].split("\n")
    assert f[0] == "F" and f[-1] == "Bonus +1" and len(f) == 3


def test_a_sub_takes_the_open_spots_corrections():
    s = eleven_player_start(sub=True)
    f = next(lines for tag, lines, extra in s.indivs() if tag == "F")
    assert ("sub", [10, 1]) in [(name, parts) for name, parts, races in f]
    assert all(extra == 0 for _, _, extra in s.indivs())


def test_ffa_is_just_the_players():
    s = Session(lobby=12, fmt="FFA")
    s.apply_capture(board(race({}, FFA_NAMES)))
    s.adjust("Moth", -2)
    assert s.indivs_text().split("\n")[:4] == ["Lantern 15", "メロメロ 12", "I:·I 9000K 9", "Moth 10-2"]


def test_the_tag_is_only_cut_off_where_it_ends():
    assert _common_tag(["V$ Ruby", "V$ mati"]) == "V$" and _common_tag(["GK★Zubarrr", "GK plum"]) == "GK"
    assert _common_tag(["HRS s☆Jeff", "HRS☆Foni"]) == "HRS" and _common_tag(["Bow champ", "B◆"]) == ""
    assert _without_tag("Bow champ", ["B"]) == "Bow champ" and _without_tag("B◆", ["B"]) == "B◆"
    assert _without_tag("ZX★みず", ["ZX"]) == "みず"


def test_the_old_logic_copies_indivs_too():
    s, _ = play_6v6(2, session_classic.Session(12, "6v6"))
    assert s.indivs_text().startswith("GK\n") and "\n\nV$\n" in s.indivs_text()
