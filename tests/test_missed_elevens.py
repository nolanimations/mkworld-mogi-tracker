"""Races of 11 players that weren't captured"""
from mogi_tracker.session import Session, _placings

NAMES = ["VR Basil", "VR Corin", "KX Rowan", "KX Sable", "KX Tamsin", "VR Dorran", "KX Wren", "VR Esk", "VR Fennick",
         "KX Yarrow", "KX Quill"]
BOARDS = [
    [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
    [15, 17, 15, 13, 11, 7, 7, 14, 15, 10, 10],
    [16, 25, 25, 25, 17, 11, 10, 21, 17, 19, 15],
    [37, 32, 32, 34, 32, 30, 32, 31, 28, 26, 21],
    [39, 40, 38, 38, 41, 37, 44, 34, 38, 31, 22],
    [49, 43, 42, 50, 42, 45, 53, 36, 43, 37, 29],
    [58, 44, 50, 53, 49, 49, 59, 38, 55, 42, 39],
    [76, 53, 57, 68, 62, 71, 73, 49, 67, 46, 48],
    [85, 61, 64, 72, 64, 77, 83, 54, 70, 47, 60],
    [93, 71, 76, 73, 71, 82, 89, 56, 74, 56, 63],
]


def board(totals):
    return [{"full_name": n, "white_score": t, "green_score": 0} for n, t in zip(NAMES, totals)]


def test_missed_races_of_11_get_their_corrections():
    s = Session(12, "6v6")
    cards = []
    for totals in BOARDS:
        s.apply_capture(board(totals))
        assert {x["kind"] for x in s.suggestions} <= {"comp11", "note"}      # no made-up rejoins
        comp = next(x for x in s.suggestions if x["kind"] == "comp11")
        cards.append(comp)
        s.apply_suggestion("comp11")
    assert cards[3]["text"].startswith("Races 4 and 5 weren't captured") and cards[3]["sure"]
    assert "+3 KX Wren, +2 VR Basil, +1 VR Dorran" in cards[3]["text"]
    assert sum(a["points"] for a in cards[3]["adds"]) == 30
    assert cards[7]["text"].startswith("Races 9 and 10 weren't captured") and not cards[7]["sure"]
    assert "6 more points are missing" in cards[7]["text"] and sum(a["points"] for a in cards[7]["adds"]) == 24
    assert s.race_info() == {"number": 12, "of": 12, "left": 0, "grand": 978, "delta": -6}


def test_a_sure_card_is_auto_accepted_like_any_11_player_race():
    s = Session(12, "6v6")
    for totals in BOARDS[:4]:
        s.apply_capture(board(totals))
        assert [x["kind"] for x in s.accept_corrections()] == ["comp11"]
    assert s.race_info()["delta"] == 0


def test_only_a_room_known_to_be_11_counts_races_of_11():
    s = Session(12, "6v6")
    s.apply_capture(board(BOARDS[0]))
    assert s.seats_missing() == 1 and s._race_ok(134) == 2
    full = Session(12, "6v6")
    full.apply_capture([{"full_name": f"P{i}", "white_score": 13 - i if i > 1 else 15 if i == 0 else 12,
                         "green_score": 0} for i in range(12)])
    assert full.seats_missing() == 0 and full._race_ok(134) is None


def test_finishing_orders():
    assert _placings({1: 24, 2: 24}, 2) == []                           # two players can't both win both races
    assert _placings({i: 2 for i in range(11)}, 5) is None              # too many races to go through
