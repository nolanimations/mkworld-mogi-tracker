"""Run the simulated mogis of test_session_normal.play() over many seeds and list the failures.

    python tests/sweep_session_normal.py               # seeds 0-299
    python tests/sweep_session_normal.py 1000 -v       # more seeds, print each failure
    python tests/sweep_session_normal.py --only 12p    # setups whose name contains "12p"
"""
import argparse
import collections
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_session_normal import play  # noqa: E402

SETUPS = {
    "24p partial=0.25": (24, ("2v2", "4v4", "6v6"), {"partial": 0.25}),
    "24p normal": (24, ("2v2", "4v4", "6v6"), {}),
    "12p normal": (12, ("2v2", "3v3", "6v6"), {}),
    "12p eleven=0.15": (12, ("2v2",), {"eleven": 0.15}),
}


def run_one(job):
    setup, lobby, fmt, seed, kw = job
    try:
        play(lobby, fmt, seed, **kw)
        return None
    except AssertionError as e:
        msg = str(e)
        kind = "suggestion" if "went from" in msg or "only add up" in msg or "took" in msg else "totals/other"
        return setup, fmt, seed, kind, msg[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", nargs="?", type=int, default=300)
    ap.add_argument("--only", default="")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    jobs = [(name, lobby, fmt, seed, kw) for name, (lobby, fmts, kw) in SETUPS.items() if args.only in name
            for fmt in fmts for seed in range(args.seeds)]
    with ProcessPoolExecutor() as pool:
        fails = [f for f in pool.map(run_one, jobs, chunksize=20) if f]
    runs = collections.Counter(j[0] for j in jobs)
    by_setup = collections.defaultdict(list)
    for f in fails:
        by_setup[f[0]].append(f)
    for name in SETUPS:
        if name not in runs:
            continue
        fs = by_setup[name]
        print(f"{name:18} {len(fs):3}/{runs[name]}  " +
              "  ".join(f"{fmt} {seed}" for _, fmt, seed, _, _ in sorted(fs, key=lambda f: (f[1], f[2]))))
        if args.verbose:
            for _, fmt, seed, kind, msg in fs:
                print(f"    {fmt} seed {seed} [{kind}]: {msg}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
