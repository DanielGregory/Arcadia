"""Run the world engine sandbox for one season (offline: local SQLite only).

    python -m world.run_season --fresh      # genesis from the seed story, then one seasonal tick
    python -m world.run_season              # one more tick on the existing sandbox

Writes data/world/sandbox.db (git-ignored), docs/chronicle_season<N>.md and docs/season<N>_log.md.
Touches nothing else: not Supabase, not the wallpaper, not the 3D world, not the daily job.
"""

from __future__ import annotations

import argparse
import random
import time

from world import report, tick as T
from world.drives import compute_drives
from world.db import DB_PATH, connect
from world.genesis import genesis


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fresh", action="store_true", help="start again from genesis")
    ap.add_argument("--seed", type=int, default=1717)
    args = ap.parse_args()
    t0 = time.time()
    if args.fresh or not DB_PATH.exists():
        genesis(args.seed)
    con = connect()
    R = T.load_rules()
    year, season, tick = T.next_time(con)
    r = random.Random(args.seed * 100 + tick)
    print(f"tick {tick}: {season}, year {year}")
    clock = T.Clock(con, year, season)
    with clock.step("advance (yields, food, upkeep)"):
        fed = T.advance(con, R, year, season)
    with clock.step("dreams (run 5)"):
        dreams = T.dream_all(con, R, year, season, clock, r)
    with clock.step("recall and sharing"):
        remembered, shared = T.recall_and_share(con, R, dreams, r, year, season)
    with clock.step("drives"):
        drives = compute_drives(con, year, season)
    from world.llm import Instruct
    with clock.step("load interpreter (1.5B)"):
        small = Instruct(R["interpretation"]["model"])
    with clock.step("interpretations"):
        interp = T.interpret(con, R, shared, small, clock, year, season)
    small.free()
    with clock.step("load storyteller (3B)"):
        llm = Instruct(R["storyteller"]["model"])
    with clock.step("storyteller proposals"):
        items = T.propose(con, R, llm, clock, year, season, tick, drives)
    with clock.step("validation and events"):
        results = T.validate_and_record(con, R, items, year, season, tick, r)
    with clock.step("beliefs, feelings, clients"):
        T.update_clients(con, R, year, season, fed, r)
        T.fade_beliefs(con, R)
    stats = T.vital_signs(con, year, season, dreams, remembered, shared, interp, results, clock)
    con.commit()
    with clock.step("chronicle"):
        chron = report.write_chronicle(con, llm, year, season, tick, clock)
    raw_failures = [(it["house"]["name"], it["raw"]) for it in items if it["proposal"] is None]
    con.commit()
    log = report.write_log(con, year, season, tick, stats, interp, raw_failures)
    con.commit()
    print(f"done in {time.time() - t0:.0f} s: {chron}, {log}")


if __name__ == "__main__":
    main()
