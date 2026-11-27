"""old session logic that was pretty bad at DCs, can still be configured in config.json if the new one is even worse. it all depends on how many dc's there are in any given mogi and how complex they are.
may delete this if the new logic proves its worth"""
import collections
import copy
import difflib
import math
import re
import unicodedata

from . import teams
from .session import AutoSetup, CustomTags

TOTAL_RACES = 12
POINTS_PER_RACE = {24: 144, 12: 82}
# 11p race (dc with no bot)
TABLE_11P = [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
UNDO_DEPTH = 20
NAME_MATCH = 0.7

_FOLD = str.maketrans({"l": "I", "0": "O"})


def label_of(tag) -> str:
    return teams.upper_latin(re.sub(r"\s+", "", str(tag or ""))) or "?"


def team_key(tag) -> str:
    return teams.upper_latin(re.sub(r"\s+", "", str(tag or "")).translate(_FOLD)) or "?"


def player_key(name) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or ""))).translate(_FOLD).casefold()


class Session(CustomTags, AutoSetup):
    _FIELDS = ("lobby", "format", "bank", "live", "display", "members", "last_players", "prev_totals", "prev_ranks",
               "roster", "absent", "suggestions", "custom", "format_auto", "format_vote")

    def __init__(self, lobby=24, fmt="4v4", races=TOTAL_RACES):
        self.lobby = lobby
        self.format = fmt
        self.races = races          # races in this mogi (tournaments: 8, 16, ...)
        self._undo = []
        self._clear()

    def _clear(self):
        self.bank = {}
        self.live = {}
        self.display = {}
        self.custom = {}
        self.members = {}
        self.last_players = []
        self.prev_totals = None 
        self.prev_ranks = None
        self.roster = []
        self.absent = {}
        self.suggestions = []
        self.format_auto = None
        self.format_vote = None

    # undo
    def _push_undo(self, label):
        self._undo.append((label, {f: copy.deepcopy(getattr(self, f)) for f in self._FIELDS}))
        del self._undo[:-UNDO_DEPTH]

    def undo(self):
        if not self._undo:
            return None
        label, state = self._undo.pop()
        for f, value in state.items():
            setattr(self, f, value)
        return label

    def undo_label(self):
        return self._undo[-1][0] if self._undo else None

    # totals
    def keys(self):
        return set(self.live) | set(self.bank)

    def total(self, key):
        return self.live.get(key, 0) + self.bank.get(key, 0)

    def _totals(self):
        return {k: self.total(k) for k in self.keys()}

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
    def set_lobby(self, lobby, undo=True):
        if lobby == self.lobby:
            return
        if undo:
            self._push_undo("room size")
        self.lobby = lobby
        if self.format not in teams.formats_for(lobby):
            self.format = "4v4"
        self.last_players, self.roster, self.absent = [], [], {}

    def set_format(self, fmt, undo=True):
        if fmt == self.format or fmt not in teams.formats_for(self.lobby):
            return
        if undo:
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

    def _apply_grouped(self, grouped):
        self.live, self.members = {}, {}
        for p in grouped:
            tag = p.get("team_identifier") or "NoTag"
            key = team_key(tag)
            # keep the longest reading of a tag: "Splash" beats "S"
            if key not in self.display or len(tag) > len(self.display[key]):
                self.display[key] = tag
            self.live[key] = self.live.get(key, 0) + p["total_score"]
            self.members.setdefault(key, []).append({"name": p["name"], "total": p["total_score"]})

    def _regroup(self):
        if not self.last_players:
            return
        players = [{"full_name": p["name"], "white_score": p["total"], "green_score": 0} for p in self.last_players]
        grouped = self._group(players)
        self._apply_grouped(grouped)
        self.roster = self._roster_of(grouped)

    @staticmethod
    def _roster_of(grouped):
        return [{"name": p["name"], "pk": player_key(p["name"]), "total": p["total_score"],
                 "key": team_key(p.get("team_identifier") or "NoTag")} for p in grouped]

    def apply_capture(self, players, tidy_board=True, lobby=None, auto_format=False):
        self._push_undo("capture")
        self._auto_setup(players, lobby, auto_format)
        grouped = self._group(players)
        totals_before, ranks_before, live_before = self._totals(), self._ranks(), dict(self.live)
        had_scores = any(totals_before.values())
        self._apply_grouped(grouped)
        self.last_players = [{"name": p["name"], "total": p["total_score"]} for p in grouped]
        self.prev_totals = totals_before if had_scores else None
        self.prev_ranks = ranks_before if had_scores else None
        new_roster = self._roster_of(grouped)
        self._notice(new_roster, live_before, tidy_board)
        self.roster = new_roster

    def same_board(self, players):
        if not self.last_players:
            return False
        new = sorted(p["white_score"] + p["green_score"] for p in players)
        return new == sorted(p["total"] for p in self.last_players)

    # DCs
    def _suggest(self, sid, kind, text, button, adds):
        self.suggestions = [s for s in self.suggestions if s["id"] != sid]
        self.suggestions.append({"id": sid, "kind": kind, "text": text, "button": button, "adds": adds})

    def _tag(self, key):
        return self.display.get(key, key)

    def _notice(self, new, live_before, tidy_board):
        on_board_before = {p["pk"] for p in self.roster}
        prev = self.roster + [p for pk, p in self.absent.items() if pk not in on_board_before]
        if not prev:
            return

        def by_pk(players):
            d = collections.defaultdict(list)
            for p in players:
                d[p["pk"]].append(p)
            return d

        prev_by, new_by = by_pk(prev), by_pk(new)
        twins = {pk for pk, ps in list(prev_by.items()) + list(new_by.items()) if len(ps) > 1}
        pairs = [(prev_by[pk][0], new_by[pk][0]) for pk in prev_by if pk in new_by and pk not in twins]
        lost = [prev_by[pk][0] for pk in prev_by if pk not in new_by and pk not in twins]
        fresh = [new_by[pk][0] for pk in new_by if pk not in prev_by and pk not in twins]
        alike = sorted(((difflib.SequenceMatcher(None, a["pk"], b["pk"]).ratio(), i, j)
                        for i, a in enumerate(lost) for j, b in enumerate(fresh)), reverse=True)
        used_i, used_j = set(), set()
        for ratio, i, j in alike:
            if ratio < NAME_MATCH:
                break
            if i not in used_i and j not in used_j:
                used_i.add(i), used_j.add(j)
                pairs.append((lost[i], fresh[j]))
        if self.lobby == 12:
            # nobody new joins a 12p room mid-mogi: a name that wasn't there before is a misread (or a sub), so it
            # belongs to the closest name that went missing. Otherwise one bad read hides an 11p race or a leaver
            for ratio, i, j in alike:
                if i not in used_i and j not in used_j:
                    used_i.add(i), used_j.add(j)
                    pairs.append((lost[i], fresh[j]))
        lost = [p for i, p in enumerate(lost) if i not in used_i]
        fresh = [p for j, p in enumerate(fresh) if j not in used_j]

        drops = [(a, b) for a, b in pairs if b["total"] < a["total"] and not a.get("banked")]
        if len(drops) >= max(3, math.ceil(len(pairs) / 2)):
            adds = [{"key": k, "points": pts} for k, pts in live_before.items() if pts]
            self._suggest("room", "room", "Most totals went back down, looks like reopen? "
                          f"The old room's {sum(live_before.values())} points are not banked yet",
                          "Bank old room", adds)
            drops = []
        for a, b in drops:
            self._suggest(f"pts:{b['pk']}", "rejoin",
                          f"{b['name']} went from {a['total']} to {b['total']}, looks like a DC?"
                          f"They seem to be missing {a['total']} points",
                          f"Bank {a['total']} for {self._tag(b['key'])}",
                          [{"name": b["name"], "key": b["key"], "points": a["total"]}])

        gone_now = [p for p in lost if p["pk"] in on_board_before]
        left_room = (self.lobby == 12 and tidy_board and len(new) < 12 and not fresh and not twins and gone_now)
        if left_room:
            for p in gone_now:
                self._suggest(f"pts:{p['pk']}", "left",
                              f"{p['name']} is no longer on the board and had {p['total']} points.",
                              f"Bank {p['total']} for {self._tag(p['key'])}",
                              [{"name": p["name"], "key": p["key"], "points": p["total"]}])

        if self.lobby == 12 and not twins and not fresh and not drops:
            gains = [(b, b["total"] - a["total"]) for a, b in pairs if b["total"] >= a["total"]]
            scored = sorted((g for _, g in gains if g > 0), reverse=True)
            idle = [b for b, g in gains if g == 0] + lost
            if scored == TABLE_11P and len(idle) == 1:
                first = next(b for b, g in gains if g == 12)
                second = next(b for b, g in gains if g == 10)
                adds = [{"name": b["name"], "key": b["key"], "points": 3 if b is first else 2 if b is second else 1}
                        for b, g in gains if g > 0]
                adds.append({"name": idle[0]["name"], "key": idle[0]["key"], "points": 1})
                self._suggest("comp11", "comp11",
                              f"Looks like an 11 player race. The usual correction is "
                              f"+3 for 1st ({first['name']}), +2 for 2nd ({second['name']}) and +1 for everyone else.",
                              "Add 15 points", adds)

        self.absent = {p["pk"]: p for p in lost}

    def _team_of(self, add):
        if add.get("name"):
            pk = player_key(add["name"])
            for key, members in self.members.items():
                if any(player_key(m["name"]) == pk for m in members):
                    return key
        return add["key"]

    def apply_suggestion(self, sid):
        s = next((s for s in self.suggestions if s["id"] == sid), None)
        if not s:
            return None
        self._push_undo(s["button"][0].lower() + s["button"][1:])
        for add in s["adds"]:
            key = self._team_of(add)
            self.bank[key] = self.bank.get(key, 0) + add["points"]
            self.display.setdefault(key, key)
        if s["kind"] in ("left", "rejoin"):
            pk = s["id"].split(":", 1)[1]
            if pk in self.absent:
                self.absent[pk]["banked"] = True
        self.suggestions = [x for x in self.suggestions if x["id"] != sid]
        return s

    def accept_corrections(self):
        return []

    def dismiss_suggestion(self, sid):
        self.suggestions = [s for s in self.suggestions if s["id"] != sid]

    # bank
    def bank_all(self):
        if not any(self.live.values()):
            return False
        self._push_undo("bank all")
        for key, pts in self.live.items():
            self.bank[key] = self.bank.get(key, 0) + pts
        self.live, self.members, self.last_players, self.roster, self.absent = {}, {}, [], [], {}
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
        if starts:
            return "ambiguous", [self._tag(k) for k in starts]
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
        totals = {k: t for k, t in self._totals().items() if t != 0}
        ranks = self._ranks(totals)
        mine = self.resolve_tag(my_tag)[1] if my_tag else None
        mine = mine if isinstance(mine, str) else None
        rows, above = [], None
        for key in sorted(totals, key=lambda k: (-totals[k], k)):
            before = self.prev_totals.get(key) if self.prev_totals else None
            was = self.prev_ranks.get(key) if self.prev_ranks else None
            rows.append({
                "key": key,
                "tag": self._tag(key),
                "rank": ranks[key],
                "total": totals[key],
                "live": self.live.get(key, 0),
                "bank": self.bank.get(key, 0),
                "gain": None if before is None else totals[key] - before,
                "trend": None if was is None else "up" if ranks[key] < was else "down" if ranks[key] > was else "same",
                "gap": None if above is None else above - totals[key],
                "members": self.members.get(key, []),
                "mine": key == mine,
            })
            above = totals[key]
        first_chars = collections.Counter(r["key"][0] for r in rows)
        for r in rows:
            full = label_of(r["tag"])
            r["short"] = full if first_chars[r["key"][0]] > 1 else full[0]
        return self._with_custom(rows)

    def indivs_text(self):
        blocks = []
        for row in self.standings():
            people = sorted(self.members.get(row["key"], []), key=lambda m: -m["total"])
            lines = [f"{m['name']} {m['total']}" for m in people]
            extra = self.bank.get(row["key"], 0)
            if extra:
                lines.append(f"{'Penalty' if extra < 0 else 'Bonus'} {extra:+}")
            blocks.append(lines if self.format == teams.FFA else [row["tag"]] + lines)
        if self.format == teams.FFA:
            return "\n".join(line for block in blocks for line in block)
        return "\n\n".join("\n".join(block) for block in blocks)

    def clipboard_text(self, my_tag="", mark_mine=True):
        """`A 120 | B 98 | @7`"""
        rows = self.standings(my_tag)
        if not rows:
            return ""
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
            "format_auto": self.format_auto,
            "captured": bool(self.last_players),
            "undo": self.undo_label(),
        }
