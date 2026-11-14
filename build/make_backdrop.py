import math
import random
from pathlib import Path

TILE = 480
SEED = 24
WEB = Path(__file__).resolve().parent.parent / "mogi_tracker" / "web"

CLASSES = [((23, 30), 20, 10), ((13, 18), 30, 8), ((5, 9), 55, 7)]


def pebble(rng, cx, cy, r):
    sides = rng.choices((3, 4, 5), weights=(6, 3, 1))[0]
    turn = rng.uniform(0, 2 * math.pi)
    pts = []
    for k in range(sides):
        a = turn + 2 * math.pi * k / sides + rng.uniform(-0.25, 0.25)
        d = r * rng.uniform(0.85, 1.15)
        pts.append((cx + d * math.cos(a), cy + d * math.sin(a)))
    cut = rng.uniform(0.2, 0.3)

    def towards(a, b, t):
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t

    path = ""
    for k, p in enumerate(pts):
        before, after = pts[k - 1], pts[(k + 1) % sides]
        start, end = towards(p, before, cut), towards(p, after, cut)
        path += f"{'M' if not path else 'L'}{start[0]:.1f} {start[1]:.1f}Q{p[0]:.1f} {p[1]:.1f} {end[0]:.1f} {end[1]:.1f}"
    return path + "Z"


def wrapped_gap(a, b):
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return math.hypot(min(dx, TILE - dx), min(dy, TILE - dy))


def place(rng):
    placed = []
    for (lo, hi), tries, gap in CLASSES:
        for _ in range(tries * 40):
            if sum(1 for p in placed if lo <= p[2] <= hi) >= tries:
                break
            r = rng.uniform(lo, hi)
            spot = (rng.uniform(0, TILE), rng.uniform(0, TILE))
            if all(wrapped_gap(spot, p) > r * 1.18 + p[2] * 1.18 + gap for p in placed):
                placed.append((*spot, r))
    return placed


def tile_svg(fill, shapes):
    paths = []
    for path in shapes:
        paths.append(f'<path d="{path}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{TILE}" height="{TILE}" viewBox="0 0 {TILE} {TILE}">'
            f'<g fill="{fill}">{"".join(paths)}</g></svg>\n')


def main():
    rng = random.Random(SEED)
    shapes = []
    for x, y, r in place(rng):
        reach = r * 1.25
        xs = [x] + ([x + TILE] if x - reach < 0 else []) + ([x - TILE] if x + reach > TILE else [])
        ys = [y] + ([y + TILE] if y - reach < 0 else []) + ([y - TILE] if y + reach > TILE else [])
        shape_rng = random.Random(rng.random())   # the same pebble on every side it wraps to
        state = shape_rng.getstate()
        for px in xs:
            for py in ys:
                shape_rng.setstate(state)
                shapes.append(pebble(shape_rng, px, py, r))
    for name, fill in (("pattern-white.svg", "#fff"), ("pattern-ink.svg", "#14204a")):
        (WEB / name).write_text(tile_svg(fill, shapes), encoding="utf-8")
    old = WEB / "backdrop.svg"
    if old.exists():
        old.unlink()
    print(f"wrote {len(shapes)} shapes into pattern-white.svg and pattern-ink.svg")


if __name__ == "__main__":
    main()
