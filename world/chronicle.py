"""Write the year's chronicles now, from the sandbox as it stands (no season is run).

    python -m world.chronicle            # the latest year, "so far" unless its winter is done

The same step the seasonal tick runs after winter (world/report.py write_year_chronicle): each chronicler in
config/rules.yaml writes the year as their house sees it. Earlier chronicles of the same year are kept in the
chronicles table (they are claims made at the time); the markdown file is rewritten.
"""

from __future__ import annotations

from world import report, tick as T
from world.db import connect, one
from world.llm import Instruct


def main() -> None:
    con = connect()
    R = T.load_rules()
    last = one(con, "select year, season from storyteller_proposals order by id desc limit 1")
    clock = T.Clock(con, last["year"], last["season"])
    llm = Instruct(R["storyteller"]["model"], dtype=R["storyteller"].get("dtype", "float32"))
    path = report.write_year_chronicle(con, llm, last["year"], last["season"], clock, complete=last["season"] == "winter", R=R)
    con.commit()
    print(f"{path} ({clock.calls} model calls)")


if __name__ == "__main__":
    main()
