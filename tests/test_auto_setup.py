"""Auto player count and format"""
import threading

import pytest

from mogi_tracker import capture, controller, ocr, session as places_session, session_classic, settings, teams

ROOM_6V6 = ["GK Pebble", "GK★Tumble", "GK Rover=3", "GK♪Dinko", "GK plum", "GK Cobble",
            "V$ Thistle", "V$ Rook", "V$ mallow", "V$ Lorne", "V$ Kestrel", "V$ Brine"]
# 2v2
ROOM_2V2 = ["X", "Xa", "Pond え?", "Pond L1", "C 8612", "C", "Marlo Hay", "Mirna Blue", "B◆", "Bow champ", "K", "Kettle",
            "FRZ°Skip", "Fen", "DDJ", "Driftin'", "Y おつ", "YonaYona", "Redさま", "RR", "A", "Ambery24", "μ2nd", "μ 1st"]
ROOM_FFA = ["nerune", "Bipp", "lucent", "yamayamaDX", "fogo3", "Laughter", "B!KZO", "u 1st", "f0rsakeN", "ain", "Akagane",
            "Sainou", "Shine.", "Garnet2", "more than", "geyanb", "Ultraman X", "Weisswolf", "Kusa", "atena", "rq",
            "seeyou", "UMenity", "Mogura"]
# two 4v4 teams start with the same letter
ROOM_4V4 = [f"{tag} {name}" for tag in ("AB", "AX", "Qu", "Zz", "Hm", "Pi")
            for name in ("Fern", "Gale", "Moss", "Reed")]


@pytest.mark.parametrize("names, lobby, fmt", [(ROOM_6V6, 12, "6v6"), (ROOM_2V2, 24, "2v2"), (ROOM_FFA, 24, "FFA"),
                                               (ROOM_4V4, 24, "4v4")])
def test_format_from_the_tags(names, lobby, fmt):
    assert teams.detect_format(names, lobby) == fmt


def test_one_misread_tag_or_one_missing_player_still_fits():
    names = list(ROOM_6V6)
    names[0] = "CK Pebble"
    assert teams.detect_format(names, 12) == "6v6"
    assert teams.detect_format(ROOM_6V6[1:], 12) == "6v6"                  # 11p start
    assert teams.detect_format(names[:11], 12) is None
    assert teams.detect_format(ROOM_6V6[:10], 12) is None
    assert teams.detect_format(ROOM_2V2[2:], 24) == "2v2"                 # 22 of 24


@pytest.mark.parametrize("misread, fmt", [(2, "6v6"), (3, None)])
def test_messy_tags_are_not_taken_for_ffa(misread, fmt):
    # 6v6 where one team's tag also starts with A, and some of the ΛF team were read as AF. Two in 24 still works for this,
    # with three no format fits, but nearly everyone has a teammate, so it's not FFA either
    names = ([f"ZX★{n}" for n in "abcdef"] + [f"anb {n}" for n in "abcdef"] + [f"HRS {n}" for n in "abcdef"] +
             [f"{'AF' if i < misread else 'ΛF'}★{n}" for i, n in enumerate("abcdef")])
    assert teams.detect_format(names, 24) == fmt


@pytest.mark.parametrize("ranks, lobby", [
    ({0: 13, 1: 14, 2: 15}, 24),                                   # scrolling
    ({**{k: k + 1 for k in range(12)}, 12: 13}, 24),
    ({**{k: k + 1 for k in range(11)}, 11: 11, 12: 11}, 24),
    ({**{k: k + 1 for k in range(12)}, 12: 17}, 24),
    ({k: k + 1 for k in range(12)}, 12),
    ({0: 1, 1: 2, 2: 2, 3: 4}, 12),
    ({**{k: k + 1 for k in range(1, 10)}, 11: 13}, 12),
    ({0: 1, 1: 2, 7: 8, 8: 9, 10: 17, 11: 12}, 12),
])
def test_player_count_from_the_ranks(ranks, lobby):
    assert ocr.lobby_of(ranks) == lobby


def players(names, total=10):
    return [{"full_name": n, "white_score": total, "green_score": 0} for n in names]


@pytest.fixture(params=[places_session, session_classic], ids=["places", "classic"])
def engine(request):
    return request.param


def test_first_capture_sets_the_room_up_and_undo_takes_it_back(engine):
    s = engine.Session(lobby=24, fmt="4v4")
    s.apply_capture(players(ROOM_6V6), lobby=12, auto_format=True)
    assert (s.lobby, s.format, s.format_auto) == (12, "6v6", "6v6")
    assert s.undo() == "capture"
    assert (s.lobby, s.format, s.format_auto, s.last_players) == (24, "4v4", None, [])


def test_a_different_player_count_mid_mogi_rebuilds_from_the_board(engine):
    # 5 races captured with 12 players picked, but it was a 24p 2v2 room
    s = engine.Session(lobby=12, fmt="6v6")
    s.apply_capture(players(ROOM_2V2[:12], 30))
    s.apply_capture(players(ROOM_2V2, 30), lobby=24, auto_format=True)
    assert (s.lobby, s.format, s.grand_total()) == (24, "2v2", 720)
    assert s.undo() == "capture" and (s.lobby, s.format) == (12, "6v6")


def test_a_different_format_needs_two_captures_in_a_row(engine):
    s = engine.Session(lobby=12, fmt="4v4")
    s.apply_capture(players(ROOM_6V6), auto_format=True)
    assert s.format == "6v6"
    two_v_two = [f"{tag} {name}" for tag in ("Ka", "Lo", "Mi", "Nu", "Ox", "Pe") for name in ("Wren", "Jay")]
    assert teams.detect_format(two_v_two, 12) == "2v2"
    s.apply_capture(players(two_v_two, 20), auto_format=True)
    assert s.format == "6v6"                     # fool me once
    s.apply_capture(players(ROOM_6V6, 30), auto_format=True)
    s.apply_capture(players(two_v_two, 40), auto_format=True)
    assert s.format == "6v6"                     # fool me twice
    s.apply_capture(players(two_v_two, 50), auto_format=True)
    assert (s.format, s.format_auto) == ("2v2", "2v2")


def test_cant_tell_keeps_the_format_and_tries_again(engine):
    s = engine.Session(lobby=12, fmt="4v4")
    s.apply_capture(players(ROOM_6V6[:10]), auto_format=True)
    assert (s.format, s.format_auto) == ("4v4", None)
    s.apply_capture(players(ROOM_6V6, 20), auto_format=True)
    assert (s.format, s.format_auto) == ("6v6", "6v6")


def test_switching_auto_on_uses_the_last_capture(engine):
    s = engine.Session(lobby=12, fmt="4v4")
    s.apply_capture(players(ROOM_6V6))
    s.detect_format_now()
    assert (s.format, s.format_auto) == ("6v6", "6v6")
    assert s.undo() == "format"


def test_new_mogi_forgets_what_auto_picked(engine):
    s = engine.Session(lobby=12, fmt="4v4")
    s.apply_capture(players(ROOM_6V6), auto_format=True)
    s.reset()
    assert s.format_auto is None and s.format == "6v6"


# controller
def make_controller(monkeypatch):
    c = controller.Controller.__new__(controller.Controller)
    c.settings = dict(settings.DEFAULTS, auto_lobby=True, auto_format=True)
    c.lock, c.watcher, c.watch_error, c._watch_source = threading.RLock(), None, "", None
    c.message = {"id": 0, "text": "", "tone": "info"}
    c.session = places_session.Session(24, "4v4")
    c.busy = c.cancelled = False
    monkeypatch.setattr(settings, "save", lambda s: s)
    monkeypatch.setattr(c, "changed", lambda: None, raising=False)
    monkeypatch.setattr(controller.Controller, "_save_last_capture", staticmethod(lambda frames, record: None))
    return c


def test_picking_by_hand_turns_auto_off(monkeypatch):
    c = make_controller(monkeypatch)
    c._do_settings({"format": "2v2"})
    assert not c.settings["auto_format"] and c.settings["auto_lobby"] and c.session.format == "2v2"
    c._do_settings({"lobby": 12})
    assert not c.settings["auto_lobby"] and c.session.lobby == 12
    c.session.apply_capture(players(ROOM_6V6))
    c._do_settings({"auto_format": True})
    assert c.settings["auto_format"] and c.session.format == "6v6"


def test_switching_auto_on_mid_mogi_lets_the_next_capture_fix_the_room(monkeypatch):
    c = make_controller(monkeypatch)
    c._do_settings({"lobby": 12, "format": "6v6"})                 # wrong settings selected
    fake_capture(monkeypatch, {k: k + 1 for k in range(12)}, ROOM_2V2[:12])
    c._capture_job()
    assert (c.session.lobby, c.session.format) == (12, "6v6")
    c._do_settings({"auto_lobby": True, "auto_format": True})      # race 5: oh.......
    assert c._detect_lobby()                                       # undecided until next capture
    taken, seen = fake_capture(monkeypatch, {0: 13, 1: 14, 2: 15}, ROOM_2V2)
    c._capture_job()
    assert seen["lobby"] == 24 and (c.session.lobby, c.session.format) == (24, "2v2")
    assert not c._detect_lobby()
    fake_capture(monkeypatch, {k: k + 1 for k in range(12)}, ROOM_2V2)
    c._capture_job()
    assert c.session.lobby == 24                                   # decided


def test_first_capture_at_race_5(monkeypatch):
    c = make_controller(monkeypatch)
    c.session = places_session.Session(12, "4v4")
    fake_capture(monkeypatch, {0: 13, 1: 14, 2: 15}, ROOM_2V2, total=30)
    c._capture_job()
    assert (c.session.lobby, c.session.format, c.session.race_info()["number"]) == (24, "2v2", 5)


def fake_capture(monkeypatch, frame_ranks, names, total=10):
    """capture.stream gives frames whose rank column reads `frame_ranks`, the board reads `names`"""
    taken = []

    def stream(source, count, monitor, camera):
        try:
            for i in range(count):
                taken.append(i)
                yield f"frame{i}"
        finally:
            taken.append("closed")

    monkeypatch.setattr(capture, "stream", stream)
    monkeypatch.setattr(ocr, "to_bgr", lambda img: img)
    monkeypatch.setattr(ocr, "board_ranks", lambda img: frame_ranks)
    seen = {}

    def analyze(images, lobby):
        seen["frames"], seen["lobby"] = list(images), lobby
        rows = [{"ti": i} for i in range(len(names))]
        return {"players": players(names, total), "merged": [], "warnings": [], "frames_read": 1,
                "frames": [{"rows": rows}]}

    monkeypatch.setattr(ocr, "analyze", analyze)
    return taken, seen


def test_a_12p_board_is_read_from_one_frame(monkeypatch):
    c = make_controller(monkeypatch)
    taken, seen = fake_capture(monkeypatch, {k: k + 1 for k in range(12)}, ROOM_6V6)
    c._capture_job()
    assert seen == {"frames": ["frame0"], "lobby": 12} and taken == [0, "closed"]
    assert (c.session.lobby, c.session.format) == (12, "6v6")
    assert c.message["text"].startswith("Auto picked 12 players and 6v6")


def test_a_24p_board_takes_the_whole_burst_and_the_count_stays_for_the_mogi(monkeypatch):
    c = make_controller(monkeypatch)
    c.session.set_lobby(12)
    taken, seen = fake_capture(monkeypatch, {0: 13, 1: 14, 2: 15}, ROOM_2V2)
    c._capture_job()
    assert seen["lobby"] == 24 and len(seen["frames"]) == capture.BURST_COUNT
    assert (c.session.lobby, c.session.format) == (24, "2v2")
    taken, seen = fake_capture(monkeypatch, {k: k + 1 for k in range(12)}, ROOM_2V2)
    c._capture_job()
    assert seen["lobby"] == 24 and c.session.lobby == 24


def test_auto_capture_leaves_the_count_to_the_board_until_the_first_capture(monkeypatch):
    c = make_controller(monkeypatch)
    made = []
    monkeypatch.setattr(controller.autocapture, "Watcher", lambda source, monitor, lobby, *a, camera="": made.append(lobby) or
                        type("W", (), {"start": lambda self: self, "stop": lambda self: None})())
    c._do_settings({"auto_capture": True})
    assert made[0]() is None
    c._auto_result({"lobby": 12, "players": players(ROOM_6V6), "tidy": True, "warnings": []})
    assert made[0]() == 12 and c.session.format == "6v6"
