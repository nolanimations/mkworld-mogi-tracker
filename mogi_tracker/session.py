"""NEW SESSION LOGIC

This session logic remembers *places*: a place starts with the player first seen there and remembers:
- the team
- the points of earlier occupants (`carried`): when a player leaves/a bot takes over or the player rejoins at 0,the
  place remembers their last race (if captured in order).
If it still has to guess it merely suggests
"""
import collections
import copy
import difflib
import itertools
import math
import re
import unicodedata

from . import teams

TOTAL_RACES = 12
POINTS_PER_RACE = {24: 144, 12: 82}
TABLE_11P = [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
UNDO_DEPTH = 20
NAME_MATCH = 0.7
OPEN_SPOT = "Open spot"

_FOLD = str.maketrans({"l": "I", "0": "O"})


def label_of(tag) -> str:
    return teams.upper_latin(re.sub(r"\s+", "", str(tag or ""))) or "?"


def team_key(tag) -> str:
    return teams.upper_latin(re.sub(r"\s+", "", str(tag or "")).translate(_FOLD)) or "?"


def player_key(name) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or ""))).translate(_FOLD).casefold()


def _points(n):
    return f"{n} point" if n == 1 else f"{n} points"


def _alike(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


MISREAD_ALIKE = 0.5    # misreads of one name measured 0.6+, two different names up to 0.44
FITS_TOTAL = 0.05      # tie-break between two equally alike pairings: prefer the one where no total went down


CUSTOM_TAG_MAX = 10


class CustomTags:

    def set_custom_tag(self, key, text):
        if key not in self.keys():
            return False
        text = re.sub(r"\s+", " ", str(text or "")).strip()[:CUSTOM_TAG_MAX]
        if text == self.custom.get(key, ""):
            return True
        self._push_undo("tag change")
        if text:
            self.custom[key] = text
        else:
            self.custom.pop(key, None)
        return True

    def _custom_match(self, typed, keys):
        tags = {k: team_key(self.custom[k]) for k in keys if k in self.custom}
        for hits in ([k for k, t in tags.items() if t == typed], [k for k, t in tags.items() if t.startswith(typed)]):
            if len(hits) == 1:
                return hits[0]
        return None

    def _with_custom(self, rows):
        for r in rows:
            r["read"], r["custom"] = r["tag"], r["key"] in self.custom
            if r["custom"]:
                r["tag"] = r["short"] = self.custom[r["key"]]
        return rows


class Session(CustomTags):
    _FIELDS = ("lobby", "format", "bank", "display", "places", "last_players", "prev_totals", "prev_ranks",
               "suggestions", "custom")

    def __init__(self, lobby=24, fmt="4v4", races=TOTAL_RACES):
        self.lobby = lobby
        self.format = fmt
        self.races = races
        self._undo = []
        self._clear()

    def _clear(self):
        self.bank = {}
        self.display = {}
        self.custom = {}
        self.places = []
        self.last_players = []
        self.prev_totals = None
        self.prev_ranks = None
        self.suggestions = []
        self._offered = set()
        self._points_before = 0
        self._declined = set()

    # undo
    def _push_undo(self, label, auto=None):
        self._undo.append((label, {f: copy.deepcopy(getattr(self, f)) for f in self._FIELDS}, auto))
        del self._undo[:-UNDO_DEPTH]

    def undo(self):
        if not self._undo:
            return None
        label, state, auto = self._undo.pop()
        for f, value in state.items():
            setattr(self, f, value)
        if auto:
            self._declined.add(auto)
        return label

    def undo_label(self):
        return self._undo[-1][0] if self._undo else None

    # totals
    @property
    def live(self):
        out = {}
        for pl in self.places:
            out[pl["team"]] = out.get(pl["team"], 0) + pl["total"] + pl["carried"]
        return out

    @property
    def members(self):
        out = {}
        for pl in sorted(self.places, key=lambda pl: pl["order"]):
            out.setdefault(pl["team"], []).append({"name": pl["name"], "total": pl["total"] + pl["carried"]})
        return out

    def keys(self):
        return set(self.live) | set(self.bank)

    def total(self, key):
        return self.live.get(key, 0) + self.bank.get(key, 0)

    def _totals(self):
        live = self.live
        return {k: live.get(k, 0) + self.bank.get(k, 0) for k in set(live) | set(self.bank)}

    def _ranks(self, totals=None):
        totals = self._totals() if totals is None else totals
        shown = {k: t for k, t in totals.items() if t != 0}
        return {k: 1 + sum(o > t for o in shown.values()) for k, t in shown.items()}

    def grand_total(self):
        return sum(self.live.values()) + sum(self.bank.values())

    def race_info(self):
        grand = self.grand_total()
        per_race = POINTS_PER_RACE[self.lobby]
        number = min(self.races, max(1, round(grand / per_race))) if grand else 0
        return {
            "number": number,
            "of": self.races,
            "left": self.races - number,
            "grand": grand,
            "delta": grand - number * per_race if grand else 0,
        }

    # setup
    def set_lobby(self, lobby):
        if lobby == self.lobby:
            return
        self._push_undo("room size")
        self.lobby = lobby
        if self.format not in teams.formats_for(lobby):
            self.format = "4v4"
        self.last_players, self.places = [], []

    def set_format(self, fmt):
        if fmt == self.format or fmt not in teams.formats_for(self.lobby):
            return
        self._push_undo("format")
        self.format = fmt
        self._regroup()

    def format_hint(self):
        if not self.last_players:
            return None
        return teams.suggest_team_format([p["name"] for p in self.last_players], self.format, self.lobby)

    # captures
    def _group(self, players):
        return teams.group_teams_first_char_primary(players, team_format=self.format, lobby_size=self.lobby)

    def _new_place(self, p, order):
        pk = player_key(p["name"])
        place = {"id": max((pl["id"] for pl in self.places), default=0) + 1, "origin": pk, "aliases": [pk],
                 "pk": pk, "name": p["name"], "total": p["total_score"], "carried": 0, "away": False,
                 "stand_in": False, "votes": {}, "team": None, "order": order}
        self.places.append(place)
        return place

    def _match(self, grouped):
        """Pair the players on the board with places. Returns ([(place, player)], unmatched places)"""
        free = list(self.places)
        pairs = []
        by_pk = collections.defaultdict(list)
        for p in grouped:
            by_pk[player_key(p["name"])].append(p)
        left = []
        for pk, ps in by_pk.items():
            mine = [pl for pl in free if pk in pl["aliases"] or pk == pl["pk"]]
            if not mine:
                left += ps
                continue
            ps = sorted(ps, key=lambda p: -p["total_score"])
            mine = sorted(mine, key=lambda pl: -pl["total"])
            for p, pl in zip(ps, mine):
                pairs.append((pl, p))
                free.remove(pl)
            left += ps[len(mine):]
        # nobody new joins a room mid-mogi (usually), so a name
        # that wasn't there before is a misread or a stand-in (bot, sub, rejoin) for a place gone
        # from the board. The totals decide which one it is (see _occupants).
        # Until the whole room has been seen (partial 24p reads), an unlike name can also be a player that simply
        # wasn't read yet: those get their own place while there are seats nobody was seen in.
        # Equally alike names ("A ario": Mario or Wario?) go to the place whose total is just below theirs
        alike = sorted(((max(_alike(player_key(p["name"]), a) for a in pl["aliases"] + [pl["pk"]]),
                         p["total_score"] - pl["total"], i, j)
                        for i, p in enumerate(left) for j, pl in enumerate(free)),
                       key=lambda x: (-x[0], x[1] < 0, abs(x[1])))
        unseen = max(0, self.lobby - len(self.places))

        def misread(ratio, gain):
            # a half-alike name with a lower total is more likely someone else than a misread
            return ratio >= MISREAD_ALIKE and (gain >= 0 or ratio >= NAME_MATCH)

        used_p, used_pl = set(), set()
        for misreads_only in (True, False):
            for ratio, gain, i, j in alike:
                if i in used_p or j in used_pl or (misreads_only and not misread(ratio, gain)):
                    continue
                if not misreads_only and len(left) - len(used_p) <= unseen:
                    break
                used_p.add(i), used_pl.add(j)
                pairs.append((free[j], left[i]))
        extra = [p for i, p in enumerate(left) if i not in used_p]
        gone = [pl for j, pl in enumerate(free) if j not in used_pl]
        return self._untangle(pairs, extra, gone)

    @staticmethod
    def _fit(pl, p):
        """How well a board row fits a place. name likeness (1 for a known name), plus a little when the total did
        not go down. An empty side (a row that gets a new place, a place nobody is in) fits 0"""
        if pl is None or p is None:
            return 0
        pk = player_key(p["name"])
        names = pl["aliases"] + [pl["pk"]]
        alike = 1.0 if pk in names else max(_alike(pk, a) for a in names)
        return alike + (FITS_TOTAL if p["total_score"] >= pl["total"] else 0)

    def _untangle(self, pairs, extra, gone):
        """Swap rows between places (or with a row that gets a new place, or a place nobody took) while that fits
        the board better overall. Matching one row at a time can give a name that fits two places ("A ario":
        Mario or Wario?) to the wrong one, and then its teammate's total goes "down" in the other place"""
        slots = list(pairs) + [(None, p) for p in extra] + [(pl, None) for pl in gone]
        fit = {}

        def f(pl, p):
            key = (id(pl), id(p))
            if key not in fit:
                fit[key] = self._fit(pl, p)
            return fit[key]

        better = True
        while better:
            better = False
            for a, b in itertools.combinations(range(len(slots)), 2):
                (pa, ra), (pb, rb) = slots[a], slots[b]
                if (pa is None and rb is None) or (pb is None and ra is None) or (ra is None and rb is None):
                    continue
                if min(f(pa, ra), f(pb, rb)) >= 1 + FITS_TOTAL:
                    continue
                if f(pa, rb) + f(pb, ra) > f(pa, ra) + f(pb, rb) + 1e-9:
                    slots[a], slots[b] = (pa, rb), (pb, ra)
                    better = True
        return ([(pl, p) for pl, p in slots if pl is not None and p is not None],
                [p for pl, p in slots if pl is None], [pl for pl, p in slots if p is None])

    def apply_capture(self, players, tidy_board=True):
        grouped = self._group(players)
        self._push_undo("capture")
        totals_before, ranks_before = self._totals(), self._ranks()
        had_scores = any(totals_before.values())
        live_before = self.live
        self._offered, self._points_before = set(), self.grand_total()
        self.suggestions = [s for s in self.suggestions if s["kind"] != "note"]
        order = {id(p): i for i, p in enumerate(grouped)}

        skip = set()
        if not self.places:
            pairs = [(self._new_place(p, order[id(p)]), p) for p in grouped]
            gone, notes = [], []
        else:
            pairs, extra, gone = self._match(grouped)
            pairs += [(self._new_place(p, order[id(p)]), p) for p in extra]
            if self._reopened(pairs):
                self._suggest("room", "room", "Most totals went back down, looks like reopen? "
                              f"The old room's {sum(live_before.values())} points are not banked yet",
                              "Bank old room", [{"key": k, "points": pts} for k, pts in live_before.items() if pts],
                              done=f"Looks like a reopen, banked the old room's {_points(sum(live_before.values()))}")
                for pl, p in pairs:
                    pl["carried"], pl["away"], pl["stand_in"] = 0, False, False
                self.places = [pl for pl, _ in pairs]
                notes = []
            else:
                notes, skip = self._occupants(pairs, gone, tidy_board, first_seen=bool(extra))

        pairs = [(pl, p) for pl, p in pairs if pl["id"] not in skip]
        first = not had_scores and all(pl["total"] == p["total_score"] for pl, p in pairs)
        for pl, p in pairs:
            pl.update(total=p["total_score"], name=p["name"], pk=player_key(p["name"]), order=order[id(p)],
                      away=False)
        for pl, p in pairs:
            # how the place's own player was read (FFA shows the usual one): readings like their first name only,
            # so a bot that kept their points doesn't rename them
            if not pl["stand_in"] and _alike(player_key(p["name"]), pl["origin"]) >= MISREAD_ALIKE:
                names = pl.setdefault("names", {})
                names[p["name"]] = names.get(p["name"], 0) + 1
        self._vote_teams(pairs)
        if first and tidy_board:
            self._eleven_player_start(pairs)
        for text in notes:
            self._suggest(f"note:{len(self.suggestions)}", "note", text, None, [])
        self.last_players = [{"name": p["name"], "total": p["total_score"]} for p in grouped]
        self.prev_totals = totals_before if had_scores else None
        self.prev_ranks = ranks_before if had_scores else None

    def _reopened(self, pairs):
        drops = [1 for pl, p in pairs if p["total_score"] < pl["total"]]
        return len(drops) >= max(3, math.ceil(len(pairs) / 2))

    def _occupants(self, pairs, gone, tidy_board, first_seen=False):
        """Work out who is in each place now, returns notes. `first_seen`: someone on the board got a place just now
        (24p, not read before), so how much they gained this race is unknown"""
        notes = []
        if self.lobby == 12 and tidy_board and len(pairs) < 12:
            for pl in gone:
                if not pl["away"]:
                    pl["away"] = True
                    notes.append(f"{pl['name']} left the room. Their {_points(pl['total'])} still count for "
                                 f"{self._tag(pl['team'])}")
        seen_all = all(pl["away"] for pl in gone)        # every known place is on the board (or away)
        complete = seen_all and not first_seen            # every place's points this race are known

        fixed, drops, unsure, back = [], [], [], []       # fixed: (place, player, started_at_0)
        own = {}                                          # place id: the row is the place's own player
        for pl, p in pairs:
            pk, new = player_key(p["name"]), p["total_score"]
            origin = self._is_origin(pl, pk)
            current = pk == pl["pk"] or _alike(pk, pl["pk"]) >= NAME_MATCH
            own[pl["id"]] = origin or (current and not pl["stand_in"])
            if pl["away"] and own[pl["id"]]:
                fixed.append((pl, p, True))               # rejoin at 0
            elif origin and pl["stand_in"]:
                back.append((pl, p))                      # back after a stand-in, or the "stand-in" was them misread
            elif current and new < pl["total"]:
                drops.append((pl, p))                     # same name, lower total: uncaught DC or misread
            elif current:
                fixed.append((pl, p, False))
            else:
                unsure.append((pl, p))

        def gain(pl, p, fresh):
            return p["total_score"] - (0 if fresh else pl["total"])

        base = sum(gain(*f) for f in fixed) + sum(p["total_score"] for _, p in drops)
        names_changed = bool(unsure)
        answer = self._adds_up(base, unsure + back) if complete else None
        skip = set()
        if answer is None:
            back_answer = [True] * len(back)              # can't tell: they rejoined at 0
            # the race can't tell, so nothing happens by itself: on a board with rows missing the pairing itself
            # may be off (leave those places as they were), otherwise a lower total is a suggestion like any drop
            rest = []
            for pl, p in unsure:
                if not seen_all:
                    skip.add(pl["id"])
                elif p["total_score"] < pl["total"]:
                    drops.append((pl, p))
                else:
                    rest.append((pl, p))
            unsure, answer = rest, [False] * len(rest)
        else:
            answer, back_answer = answer[:len(unsure)], answer[len(unsure):]
        decided = fixed + [(pl, p, fresh) for (pl, p), fresh in zip(unsure + back, answer + back_answer)]

        # same name and a higher total, but the race only adds up if they started over: a rejoin that immediately has a higher score after rejoining compared to before DC'ing
        if complete and not names_changed and not back and not drops and self._race_ok(base) is None:
            fits = [(pl, p) for pl, p, fresh in fixed
                    if not fresh and self._could_start_over(p, self._race_ok(base + pl["total"]))]
            # in a race that wasn't captured a bot could've raced for someone
            others = [pl for pl, p, fresh in fixed if not fresh and not any(pl is f for f, _ in fits)
                      and self._could_have_missed_races(pl, p, base)]
            if len(fits) == 1 and not others:
                drops.append(fits[0])
                base += fits[0][0]["total"]
                decided = [d for d in decided if d[0] is not fits[0][0]]

        bot = 0
        if (complete and not names_changed and not back and len(drops) == 1
                and len(pairs) == len(self.last_players) == self.lobby):
            bot = self._missed_bot(base, drops[0][1])
        for pl, p in drops:
            team = self._tag(pl["team"])
            why = (f"{p['name']} went from {pl['total']} to {p['total_score']}, looks like a DC? "
                   if p["total_score"] < pl["total"] else
                   f"The points only add up if {p['name']} DC'd and rejoined. ")
            points, parts, also = pl["total"], "", ""
            if bot and (bot < 15 or self.lobby == 24):      # 15 in 12p, 11p?
                points += bot
                parts = f": {pl['total']} from before and {bot} from a bot in a race that wasn't captured"
            elif bot:
                also = (f". Another {bot} are missing from races that weren't captured. If a bot raced for them those "
                        f"go to {team} too, if it was 11 players add the usual correction by hand")
            self._suggest(f"pts:{pl['id']}", "rejoin", why + f"They seem to be missing {points} points" + parts + also,
                          f"Bank {points} for {team}", [{"place": pl["id"], "points": points}],
                          done=f"{p['name']} DC'd and rejoined, added {_points(points)} to {team}" + parts,
                          sure=p["total_score"] < pl["total"] and bot <= 15, score=p["total_score"])
        steady = []
        for pl, p, fresh in decided:
            pk = player_key(p["name"])
            origin = own[pl["id"]]
            team = self._tag(pl["team"])
            if pl.get("open"):                    # sub fills the room's open spot
                pl.update(open=False, origin=pk, aliases=[pk], stand_in=False)
                notes.append(f"{p['name']} took the open spot on {team}"
                             + (f", the {_points(pl['carried'])} it held count for them" if pl["carried"] else ""))
                steady.append((pl, p["total_score"]))
                continue
            if fresh:
                if origin:
                    had = f"their {_points(pl['total'])} from before" if pl["away"] or pl["name"] == p["name"] \
                        else f"the {_points(pl['total'])} {pl['name']} had for them"
                    notes.append(f"{p['name']} is back")
                    pl["stand_in"] = False
                else:
                    notes.append(f"{p['name']} took {pl['name']}'s place. {_points(pl['total'])} stay with {team}")
                    pl["stand_in"] = True
                pl["carried"] += pl["total"]
            elif origin and pl["stand_in"]:
                pl["stand_in"] = False            # kept their points: the "stand-in" was them, misread
            elif pk not in pl["aliases"] and not self._is_origin(pl, pk) and not pl["stand_in"]:
                pl["aliases"].append(pk)          # the player's own names only, a stand-in that stays is no rejoin
            steady.append((pl, gain(pl, p, fresh)))
        self._eleven_players(steady, [pl for pl in gone if pl["away"]] if tidy_board else [])
        return notes, skip

    @staticmethod
    def _is_origin(pl, pk):
        """`pk` looks like the player first seen in this place"""
        return pk in pl["aliases"] or any(_alike(pk, a) >= NAME_MATCH for a in pl["aliases"])

    def _race_ok(self, points):
        per = POINTS_PER_RACE[self.lobby]
        for k in range(1, max(self.races, TOTAL_RACES) + 1):
            if points == per * k or (self.lobby == 12 and points == per * k - (per - sum(TABLE_11P))):
                return k
        return None

    @staticmethod
    def _could_start_over(p, races):
        return races is not None and p["total_score"] <= 15 * races

    def _could_have_missed_races(self, pl, p, base):
        """Would the points add up if this place started over and a bot played for it in races that weren't captured?"""
        per = POINTS_PER_RACE[self.lobby]
        return any(0 <= per * k - base - pl["total"] <= 15 * (k - 1) and p["total_score"] <= 15 * (k - 1)
                   for k in range(2, max(self.races, TOTAL_RACES) + 1))

    def _missed_bot(self, base, p):
        """Points missing after `p` rejoined at 0, if a bot can have raced for them in races that weren't captured"""
        per = POINTS_PER_RACE[self.lobby]
        races = math.ceil(base / per)
        missing = per * races - base
        return missing if p["total_score"] > 0 and max(missing, p["total_score"]) <= 15 * (races - 1) else 0

    def _adds_up(self, base, unsure):
        """For each unsure place: did someone start over? The answer that makes the fewest races add up, if
        there is exactly one"""
        if not unsure or len(unsure) > 6:
            return None
        fits = []
        for answer in itertools.product((False, True), repeat=len(unsure)):
            points = base + sum(p["total_score"] - (0 if fresh else pl["total"])
                                for (pl, p), fresh in zip(unsure, answer))
            k = self._race_ok(points)
            if k is not None and all(self._could_start_over(p, k) for (pl, p), fresh in zip(unsure, answer) if fresh):
                fits.append((k, answer))
        if not fits:
            return None
        fewest = min(k for k, _ in fits)
        best = [answer for k, answer in fits if k == fewest]
        return list(best[0]) if len(best) == 1 else None

    def _eleven_player_start(self, pairs):
        """if race 1 with 11 players (12p), an open spot on the team that is short holds the +1s of 11 player races until a sub joins"""
        if self.lobby != 12 or len(pairs) != 11 or any(pl.get("open") for pl in self.places):
            return
        if sorted((p["total_score"] for _, p in pairs), reverse=True) != TABLE_11P:
            return
        if self.format == teams.FFA:
            short = [team_key(OPEN_SPOT)]
        else:
            size = int(self.format.split("v")[0])
            count = collections.Counter(pl["team"] for pl, _ in pairs)
            short = [t for t, n in count.items() if n < size]
        if len(short) != 1:
            return              # can't tell which team is short so the race shows 15 points missing instead
        spot = {"id": max(pl["id"] for pl in self.places) + 1, "origin": "", "aliases": [], "pk": "",
                "name": OPEN_SPOT, "total": 0, "carried": 0, "away": True, "stand_in": False, "votes": {},
                "team": short[0], "order": 11, "open": True}
        self.places.append(spot)
        self._eleven_players([(pl, p["total_score"]) for pl, p in pairs], [spot])

    def _eleven_players(self, steady, away):
        if self.lobby != 12:
            return
        scored = sorted((g for _, g in steady if g > 0), reverse=True)
        idle = [pl for pl, g in steady if g == 0] + away
        if scored != TABLE_11P or len(idle) != 1:
            return
        first = next(pl for pl, g in steady if g == 12)
        second = next(pl for pl, g in steady if g == 10)
        adds = [{"place": pl["id"], "points": 3 if pl is first else 2 if pl is second else 1}
                for pl, g in steady if g > 0]
        adds.append({"place": idle[0]["id"], "points": 1})
        missing = (f"the open spot on {self._tag(idle[0]['team'])}" if idle[0].get("open") else
                   f"{idle[0]['name']}, who missed this race")
        self._suggest("comp11", "comp11",
                      f"Looks like an 11 player race. The usual correction is +3 for 1st ({first['name']}), "
                      f"+2 for 2nd ({second['name']}), +1 for everyone else and +1 for {missing}",
                      "Add 15 points", adds,
                      done=f"11 player race, added 15 points: +3 for 1st ({first['name']}), +2 for 2nd "
                           f"({second['name']}), +1 for everyone else and +1 for {missing}",
                      # 15 points: did they miss the race, or rejoin and win?
                      sure=idle[0] in away or idle[0]["total"] != 15)

    def _vote_teams(self, pairs):
        """Each place votes for the team its group belongs to (stand-ins don't vote)"""
        groups, labels = collections.defaultdict(list), {}
        for pl, p in pairs:
            tag = p.get("team_identifier") or "NoTag"
            key = team_key(tag)
            groups[key].append(pl)
            if len(tag) > len(labels.get(key, "")):
                labels[key] = tag
        scores = []
        for g, pls in groups.items():
            known = collections.Counter(pl["team"] for pl in pls if pl["team"] and not pl["stand_in"])
            scores += [(n, g, t) for t, n in known.items()]
        mapping, taken = {}, set()
        for n, g, t in sorted(scores, key=lambda x: (-x[0], x[1], x[2])):
            if g not in mapping and t not in taken:
                mapping[g] = t
                taken.add(t)
        existing = {pl["team"] for pl in self.places if pl["team"]}
        for g in groups:
            if g not in mapping:
                t, n = g, 2
                while t in taken or (t in existing and t != g):
                    t, n = f"{g}{n}", n + 1
                mapping[g] = t
                taken.add(t)
        for g, pls in groups.items():
            t = mapping[g]
            if t not in self.display or len(labels[g]) > len(self.display[t]):
                self.display[t] = labels[g]
            for pl in pls:
                if pl["stand_in"]:
                    pl["team"] = pl["team"] or t
                    continue
                pl["votes"][t] = pl["votes"].get(t, 0) + 1
                had = pl["team"]
                pl["team"] = max(pl["votes"], key=lambda k: (pl["votes"][k], k == had, k == t))

    def _regroup(self):
        """New format, recreate teams"""
        if not self.last_players:
            return
        players = [{"full_name": p["name"], "white_score": p["total"], "green_score": 0} for p in self.last_players]
        grouped = self._group(players)
        old_team = {pl["id"]: pl["team"] for pl in self.places}
        for pl in self.places:
            pl["votes"], pl["team"] = {}, None
        self.display = {k: v for k, v in self.display.items() if k in self.bank}
        pairs, _, _ = self._match(grouped)
        stand_ins = [pl for pl, _ in pairs if pl["stand_in"]]
        for pl in stand_ins:
            pl["stand_in"] = False
        self._vote_teams(pairs)
        for pl in stand_ins:
            pl["stand_in"] = True
        for pl in self.places:
            if pl["team"] is None:
                mates = collections.Counter(o["team"] for o in self.places
                                            if o["team"] and old_team[o["id"]] == old_team[pl["id"]])
                pl["team"] = mates.most_common(1)[0][0] if mates else old_team[pl["id"]]

    def same_board(self, players):
        """True if `players` is last captured board"""
        if not self.last_players:
            return False
        new = sorted(p["white_score"] + p["green_score"] for p in players)
        return new == sorted(p["total"] for p in self.last_players)

    # suggestions and notes
    def _suggest(self, sid, kind, text, button, adds, done="", sure=True, score=0):
        team = {pl["id"]: pl["team"] for pl in self.places}
        adds = [{"team": team.get(a.get("place")), **a} for a in adds]
        self.suggestions = [s for s in self.suggestions if s["id"] != sid]
        self.suggestions.append({"id": sid, "kind": kind, "text": text, "button": button, "adds": adds,
                                 "done": done, "sure": sure, "score": score})
        if button:
            self._offered.add(sid)

    def _tag(self, key):
        if self.format == teams.FFA:
            pl = next((pl for pl in self.places if pl["team"] == key), None)
            if pl:
                names = pl.get("names") or {pl["name"]: 1}
                return max(names, key=names.get)      # a tie goes to the name seen first
        return self.display.get(key, key)

    def apply_suggestion(self, sid):
        s = next((s for s in self.suggestions if s["id"] == sid), None)
        if not s or not s["button"]:
            return None
        self._push_undo(s["button"][0].lower() + s["button"][1:])
        self._apply(s)
        return s

    def _apply(self, s):
        places = {pl["id"]: pl for pl in self.places}
        for add in s["adds"]:
            if "place" in add and add["place"] in places:
                places[add["place"]]["carried"] += add["points"]
            else:
                key = add.get("key") or add["team"]
                if not key:
                    continue
                self.bank[key] = self.bank.get(key, 0) + add["points"]
                self.display.setdefault(key, key)
        self.suggestions = [x for x in self.suggestions if x["id"] != s["id"]]

    def accept_corrections(self):
        new = [s for s in self.suggestions if s["id"] in self._offered]
        self._offered = set()
        if not new or not all(s["sure"] for s in new) or not self._adds_up_with(new):
            return []
        board = (tuple(sorted(p["total"] for p in self.last_players)),
                 tuple(sorted((s["kind"], a.get("key") or a["team"] or "", a["points"])
                              for s in new for a in s["adds"])))
        if board in self._declined:
            return []
        button = new[0]["button"]
        self._push_undo(button[0].lower() + button[1:] if len(new) == 1 else f"{len(new)} corrections", auto=board)
        for s in new:
            self._apply(s)
            self._suggest(f"auto:{s['id']}", "note", s["done"], None, [])
        return new

    def _adds_up_with(self, new):
        per = POINTS_PER_RACE[self.lobby]
        total = self.grand_total() + sum(a["points"] for s in new for a in s["adds"])
        races = round((total - self._points_before) / per)
        missing, missing_before = (t - per * round(t / per) for t in (total, self._points_before))
        return missing in (0, missing_before) and all(s["score"] <= 15 * races for s in new)

    def dismiss_suggestion(self, sid):
        self.suggestions = [s for s in self.suggestions if s["id"] != sid]

    # bank
    def bank_all(self):
        live = self.live
        if not any(live.values()):
            return False
        self._push_undo("bank all")
        for key, pts in live.items():
            self.bank[key] = self.bank.get(key, 0) + pts
        self.places, self.last_players = [], []
        self.suggestions = [s for s in self.suggestions if s["kind"] != "room"]
        return True

    def resolve_tag(self, text):
        typed = team_key(text)
        if typed == "?":
            return "unknown", None
        keys = self.keys()
        if typed in keys:
            return "ok", typed
        custom = self._custom_match(typed, keys)
        if custom:
            return "ok", custom
        starts = sorted(k for k in keys if k.startswith(typed))
        if len(starts) == 1:
            return "ok", starts[0]
        # the tag as shown can be longer than the team's first reading
        shown = sorted(k for k in keys if team_key(self._tag(k)).startswith(typed))
        if len(shown) == 1:
            return "ok", shown[0]
        if starts or shown:
            return "ambiguous", [self._tag(k) for k in (starts or shown)]
        return "unknown", None

    def adjust(self, tag_text, points, create=False):
        status, found = self.resolve_tag(tag_text)
        if status == "ambiguous":
            return {"ok": False, "reason": "ambiguous", "matches": found}
        if status == "unknown":
            if not create or team_key(tag_text) == "?":
                return {"ok": False, "reason": "unknown", "tag": str(tag_text).strip()}
            found = team_key(tag_text)
            self._push_undo(f"{points:+} {str(tag_text).strip()}")
            self.display[found] = str(tag_text).strip()
        else:
            self._push_undo(f"{points:+} {self._tag(found)}")
        self.bank[found] = self.bank.get(found, 0) + points
        return {"ok": True, "tag": self._tag(found), "points": points}

    def reset(self):
        self._push_undo("new mogi")
        self._clear()

    # output
    def standings(self, my_tag=""):
        live, members = self.live, self.members
        totals = {k: t for k, t in self._totals().items() if t != 0}
        ranks = self._ranks(totals)
        mine = self.resolve_tag(my_tag)[1] if my_tag else None
        mine = mine if isinstance(mine, str) else None
        rows, above = [], None
        board_order = {}
        for pl in self.places:
            board_order[pl["team"]] = min(board_order.get(pl["team"], 99), pl["order"])
        tie = (lambda k: (board_order.get(k, 99), k)) if self.format == teams.FFA else (lambda k: (0, k))
        for key in sorted(totals, key=lambda k: (-totals[k], tie(k))):
            before = self.prev_totals.get(key) if self.prev_totals else None
            was = self.prev_ranks.get(key) if self.prev_ranks else None
            rows.append({
                "key": key,
                "tag": self._tag(key),
                "rank": ranks[key],
                "total": totals[key],
                "live": live.get(key, 0),
                "bank": self.bank.get(key, 0),
                "gain": None if before is None else totals[key] - before,
                "trend": None if was is None else "up" if ranks[key] < was else "down" if ranks[key] > was else "same",
                "gap": None if above is None else above - totals[key],
                "members": members.get(key, []),
                "mine": key == mine,
            })
            above = totals[key]
        first_chars = collections.Counter(label_of(r["tag"])[0] for r in rows)
        for r in rows:
            full = label_of(r["tag"])
            r["short"] = full if first_chars[full[0]] > 1 else full[0]
            if self.format == teams.FFA:
                r["short"] = r["tag"]
        return self._with_custom(rows)

    def clipboard_text(self, my_tag="", mark_mine=True):
        """`A 120 | B 98 | @7`, in FFA a line per player: `Leafeon 106`"""
        rows = self.standings(my_tag)
        if not rows:
            return ""
        if self.format == teams.FFA:
            return "\n".join(f"{r['tag']} {r['total']}" for r in rows)
        parts = []
        for r in rows:
            label = r["short"]
            if r["mine"] and mark_mine:
                label = f"**{label}**"
            parts.append(f"{label} {r['total']}")
        return " | ".join(parts) + f" | @{self.race_info()['left']}"

    def snapshot(self, my_tag=""):
        return {
            "lobby": self.lobby,
            "format": self.format,
            "formats": teams.formats_for(self.lobby),
            "race": self.race_info(),
            "teams": self.standings(my_tag),
            "suggestions": [{"id": s["id"], "kind": s["kind"], "text": s["text"], "button": s["button"]}
                            for s in self.suggestions],
            "format_hint": self.format_hint(),
            "undo": self.undo_label(),
        }
