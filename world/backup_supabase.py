"""Back up every table in Supabase's public schema to data/backups/supabase_<UTC time>/<table>.json.

    python world/backup_supabase.py

Reads the table list from the REST API's own description of itself, then pages through each table
(Supabase returns at most 1000 rows per request). Run before any migration. Data files stay out of git
(data/ is ignored); the folder name is printed so it can be noted in the migration's header.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily"))
from memory_sync import client, select  # noqa: E402


def main() -> None:
    sb = client()
    spec = sb.session.get(f"{sb.url}/rest/v1/", timeout=60).json()
    tables = sorted(p.strip("/") for p in spec.get("paths", {}) if p.count("/") == 1 and p != "/" and not p.startswith("/rpc"))
    out = ROOT / "data/backups" / f"supabase_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%MZ}"
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for t in tables:
        rows = select(sb, f"{t}?select=*")
        (out / f"{t}.json").write_text(json.dumps(rows, ensure_ascii=False, default=str), encoding="utf-8")
        total += len(rows)
        print(f"  {t:28s} {len(rows):6d} rows")
    print(f"backed up {len(tables)} tables, {total} rows -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
