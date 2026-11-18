"""The sandbox's database: a local SQLite file mirroring the Supabase world tables.

World engine v0 runs offline: it never writes to Supabase, the wallpaper, the 3D world or the daily
job. Its tables have the same names and columns as the Supabase ones (supabase/migrations/
20261117_world_schema.sql and 20261118_houses.sql), so a later version can write there instead.
Lists (actors, houses...) are stored as JSON text; seasons as text.

Two small additions here that Supabase doesn't have yet (PROPOSED):
  relationships.kind also allows 'betrothed' and 'lover';
  memories.private marks character-only memories (the private truths): reports never print them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/world/sandbox.db"

SCHEMA = """
create table people (
  id integer primary key, year int, season text, name text not null, born_year int, died_year int,
  origin text, household text, openness real, caution real, warmth real, pride real, piety real,
  temperament text, need_hunger real, need_warmth real, need_safety real, need_belonging real, need_standing real,
  health real, place_id int, alive int not null default 1, promoted_from_crowd int not null default 0,
  tier text, dream_temperament text, absent int not null default 0, proposed int not null default 0, note text);
create table relationships (
  id integer primary key, year int, season text, person_a int not null, person_b int not null,
  kind text not null, strength real not null, formed_event int);
create table places (
  id integer primary key, year int, season text, name text not null, kind text, parent_id int,
  on_island int not null default 1, condition text);
create table objects (
  id integer primary key, year int, season text, kind text, description text, made_by int,
  owner_person int, owner_house int, location_place int, location_person int, condition text, made_event int);
create table houses (
  id integer primary key, year int, season text, name text not null unique, claim text not null, land text,
  land_kind text, seat_place_id int, head_id int, food real not null default 0, goods real not null default 0,
  materials real not null default 0, proposed int not null default 0);
create table house_members (
  id integer primary key, house_id int not null, person_id int not null, role text not null,
  joined_year int, joined_season text, left_year int, left_season text);
create table lineage (id integer primary key, parent_id int not null, child_id int not null, kind text not null);
create table house_clients (
  id integer primary key, year int not null, season text not null, house_id int, count int not null,
  loyalty real, gained int not null default 0, lost int not null default 0);
create table legends (
  id integer primary key, year int, season text, house_id int, title text not null, text text not null,
  events text not null default '[]', proposed int not null default 0);
create table storyteller_proposals (
  id integer primary key, year int not null, season text not null, tick int not null, house_id int,
  kind text not null, payload text not null, wording text, status text not null, reason text,
  rule_broken text, event_id int);
create table events (
  id integer primary key, year int not null, season text not null, kind text not null, place_id int,
  actors text not null default '[]', objects text not null default '[]', houses text not null default '[]',
  outcome text not null, facts text not null default '{}', text text not null, proposal_id int,
  sealed int not null default 0);
create table dreams (
  id text primary key, year int, season text, dreamer_id int, run text not null, kind text not null,
  tag text not null, prompt text, text text not null, recalled int, shared_with text not null default '[]',
  vividness real);
create table memories (
  id integer primary key, year int not null, season text not null, person_id int not null,
  source_type text not null, source_id text not null, told_by int, text text not null,
  vividness real not null, private int not null default 0);
create table beliefs (
  id integer primary key, year int not null, season text not null, holder_id int not null,
  subject_type text not null, subject_id text not null, interpretation text not null,
  confidence real not null, source_type text not null, source_person int, about_house int, stance real,
  history text not null default '[]');
create table townsfolk (
  id integer primary key, year int not null, season text not null, count int not null, births int default 0,
  deaths int default 0, mood real, food_share real);
create table vital_signs (year int not null, season text not null, stats text not null, primary key (year, season));
create table sealed_facts (key text primary key, value text not null);
create table runtimes (year int, season text, step text, seconds real, calls int);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def create(path: Path = DB_PATH) -> sqlite3.Connection:
    """A fresh, empty world (the old file, if any, is replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = connect(path)
    con.executescript(SCHEMA)
    return con


def insert(con: sqlite3.Connection, table: str, **row) -> int:
    row = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in row.items()}
    cur = con.execute(f"insert into {table} ({', '.join(row)}) values ({', '.join('?' * len(row))})", list(row.values()))
    return cur.lastrowid


def rows(con: sqlite3.Connection, sql: str, *args) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args)]


def one(con: sqlite3.Connection, sql: str, *args) -> dict | None:
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None
