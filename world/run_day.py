"""The world engine's nightly run: one day of the real world = one year of Corva (four seasons).

    python -m world.run_day                   # the year's remaining seasons, within the 2-hour ceiling
    python -m world.run_day --ceiling 3600    # a different ceiling, in seconds
    python -m world.run_day --no_git          # don't commit and push the reports

Run by a scheduled task at about 3:30 AM Central (sandbox only: it touches nothing of production; the
morning wallpaper is a separate job at 7:41). Steps:
  1. state: pull the sandbox file from the private model repo if this machine doesn't have it (a fresh
     cloud session never does), and the run 5 checkpoint (world/state.py);
  2. seasons: run world.run_season once per season, each in its own process (so every model's memory is
     given back between seasons), until the year ends with its winter, which also writes the year's
     chronicle. Before each season it checks the clock: a season is only started if, at the slowest
     pace seen so far (25 minutes before any is seen), it would finish inside the ceiling. What doesn't
     fit is left for the next night, and said so;
  3. after every season: the state is pushed back (a crash loses at most one season);
  4. at the end: the snapshot is published to the sandbox_* tables (world/publish.py), and the season
     logs and the year's chronicle are committed and pushed to main.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from world import state
from world.db import DB_PATH, ROOT, connect
from world.tick import next_time

FIRST_GUESS = 25 * 60     # seconds a season might take before one has been timed tonight
SAFETY = 5 * 60           # kept free at the end for the publish and the git push


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ceiling", type=int, default=7200, help="seconds the whole run may take (default: 2 hours)")
    ap.add_argument("--no_git", action="store_true")
    ap.add_argument("--max_seasons", type=int, default=4)
    args = ap.parse_args()
    t0 = time.time()
    if not DB_PATH.exists():
        state.pull()
    state.ensure_checkpoint()

    done, slowest, files = [], 0.0, []
    for _ in range(args.max_seasons):
        con = connect()
        year, season, tick = next_time(con)
        con.close()
        pace = slowest or FIRST_GUESS
        left = args.ceiling - (time.time() - t0) - SAFETY
        if pace > left:
            print(f"stopping before {season} of year {year}: it might take {pace / 60:.0f} min and {left / 60:.0f} min are left. "
                  f"It runs next night.", flush=True)
            break
        print(f"--- season {tick}: {season}, year {year} ({(time.time() - t0) / 60:.0f} min in)", flush=True)
        s0 = time.time()
        subprocess.run([sys.executable, "-m", "world.run_season"], cwd=ROOT, check=True)
        took = time.time() - s0
        slowest = max(slowest, took)
        done.append({"tick": tick, "season": season, "year": year, "minutes": round(took / 60, 1)})
        files.append(f"docs/season{tick}_log.md")
        if season == "winter":
            files.append(f"docs/chronicle_year{year}.md")
        state.push(f"world: after season {tick} ({season}, year {year})")
        if season == "winter":
            break                              # the year is done: one day, one year
    if done:
        subprocess.run([sys.executable, "-m", "world.publish"], cwd=ROOT, check=True)
    total = (time.time() - t0) / 60
    print(json.dumps({"seasons": done, "total_minutes": round(total, 1), "ceiling_minutes": args.ceiling / 60}), flush=True)
    if done and not args.no_git:
        git("add", *[f for f in files if (ROOT / f).exists()])
        last = done[-1]
        git("commit", "-m", f"World engine: {', '.join(d['season'] for d in done)} of year {last['year']} (nightly run, {total:.0f} min)")
        for attempt in range(4):
            try:
                git("pull", "--rebase", "origin", "main")
                git("push", "origin", "HEAD:main")
                print("reports pushed")
                break
            except subprocess.CalledProcessError as err:
                print(f"push failed ({err.stderr.strip()}); retrying", flush=True)
                time.sleep(2 ** (attempt + 1))
        else:
            sys.exit("could not push the reports (the state and the published snapshot are safe)")


if __name__ == "__main__":
    main()
