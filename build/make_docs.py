# Regenerate the README pictures (docs/app.png, docs/overlay.png)
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mogi_tracker import __version__  # noqa: E402
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
BROWSER = next((b for b in BROWSERS if Path(b).is_file()), BROWSERS[-1])
PORT = 12431

TEAMS = {tag: [f"Player {i * 4 + n}" for n in range(1, 5)] for i, tag in enumerate("ABCDEF")}
RACE = 4
TABLE = [15, 12, 10, 9, 9, 8, 8, 7, 7, 6, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 1]


def board(totals):
    return [{"full_name": n, "white_score": t, "green_score": 0} for n, t in totals.items()]


def race(totals, order):
    """Totals after a race finished in `order` (best first); players stay listed in their own order."""
    points = dict(zip(order, TABLE))
    return {n: totals.get(n, 0) + points[n] for n in sorted(order, key=lambda n: int(n.split()[1]))}


def main():
    started = time.time()
    data = Path(tempfile.mkdtemp(prefix="mogi_docs_"))
    (data / "settings.json").write_text(json.dumps(
        {"hotkey": "", "lobby": 24, "format": "4v4", "my_tag": "B", "port": PORT, "last_version": __version__}),
        encoding="utf-8")
    os.environ["MKW_TRACKER_DATA_DIR"] = str(data)

    from mogi_tracker import server
    from mogi_tracker.controller import Controller

    controller = Controller()
    server.start(controller)
    names = [n for members in TEAMS.values() for n in members]
    team_of = {n: tag for tag, members in TEAMS.items() for n in members}
    controller.session._group = lambda players: [
        {"team_identifier": team_of[p["full_name"]], "name": p["full_name"],
         "total_score": p["white_score"] + p["green_score"]} for p in players]
    strength = {n: i // 4 * 0.22 + random.Random(i).random() * 2.5 for i, n in enumerate(names)}
    totals = {}
    for r in range(RACE - 1):
        rng = random.Random(100 + r)
        totals = race(totals, sorted(names, key=lambda n: strength[n] + rng.random() * 3))
    for seed in range(500):
        session = controller.session
        session.reset()
        session.apply_capture(board(totals))
        last = names[:]
        random.Random(seed).shuffle(last)
        session.apply_capture(board(race(totals, last)))
        trends = [t["trend"] for t in session.standings()]
        if trends.count("up") >= 1 and trends.count("down") >= 1 and trends.count("same") >= 2:
            break
    else:
        raise SystemExit("no shuffle moved teams both up and down")
    controller.session._undo.clear()
    controller.changed()

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    base = [BROWSER, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1.5",
            "--virtual-time-budget=4000", f"--user-data-dir={data / 'edge'}"]
    url = f"http://127.0.0.1:{controller.port}"
    subprocess.run(base + ["--window-size=1040,760", f"--screenshot={docs / 'app.png'}", url + "/?once"], check=True, timeout=60)
    # the other two backgrounds, as smaller previews
    for theme in ("blue", "light"):
        controller.settings["background"] = theme
        subprocess.run(base + ["--window-size=1040,760", f"--screenshot={docs / f'app-{theme}.png'}", url + "/?once"],
                       check=True, timeout=60)
    controller.settings["background"] = "dark"
    subprocess.run(base + ["--window-size=886,118", "--default-background-color=00000000",
                           f"--screenshot={docs / 'overlay.png'}", url + "/overlay?once&layout=bar"], check=True, timeout=60)
    subprocess.run(base + ["--window-size=230,364", "--default-background-color=00000000",
                           f"--screenshot={docs / 'overlay-list.png'}", url + "/overlay?once&layout=list"], check=True, timeout=60)
    controller.close()
    stale = [p.name for p in sorted(docs.glob("*.png")) if p.stat().st_mtime < started]
    if stale:
        raise SystemExit(f"the browser didn't write {stale}")
    print("wrote", [p.name for p in sorted(docs.glob("*.png"))])


if __name__ == "__main__":
    main()
