-- =====================================================================================
-- SANDBOX MIRROR: a read-only window onto the offline world engine.
--
-- The world engine v0 runs offline on a local SQLite file (data/world/sandbox.db). After each
-- season, world/publish.py copies a PUBLIC snapshot of it here, into tables prefixed sandbox_, so
-- the site's sandbox modes (/world/?world=sandbox, the review page's Chronicle tab, the sandbox
-- Sky, the wallpaper preview) can read it. Production tables (dreams, mornings, people...) are
-- not touched.
--
-- Rules (VISION: the engine is the truth):
--   * the site READS these tables with the publishable key; nobody but the engine writes them
--     (the engine uses the secret key, which bypasses row level security; anon gets select only);
--   * what is never copied here: sealed_facts, memories (private truths live there), sealed
--     events, event facts, and the place of anyone who is absent (where the lovers are is sealed);
--   * every publish replaces the whole snapshot (it is a mirror, not a history).
--
-- Why a prefix and not a separate schema: the hosted API only serves the schemas listed in its
-- settings, and keeping everything in public avoids a settings change. Rollback: drop the tables
-- (rollback_sandbox_mirror.sql).
-- =====================================================================================

-- the clock: which season the snapshot is from
create table public.sandbox_world (
  id int primary key default 1 check (id = 1),
  year int not null, season text not null, tick int not null,
  published_at timestamptz not null default now()
);

-- places with their positions on the 3D island (metres; x east, z south). placement_proposed:
-- the position was chosen by world/placements.py (PROPOSED), not decided by Danny.
create table public.sandbox_places (
  id bigint primary key, name text not null, kind text, parent_id bigint,
  x real, z real, placement_proposed boolean not null default true
);

create table public.sandbox_houses (
  id bigint primary key, name text not null, claim text, land text, land_kind text,
  seat_place_id bigint, head_id bigint, food real, goods real, materials real,
  proposed boolean not null default false,        -- a placeholder house Danny hasn't detailed
  color text,                                     -- the house's lantern colour (PROPOSED)
  estate_x real, estate_z real, estate_radius real, estate_proposed boolean not null default true
);

-- people: place_id is NULL for anyone absent (their whereabouts are sealed)
create table public.sandbox_people (
  id bigint primary key, name text not null, tier text, house_id bigint, role text,
  place_id bigint, alive boolean, absent boolean, proposed boolean, dream_temperament text
);

-- events that happened (not sealed ones; no facts column: facts can hold engine-only detail)
create table public.sandbox_events (
  id bigint primary key, year int, season text, kind text, place_id bigint,
  actors jsonb not null default '[]', houses jsonb not null default '[]', outcome text, text text
);

create table public.sandbox_beliefs (
  id bigint primary key, year int, season text, holder_id bigint, subject_type text, subject_id text,
  interpretation text, confidence real, source_type text, about_house bigint, stance real
);

-- every dream of the season. discussed = how many people it was told to + interpretations of it.
-- sky_x / sky_y: its star (0..1), placed by meaning like the production Sky.
create table public.sandbox_dreams (
  id text primary key, year int, season text, dreamer_id bigint, house_id bigint, tag text, text text,
  recalled boolean, shared_with jsonb not null default '[]', discussed int not null default 0,
  retelling text, sky_x real, sky_y real
);

create table public.sandbox_house_clients (
  id bigint primary key, year int, season text, house_id bigint, count int, loyalty real, gained int, lost int
);

-- a chronicle is an author's account: kind 'chronicle' (the season's, whole markdown),
-- 'account' (a person's first-person account) or 'talk' (town talk). Claims, not facts.
create table public.sandbox_chronicles (
  id bigint primary key, year int, season text, author_id bigint, kind text, text text
);

-- how houses feel about each other, computed by the engine from members' beliefs (as the
-- house_feelings view does), stored flat for the snapshot
create table public.sandbox_house_feelings (
  from_house bigint, to_house bigint, feeling real, beliefs int, primary key (from_house, to_house)
);

create table public.sandbox_vital_signs (year int, season text, stats jsonb, primary key (year, season));

-- the wallpaper PREVIEW (never production): what tomorrow's wallpaper would be from the engine's
-- most-discussed dream. image is a path in the public 'arcadia' bucket under sandbox/.
create table public.sandbox_previews (
  id bigint generated always as identity primary key, created_at timestamptz not null default now(),
  year int, season text, dream_id text, dreamer text, house text, scene text, image text, status text, error text
);

do $$
declare t text;
begin
  foreach t in array array['sandbox_world', 'sandbox_places', 'sandbox_houses', 'sandbox_people', 'sandbox_events',
                           'sandbox_beliefs', 'sandbox_dreams', 'sandbox_house_clients', 'sandbox_chronicles',
                           'sandbox_house_feelings', 'sandbox_vital_signs', 'sandbox_previews']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy "public read" on public.%I for select to anon, authenticated using (true)', t);
    execute format('revoke insert, update, delete on public.%I from anon, authenticated', t);
  end loop;
end $$;
