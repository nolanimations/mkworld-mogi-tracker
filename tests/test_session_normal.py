import random

import pytest

from mogi_tracker.ocr import POINTS_TABLE_24
from mogi_tracker.session import Session, TABLE_11P

TABLE_12P = [15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
TAGS = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "M", "N"]
NAMES = ["Mario", "Luigi", "Peach", "Daisy", "Yoshi", "Wario", "Toad", "Rosa", "Koopa", "Birdo", "Pauline", "Cow",
         "pqzt", "Morven", "Dunn", "rolo", "Tirane", "Pazzy", "Rowlan", "Taks", "kai_pip", "Xorbeas", "Brisk", "Vela"]
TAG_LOOKALIKE = {"A": "4", "B": "8", "E": "F", "G": "6", "M": "N", "N": "M", "J": "I", "D": "O", "H": "K"}
LOOKALIKE = {"o": "0", "O": "0", "l": "I", "I": "l", "S": "$", "a": "e", "i": "l", "e": "c"}


def misread(name, rng):
    tag, rest = name.split(" ", 1)
    i = rng.randrange(len(rest))
    ch = rest[i]
    op = rng.random()
    if op < 0.5 and ch in LOOKALIKE:
        rest = rest[:i] + LOOKALIKE[ch] + rest[i + 1:]
    elif op < 0.8 and len(rest) > 3:
        rest = rest[:i] + rest[i + 1:]
    else:
        rest = rest[:i] + rng.choice("xyz") + rest[i:]
    return f"{tag} {rest}"


def play(lobby, fmt, seed, eleven=0.0, partial=0.0, skip=0.15, noise=0.12, tag_noise=0.02):
    rng = random.Random(seed)
    size = int(fmt.split("v")[0])
    tags = TAGS[:lobby // size]
    players = [f"{t} {NAMES[i * size + k]}" for i, t in enumerate(tags) for k in range(size)]
    table = TABLE_12P if lobby == 12 else POINTS_TABLE_24
    owed = dict.fromkeys(players, 0)
    shown = dict.fromkeys(players, 0)
    s = Session(lobby, fmt)
    away = None
    elevens = {r for r in range(2, 12) if lobby == 12 and rng.random() < eleven}
    elevens -= {r + 1 for r in elevens} 
    for r in range(1, 13):
        back, away = away, None
        racers = list(players)
        rng.shuffle(racers)
        if r in elevens:
            away = racers.pop() 
        if back:
            owed_before = owed[back]
            shown[back] = 0
            assert owed[back] == owed_before
        pts = TABLE_11P if away else table
        for p, x in zip(racers, pts):
            shown[p] += x
            owed[p] += x
        if away:
            for k, p in enumerate(racers):
                owed[p] += 3 if k == 0 else 2 if k == 1 else 1
            owed[away] += 1
        captured = r == 12 or r in elevens or r + 1 in elevens or rng.random() > skip
        if not captured:
            continue
        rows = [p for p in players if p != away]
        tidy = True
        if lobby == 24 and r < 12 and rng.random() < partial:
            for _ in range(rng.randint(1, 4)):
                rows.remove(rng.choice(rows))
            tidy = False
        board = []
        for p in rows:
            name = p
            if r < 12 and rng.random() < noise:
                name = misread(name, rng)
            if r < 12 and rng.random() < tag_noise and name[0] in TAG_LOOKALIKE:
                name = TAG_LOOKALIKE[name[0]] + name[1:]
            board.append({"full_name": name, "white_score": shown[p], "green_score": 0})
        s.apply_capture(board, tidy_board=tidy)
        kinds = [x["kind"] for x in s.suggestions]
        assert set(kinds) <= {"comp11", "note"}, (r, [x["text"] for x in s.suggestions])
        if "comp11" in kinds:
            s.apply_suggestion("comp11")
        if tidy:
            assert s.race_info()["delta"] == 0, (r, s.race_info())
    truth = {}
    for p, x in owed.items():
        truth[p.split(" ")[0]] = truth.get(p.split(" ")[0], 0) + x
    got = {}
    for row in s.standings():
        tag = row["members"][0]["name"].split(" ")[0]
        got[tag] = got.get(tag, 0) + row["total"]
    assert got == truth, (seed, got, truth)
    assert s.race_info() == {"number": 12, "of": 12, "left": 0, "grand": 12 * sum(table), "delta": 0}
    indivs = {name: sum(parts) for tag, lines, extra in s.indivs() for name, parts, races in lines}
    assert indivs == {p.split(" ", 1)[1]: x for p, x in owed.items()}, seed
    assert all(extra == 0 for _, _, extra in s.indivs())


@pytest.mark.parametrize("fmt", ["2v2", "3v3", "6v6"])
@pytest.mark.parametrize("seed", range(25))
def test_normal_12p_mogi(seed, fmt):
    play(12, fmt, seed)


@pytest.mark.parametrize("seed", range(25))
def test_12p_mogi_with_the_odd_11_player_race(seed):
    play(12, "2v2", seed, eleven=0.15)


@pytest.mark.parametrize("fmt", ["2v2", "4v4", "6v6"])
@pytest.mark.parametrize("seed", range(20))
def test_normal_24p_mogi_with_partial_reads(seed, fmt):
    play(24, fmt, seed, partial=0.25)
