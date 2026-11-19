from mogi_tracker import teams


def _tags(names, fmt, lobby):
    out = teams.group_teams_first_char_primary(
        [{"full_name": n, "white_score": 10, "green_score": 0} for n in names], fmt, lobby)
    return {o["name"]: o["team_identifier"] for o in out}


def test_shared_start_wins_over_shared_ending():
    names = ["Nolanimati", "Koberry", "Qqq..", "Ko int", "W★RedFox", "Q Tae-oh", "Sakuberry", "curryOOF!", "curry",
             "N", "S4k1b3rry", "Wafflecone"]
    tags = _tags(names, "2v2", 12)
    assert tags["Sakuberry"] == tags["S4k1b3rry"] == "S"
    assert tags["Koberry"] == tags["Ko int"] == "KO"


def test_tag_at_the_end_still_works():
    assert teams.team_label_for_group([{"full_name": "AlexRKO"}, {"full_name": "BenRKO"}], "A") == "RKO"


def test_capital_i_read_as_lowercase_l_stays_with_its_team():
    names = ["Lantern", "メロメロ", "Moth", "l:·l 9000K", "メカニカル", "ゆきだるまのぼうし", "Mothra812", "I:·I Tirane",
             "L◇たまごやき", "ゆきだるま", "Goatman4000", "Goatwoman"]
    tags = _tags(names, "2v2", 12)
    assert tags["l:·l 9000K"] == tags["I:·I Tirane"] != tags["Lantern"] == tags["L◇たまごやき"]


def test_rebalance_moves_the_player_that_fits_the_short_team():
    p = lambda n: {"full_name": n}
    grouping = {"L": [p("Lantern"), p("Xl:·l 9000K"), p("L◇たまごやき")], "I": [p("I:·I Tirane")], "W": [p("Moth"), p("Mothra")]}
    out = teams.rebalance(grouping, 2)
    assert sorted(m["full_name"] for m in out["I"]) == ["I:·I Tirane", "Xl:·l 9000K"]
    assert teams.rebalance({"L": [p("Lumi"), p("Lumo"), p("Lami")], "B": [p("Bob")]}, 2)["B"] == [p("Bob")]   # no better fit
