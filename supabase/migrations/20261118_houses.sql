-- =====================================================================================
-- Houses, membership, lineage, clients, legends, and the sealed record (world engine v2).
-- From docs/world_engine.md (spec v2) and docs/seed_history.md.
-- APPLIED 2026-11-18 (backup first: data/backups/supabase_20261118T1343Z, by python world/backup_supabase.py).
-- Additive only: new tables, new columns, a view. Nothing dropped or rewritten.
-- Undo: rollback_houses.sql.
--
-- The hard rule still holds: these tables hold facts (who belongs to which house, who is whose
-- child, how many clients a house has and how loyal they are, what a house claims by right).
-- How houses FEEL about each other is not stored: it is the view house_feelings, computed from
-- the members' beliefs. A legend is an attributed account (like a chronicle), labelled with the
-- house that tells it, never a statement of what happened.
-- =====================================================================================

-- 1. HOUSES: the ten landed families. Facts only: land, seat, the right each holds, stores.
create table public.houses (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,
  name text not null unique,                            -- "Corvane"
  claim text not null,                                  -- its one hereditary claim: a right, e.g. "the council seat"
  land text,                                            -- what it holds: "olive and vineyard land in the hills"
  seat_place_id bigint references public.places(id),
  head_id bigint references public.people(id),
  food real not null default 0, goods real not null default 0, materials real not null default 0,
  proposed boolean not null default false               -- true: generated placeholder (PROPOSED), for Danny to rewrite
);

-- 2. PEOPLE: tiers, a temperament for dreaming, and whether they are away.
alter table public.people
  add column tier text check (tier in ('principal', 'side')),
  add column dream_temperament text check (dream_temperament in ('mystic', 'romantic', 'traditionalist', 'sage', 'pragmatist', 'skeptic')),
  add column absent boolean not null default false,     -- not in Corva (where they are, if sealed, is in sealed_facts)
  add column proposed boolean not null default false;   -- generated placeholder (PROPOSED)

-- 3. HOUSE MEMBERSHIP: who belongs to which house, in what role, from when to when.
create table public.house_members (
  id bigint generated always as identity primary key,
  house_id bigint not null references public.houses(id),
  person_id bigint not null references public.people(id),
  role text not null check (role in ('head', 'heir', 'spouse', 'child', 'kin', 'fosterling', 'servant', 'retainer')),
  joined_year int, joined_season public.season,
  left_year int, left_season public.season,
  unique (house_id, person_id, joined_year, joined_season)
);

-- 4. LINEAGE: who is whose child, as it truly is. A missing row is an unknown parent (Soren's
--    father has none, and none will be invented). What people BELIEVE about parentage is a belief.
create table public.lineage (
  id bigint generated always as identity primary key,
  parent_id bigint not null references public.people(id),
  child_id bigint not null references public.people(id),
  kind text not null check (kind in ('blood', 'adoptive', 'fostered')),
  unique (parent_id, child_id)
);

-- 5. CLIENTS: the townsfolk attached to each house, per tick. Count and average loyalty are a
--    house's real power; defections are counted both ways. Unattached townsfolk are house_id NULL.
create table public.house_clients (
  id bigint generated always as identity primary key,
  year int not null, season public.season not null,
  house_id bigint references public.houses(id),         -- NULL: unattached
  count int not null check (count >= 0),
  loyalty real check (loyalty between 0 and 1),
  gained int not null default 0, lost int not null default 0,        -- clients won and lost this tick
  unique (year, season, house_id)
);

-- 6. LEGENDS: stories a house tells, in its own version. Attributed accounts, like chronicles.
create table public.legends (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,                       -- when this version took shape (NULL: from before the record)
  house_id bigint references public.houses(id),         -- whose version (NULL: told across the city)
  title text not null,
  text text not null,                                   -- the telling, labelled as that house's account
  events bigint[] not null default '{}',                -- the events it grew from, if any are in the record
  proposed boolean not null default false
);

-- 7. BELIEFS gain an object house and a stance, so house feelings can be computed from them.
alter table public.beliefs
  add column about_house bigint references public.houses(id),
  add column stance real check (stance between -1 and 1);   -- how the holder stands toward that house in this belief

-- 8. EVENTS name the houses they touch (inter-house events are permanent facts); proposals name the house that proposed.
alter table public.events add column houses bigint[] not null default '{}';
alter table public.storyteller_proposals add column house_id bigint references public.houses(id);
-- dreams: whether the dreamer remembered it on waking, and who they told
alter table public.dreams
  add column recalled boolean,
  add column shared_with bigint[] not null default '{}';

-- 9. HOUSE FEELINGS: a view, never stored. How the members of one house stand toward another =
--    the confidence-weighted mean stance of their current beliefs about that house.
create view public.house_feelings with (security_invoker = true) as
  select m.house_id as from_house, b.about_house as to_house,
         sum(b.stance * b.confidence) / nullif(sum(b.confidence), 0) as feeling,
         count(*) as beliefs
  from public.beliefs b
  join public.house_members m on m.person_id = b.holder_id and m.left_year is null
  where b.about_house is not null and b.stance is not null
  group by m.house_id, b.about_house;

-- 10. SEALED FACTS: truths the engine knows and nobody else may read (the lovers' true location).
--     Row level security on and NO policy: anon and authenticated can read nothing; only the
--     service role (the engine) can. Reports never print these rows.
create table public.sealed_facts (
  key text primary key,
  created_at timestamptz not null default now(),
  value jsonb not null
);
alter table public.sealed_facts enable row level security;

-- Public read on the new open tables, as for the rest of the world.
do $$
declare t text;
begin
  foreach t in array array['houses', 'house_members', 'lineage', 'house_clients', 'legends'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy "public read" on public.%I for select to anon, authenticated using (true)', t);
  end loop;
end $$;
