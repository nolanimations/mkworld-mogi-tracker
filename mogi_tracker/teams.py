"""Group the players of one leaderboard into teams by their tags.

Most rooms should group easily based on the first character of the name, but if they don't, the app scores a handful of alternative groupings against the chosen format and picks the best one
(this is often the case in tournaments)
"""
import collections
import difflib
import re
import unicodedata

TEAM_SIZES = {"2v2": 2, "3v3": 3, "4v4": 4, "6v6": 6, "8v8": 8, "12v12": 12}
LOBBY_SIZES = (24, 12)
TAG_SYMBOLS = set("#★☆")


def formats_for(lobby_size: int = 24) -> list[str]:
    return [fmt for fmt, size in TEAM_SIZES.items() if lobby_size % size == 0 and lobby_size // size >= 2]


def parse_team_format(team_format: str, lobby_size: int = 24):
    size = TEAM_SIZES.get(team_format, 4)
    return {"team_size": size, "expected_teams": lobby_size // size}


def upper_latin(s: str) -> str:
    """Capitalise Latin letters only, so "a" and "A" are one tag. Other scripts keep their own case: a capital
    can look like a different letter (Greek μ becomes Μ, which reads as M)"""
    return "".join(c.upper() if c.isascii() or "LATIN" in unicodedata.name(c, "") else c for c in s)


def get_first_char_key(name: str) -> str:
    if not name:
        return "?"
    s = str(name).strip()
    if not s:
        return "?"
    return upper_latin(s[0])


def extract_tokens(name: str) -> list[str]:
    if not name:
        return []

    tokens = []
    current = []
    for ch in str(name).strip():
        if ch.isalnum() or ch in TAG_SYMBOLS:
            current.append(ch)
        elif current:
            tokens.append(upper_latin("".join(current)))
            current = []

    if current:
        tokens.append(upper_latin("".join(current)))

    return tokens


def extract_leading_token(name: str) -> str:
    tokens = extract_tokens(name)
    return tokens[0] if tokens else ""


def extract_trailing_token(name: str) -> str:
    tokens = extract_tokens(name)
    return tokens[-1] if tokens else ""


def suffix_key(token: str, length: int) -> str:
    if not token:
        return ""
    token = str(token)
    return token[-length:] if len(token) >= length else token


def longest_common_suffix(a: str, b: str) -> str:
    a = str(a or "")
    b = str(b or "")
    i = 0
    max_len = min(len(a), len(b))
    while i < max_len and a[-(i + 1)] == b[-(i + 1)]:
        i += 1
    if i == 0:
        return ""
    return a[-i:]


def numeric_suffix_signature(token: str) -> str:
    token = str(token or "")
    for idx, ch in enumerate(token):
        if ch.isdigit():
            suffix = token[idx:]
            if len(suffix) >= 4:
                return suffix
            return ""
    return ""


def bucket_by(players, key_fn):
    grouped = collections.defaultdict(list)
    for player in players:
        key = key_fn(player) or "?"
        grouped[key].append(player)
    return grouped


def similarity_score(key_a: str, key_b: str) -> float:
    a = str(key_a or "")
    b = str(key_b or "")
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    bonus = 0.0
    if a and b and a[0] == b[0]:
        bonus += 0.2
    if a in b or b in a:
        bonus += 0.2
    return ratio + bonus


def dominant_leading_token(members) -> str:
    tokens = [extract_leading_token(p.get("full_name")) for p in members]
    tokens = [t for t in tokens if t]
    if not tokens:
        return ""
    return collections.Counter(tokens).most_common(1)[0][0]


def merge_groups_by_numeric_suffix(grouping):
    merged = {k: list(v) for k, v in grouping.items() if v}
    keys = list(merged.keys())
    if len(keys) < 2:
        return merged, False

    group_tokens = {k: dominant_leading_token(merged[k]) for k in keys}
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            k1 = keys[i]
            k2 = keys[j]
            t1 = group_tokens.get(k1, "")
            t2 = group_tokens.get(k2, "")
            if not t1 or not t2:
                continue

            common_suffix = longest_common_suffix(t1, t2)
            if len(common_suffix) >= 4 and any(ch.isdigit() for ch in common_suffix):
                union(k1, k2)

    components = collections.defaultdict(list)
    for key in keys:
        components[find(key)].append(key)

    if all(len(component) == 1 for component in components.values()):
        return merged, False

    out = {}
    for root, component_keys in components.items():
        primary_key = max(component_keys, key=lambda k: len(merged[k]))
        members = []
        for component_key in component_keys:
            members.extend(merged[component_key])
        out[primary_key] = members

    return out, True


def shared_prefix_label(names) -> str:
    """Longest prefix shared by at least half the team (min 2 players)"""
    compact = [upper_latin("".join(n.split())) for n in names]
    if len(compact) < 2:
        return ""
    needed = max(2, (len(compact) + 1) // 2)

    best = ""
    for length in range(1, max(len(c) for c in compact) + 1):
        counts = collections.Counter(c[:length] for c in compact if len(c) >= length)
        supported = [p for p, count in counts.items() if count >= needed]
        if not supported:
            break
        best = min(supported, key=lambda p: (-counts[p], p))
    return best.rstrip("-_.|/")


def team_label_for_group(players, fallback_key: str) -> str:
    names = sorted(str(p.get("full_name", "")).strip() for p in players if p.get("full_name"))
    if not names:
        return fallback_key

    lead_tokens = [extract_leading_token(n) for n in names]
    lead_tokens = [t for t in lead_tokens if t]

    # Prefer if members share a suffix tag
    if len(lead_tokens) >= 2:
        suffix_counter = collections.Counter()
        for token in lead_tokens:
            max_len = min(6, len(token))
            for n in range(2, max_len + 1):
                suffix_counter[token[-n:]] += 1

        if suffix_counter:
            best_suffix, best_count = max(
                suffix_counter.items(),
                key=lambda item: (item[1] * len(item[0]), item[1], len(item[0]), item[0]),
            )
            if best_count >= 2 and len(best_suffix) >= 3:
                return best_suffix

    prefix = shared_prefix_label(names)
    if prefix:
        return prefix

    if lead_tokens:
        top_token = min(collections.Counter(lead_tokens).items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if len(top_token) <= 8:
            return top_token

    prefixes = [upper_latin(n[:3]) for n in names if len(n) >= 3]
    if prefixes:
        return min(collections.Counter(prefixes).items(), key=lambda kv: (-kv[1], kv[0]))[0]

    return names[0]


def score_grouping(grouping, expected_teams: int, team_size: int) -> float:
    sizes = [len(v) for v in grouping.values() if v]
    if not sizes:
        return float("inf")

    count_penalty = abs(len(sizes) - expected_teams) * 6.0
    size_penalty = sum(abs(size - team_size) for size in sizes) / len(sizes)
    singleton_penalty = sum(1 for size in sizes if size == 1) * 0.6
    oversized_penalty = sum(max(0, size - (team_size + 1)) for size in sizes) * 1.5

    # Prefer keeping long numeric-suffix tags together
    suffix_to_groups = collections.Counter()
    for members in grouping.values():
        token = dominant_leading_token(members)
        signature = numeric_suffix_signature(token)
        if signature:
            suffix_to_groups[signature] += 1

    suffix_split_penalty = sum((count - 1) * 3.5 for count in suffix_to_groups.values() if count > 1)

    return count_penalty + size_penalty + singleton_penalty + oversized_penalty + suffix_split_penalty


def should_run_refinement(grouping, expected_teams: int, team_size: int) -> bool:
    if len(grouping) != expected_teams:
        return True

    sizes = [len(v) for v in grouping.values() if v]
    if not sizes:
        return False

    # Keep default behavior stable unless the grouping shape is suspicious
    avg_delta = sum(abs(size - team_size) for size in sizes) / len(sizes)

    if team_size <= 3 and avg_delta >= 0.75:
        return True

    return False


def name_affinity(player, members) -> float:
    name = str(player.get("full_name", ""))
    return max((similarity_score(name, str(m.get("full_name", ""))) for m in members), default=0.0)


def merge_to_expected(grouping, expected_teams: int, team_size: int):
    merged = {k: list(v) for k, v in grouping.items() if v}

    while len(merged) > expected_teams:
        source_key = min(merged.keys(), key=lambda k: (len(merged[k]), k))
        source_members = merged.pop(source_key)

        for player in source_members:
            best_target = max(
                sorted(merged),
                key=lambda k: (team_size - len(merged[k]), name_affinity(player, merged[k])),
            )
            merged[best_target].append(player)

    return merged


def split_bucket_members(bucket_members, team_size: int):
    if len(bucket_members) <= team_size + 1:
        return None

    candidates = [
        bucket_by(bucket_members, lambda p: extract_leading_token(p.get("full_name"))[:2] or get_first_char_key(p.get("full_name"))),
        bucket_by(bucket_members, lambda p: extract_leading_token(p.get("full_name"))[:3] or get_first_char_key(p.get("full_name"))),
        bucket_by(bucket_members, lambda p: extract_trailing_token(p.get("full_name"))[:2] or get_first_char_key(p.get("full_name"))),
        bucket_by(bucket_members, lambda p: extract_trailing_token(p.get("full_name"))[:3] or get_first_char_key(p.get("full_name"))),
    ]

    best = None
    best_score = float("inf")
    expected_subteams = max(2, round(len(bucket_members) / max(team_size, 1)))

    for candidate in candidates:
        if len(candidate) <= 1:
            continue

        sizes = [len(v) for v in candidate.values()]
        if all(size == 1 for size in sizes):
            continue

        candidate_score = score_grouping(candidate, expected_subteams, team_size)
        if candidate_score < best_score:
            best = candidate
            best_score = candidate_score

    return best


def split_to_expected(grouping, expected_teams: int, team_size: int):
    result = {k: list(v) for k, v in grouping.items() if v}

    while len(result) < expected_teams:
        split_key = None
        for key, members in sorted(result.items(), key=lambda item: len(item[1]), reverse=True):
            if len(members) > team_size:
                split_key = key
                break

        if not split_key:
            break

        sub_groups = split_bucket_members(result[split_key], team_size)
        if not sub_groups:
            break

        del result[split_key]
        for sub_key, sub_members in sub_groups.items():
            result[f"{split_key}:{sub_key}"] = sub_members

    return result


def normalize_grouping(grouping, expected_teams: int, team_size: int):
    normalized = {k: list(v) for k, v in grouping.items() if v}

    if len(normalized) > expected_teams:
        normalized = merge_to_expected(normalized, expected_teams, team_size)
    elif len(normalized) < expected_teams:
        normalized = split_to_expected(normalized, expected_teams, team_size)

    return normalized


def assign_final_teams(grouping):
    used = set()
    for key in sorted(grouping):
        members = grouping[key]
        label = team_label_for_group(members, key)
        # Two teams with one label would be merged into one row
        base, n = label, 2
        while upper_latin("".join(label.split())) in used:
            label, n = f"{base}{n}", n + 1
        used.add(upper_latin("".join(label.split())))
        for player in members:
            player["final_team"] = label


def suggest_team_format(names, selected_format: str, lobby_size: int = 24):
    sizes = [len(v) for v in bucket_by([{"full_name": n} for n in names], lambda p: get_first_char_key(p["full_name"])).values()]
    for fmt in formats_for(lobby_size):
        info = parse_team_format(fmt, lobby_size)
        if fmt != selected_format and len(sizes) == info["expected_teams"] and all(s == info["team_size"] for s in sizes):
            return fmt
    return None


def build_players(raw_data):
    """[{"full_name", "white_score", "green_score"}]."""
    players = []
    for player in raw_data:
        p = dict(player)
        p["final_team"] = None
        players.append(p)
    return players


def group_teams_first_char_primary(raw_data, team_format="4v4", lobby_size=24):
    format_info = parse_team_format(team_format, lobby_size)
    team_size = format_info["team_size"]
    expected_teams = format_info["expected_teams"]

    players = build_players(raw_data)

    first_char_groups = bucket_by(players, lambda p: get_first_char_key(p.get("full_name")))
    base_score = score_grouping(first_char_groups, expected_teams, team_size)
    started_at_expected_count = len(first_char_groups) == expected_teams
    refinement_needed = should_run_refinement(first_char_groups, expected_teams, team_size)

    suffix_merged_groups = None
    did_suffix_merge = False
    if team_size <= 3:
        suffix_merged_groups, did_suffix_merge = merge_groups_by_numeric_suffix(first_char_groups)
        if did_suffix_merge:
            refinement_needed = True

    # Fast
    if not refinement_needed:
        assign_final_teams(first_char_groups)
    else:
        # Only do this on mismatch
        candidates = [("first-char", first_char_groups)]
        if did_suffix_merge and suffix_merged_groups:
            candidates.append(("numeric-suffix-merge", suffix_merged_groups))

        candidates.extend(
            [
                ("lead-2", bucket_by(players, lambda p: extract_leading_token(p.get("full_name"))[:2] or get_first_char_key(p.get("full_name")))),
                ("lead-3", bucket_by(players, lambda p: extract_leading_token(p.get("full_name"))[:3] or get_first_char_key(p.get("full_name")))),
                ("trail-2", bucket_by(players, lambda p: extract_trailing_token(p.get("full_name"))[:2] or get_first_char_key(p.get("full_name")))),
                ("trail-3", bucket_by(players, lambda p: extract_trailing_token(p.get("full_name"))[:3] or get_first_char_key(p.get("full_name")))),
                (
                    "suffix-4",
                    bucket_by(
                        players,
                        lambda p: suffix_key(extract_leading_token(p.get("full_name")), 4) or get_first_char_key(p.get("full_name")),
                    ),
                ),
                (
                    "suffix-5",
                    bucket_by(
                        players,
                        lambda p: suffix_key(extract_leading_token(p.get("full_name")), 5) or get_first_char_key(p.get("full_name")),
                    ),
                ),
            ]
        )

        best_grouping = None
        best_score = float("inf")

        for candidate_name, candidate in candidates:
            adjusted = normalize_grouping(candidate, expected_teams, team_size)
            # Recheck count stability
            adjusted = normalize_grouping(adjusted, expected_teams, team_size)

            if len(adjusted) != expected_teams:
                continue

            candidate_score = score_grouping(adjusted, expected_teams, team_size)

            # If mogi started at expected team count, don't accept a player
            # that required forced rebalance unless it actually improves grouping quality
            if started_at_expected_count and len(candidate) != expected_teams and candidate_score >= base_score:
                continue

            if candidate_score < best_score:
                best_grouping = adjusted
                best_score = candidate_score

        if not best_grouping:
            best_grouping = first_char_groups

        assign_final_teams(best_grouping)

    output = []
    for player in players:
        if not player["final_team"]:
            player["final_team"] = player["full_name"]

        player["final_team"] = str(player["final_team"]).strip()
        total = player["white_score"] + player["green_score"]
        output.append(
            {
                "team_identifier": player["final_team"],
                "name": player["full_name"],
                "total_score": total,
            }
        )

    return output
