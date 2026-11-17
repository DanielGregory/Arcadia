-- =====================================================================================
-- Arcadia world database: STRUCTURE ONLY (no simulation logic). From docs/world_engine.md.
-- Approved 2026-11-17; to be applied (backup: HF DannyGregs/arcadia-dreams backups/supabase_20261117T2038Z;
-- undo: rollback_world_schema.sql). Code switchover: 20261117_world_switchover.patch (git apply after migrating).
--
-- The hard rule: no table stores what anything MEANS. Facts live everywhere; meaning,
-- significance and interpretation live only in `beliefs`, per person, with a confidence.
-- Enforced three ways (section 9): no such columns are created; world_meaning_lint()
-- lists any that ever appear; and events are append-only.
--
-- Shared conventions: every world row has created_at and its in-world time (year, season).
-- Pre-world material (the dreams we already have) has year/season NULL and a real `day`.
-- =====================================================================================

-- 0. Make room: the review gallery's table is called "dreams" today. It keeps its rows and the
--    columns the gallery writes (mark, note); only its name changes. (site/ and daily/ updated to match.)
alter table public.dreams rename to review_dreams;

create type public.season as enum ('spring', 'summer', 'autumn', 'winter');

-- 1. PEOPLE: the ~25 named inhabitants (full agents). Facts and state only.
create table public.people (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,                      -- when they entered the record
  name text not null,
  born_year int, died_year int,
  origin text,                                          -- where they came from (a place name), not why
  household text,
  -- traits, fixed for life, 0..1
  openness real check (openness between 0 and 1),
  caution real check (caution between 0 and 1),
  warmth real check (warmth between 0 and 1),
  pride real check (pride between 0 and 1),
  piety real check (piety between 0 and 1),
  temperament text check (temperament in ('sanguine', 'choleric', 'melancholic', 'phlegmatic')),
  -- needs, change every tick, 0..1 (1 = fully met)
  need_hunger real, need_warmth real, need_safety real, need_belonging real, need_standing real,
  health real check (health between 0 and 1),
  place_id bigint,                                      -- where they are now (FK added below)
  alive boolean not null default true,
  promoted_from_crowd boolean not null default false
);

-- 2. RELATIONSHIPS between named people.
create table public.relationships (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,
  person_a bigint not null references public.people(id),
  person_b bigint not null references public.people(id),
  kind text not null check (kind in ('kin', 'spouse', 'friend', 'rival', 'teacher')),
  strength real not null check (strength between -1 and 1),
  formed_event bigint                                   -- FK added below
);

-- 3. TOWNSFOLK: ~200 people as aggregate counts, one row per tick. No individuals.
create table public.townsfolk (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,
  count int not null, births int not null default 0, deaths int not null default 0,
  mood real check (mood between -1 and 1),
  food_share real,
  faction_sizes jsonb not null default '{}',            -- {faction_id: members}
  unique (year, season)
);

-- 4. PLACES: what is where, who built it, what state it is in. Use = activity counts, not purpose.
create table public.places (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,
  kind text not null,                                   -- shore, spring, field, grove, house, wall, harbour, stone...
  names jsonb not null default '[]',                    -- [{"name": "the spring", "used_by": [person ids]}]
  parent_id bigint references public.places(id),
  built_by bigint references public.people(id),
  built_event bigint,                                   -- FK added below
  condition real check (condition between 0 and 1),
  activity jsonb not null default '{}'                  -- {"fetched water": 41, "gathered": 3}
);
alter table public.people add constraint people_place_fk foreign key (place_id) references public.places(id);

-- 5. OBJECTS: physical things. Their history is the list of events that touched them.
create table public.objects (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,
  kind text not null,
  description text,                                     -- physical only: "a weathered standing stone, waist-high"
  marks text,                                           -- visible marks as written (the inscription's glyphs); never a reading
  made_by bigint references public.people(id),
  owner_type text not null default 'none' check (owner_type in ('person', 'faction', 'none')),
  owner_id bigint,
  place_id bigint references public.places(id),
  held_by bigint references public.people(id),
  condition real check (condition between 0 and 1),
  made_event bigint                                     -- FK added below
);

-- 6. STORYTELLER PROPOSALS and CREATOR PLANTINGS come before events, which point at them.
create table public.storyteller_proposals (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,
  tick int not null,
  kind text not null,
  payload jsonb not null,                               -- the structured proposal
  wording text,                                         -- the storyteller's own words: stays here, never enters events
  status text not null check (status in ('accepted', 'partial', 'failed', 'rejected')),
  reason text,                                          -- why it resolved that way
  rule_broken text,                                     -- for rejections: which rule ("asserts a meaning", "actor dead"...)
  event_id bigint                                       -- FK added below
);

create table public.creator_plantings (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  week date not null,                                   -- the real week it was planted (one a week)
  year int, season public.season,                       -- when it entered the world
  kind text not null check (kind in ('object', 'stranger', 'dream')),
  payload jsonb not null,                               -- what it IS, never what it is for
  event_id bigint                                       -- its arrival or discovery; FK added below
);

-- 7. EVENTS: append-only record of what happened. Text is engine-written from templates.
create table public.events (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,
  kind text not null,                                   -- closed vocabulary, checked by the engine
  place_id bigint references public.places(id),
  actors bigint[] not null default '{}',                -- people ids
  objects bigint[] not null default '{}',               -- object ids
  outcome text not null check (outcome in ('success', 'partial', 'failure')),
  facts jsonb not null default '{}',
  text text not null,                                   -- template text: "Ione found a marked stone by the spring."
  proposal_id bigint references public.storyteller_proposals(id),
  planting_id bigint references public.creator_plantings(id)
);
alter table public.relationships add constraint rel_event_fk foreign key (formed_event) references public.events(id);
alter table public.places add constraint place_event_fk foreign key (built_event) references public.events(id);
alter table public.objects add constraint object_event_fk foreign key (made_event) references public.events(id);
alter table public.storyteller_proposals add constraint proposal_event_fk foreign key (event_id) references public.events(id);
alter table public.creator_plantings add constraint planting_event_fk foreign key (event_id) references public.events(id);

-- Append-only: corrections are new events, never edits.
create or replace function public.events_append_only() returns trigger language plpgsql as $$
begin
  raise exception 'events are append-only: record a new event instead of changing event %', old.id;
end $$;
create trigger events_no_update before update or delete on public.events
  for each row execute function public.events_append_only();

-- 8. DREAMS, SYMBOLS and where symbols occur. Takes over Phase 2's memory_* tables.
create table public.dreams (
  id text primary key,                                  -- "run4-read-07", "morning-2026-11-17", later "y3-spring-ione"
  created_at timestamptz not null default now(),
  year int, season public.season,                       -- in-world time (NULL for pre-world dreams)
  day date,                                             -- real date (mornings)
  dreamer_id bigint references public.people(id),       -- NULL: dreamed by the model before the world began
  run text not null,                                    -- which model: run4, run5...
  kind text not null,                                   -- read_test | priming | sample | morning | candidate | test | world
  tag text not null,                                    -- the voice: dream | myth | tale | poem | wisdom | chronicle | saga
  memory_seeds bigint[] not null default '{}',          -- memories that primed it (world dreams)
  prompt text,
  text text not null,                                   -- as dreamed
  remembered text,                                      -- the editor's tidy copy (mornings); world dreams have none
  embedding extensions.vector(384),
  sky_x real, sky_y real, constellation int             -- place in the Sky (layout, not meaning)
);
create index dreams_embedding on public.dreams using hnsw (embedding extensions.vector_cosine_ops);

create table public.symbols (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,                       -- first seen in-world (NULL: before the world)
  label text not null unique,                           -- an IMAGE: "sea", later "the sea sleeping in the sky"; never what it stands for
  embedding extensions.vector(384),
  first_seen_dream text references public.dreams(id),
  first_seen_event bigint references public.events(id),
  frequency int not null default 0,                     -- total mentions
  dreams int not null default 0                         -- dreams it appears in
);

create table public.symbol_occurrences (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int, season public.season,
  symbol_id bigint not null references public.symbols(id) on delete cascade,
  dream_id text references public.dreams(id) on delete cascade,
  event_id bigint references public.events(id),
  mentions int not null default 1,
  check ((dream_id is null) <> (event_id is null)),     -- exactly one of: a dream, an event
  unique (symbol_id, dream_id), unique (symbol_id, event_id)
);

create table public.sky_constellations (                -- Sky layout: groups of nearby stars, named by shared images
  id int primary key,
  label text not null, symbols text[] not null, x real, y real, size int not null
);

-- 9. MEMORIES: what each person remembers, which may drift from the record.
create table public.memories (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,
  person_id bigint not null references public.people(id),
  source_type text not null check (source_type in ('event', 'dream', 'told_by', 'chronicle')),
  source_id text not null,                              -- points at the TRUE record (event/dream/chronicle id)
  told_by bigint references public.people(id),
  text text not null,                                   -- as remembered, may be distorted
  vividness real not null check (vividness between 0 and 1),
  distortions jsonb not null default '[]',              -- [{"field": "weather", "was": "calm", "now": "storm"}]
  last_recalled_year int, last_recalled_season public.season
);

-- 10. BELIEFS: the ONLY place meaning lives. Always held by someone, always with a confidence.
create table public.beliefs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,     -- when formed
  holder_id bigint not null references public.people(id),
  subject_type text not null check (subject_type in ('event', 'symbol', 'object', 'place', 'person', 'planting', 'dream')),
  subject_id text not null,
  interpretation text not null,                         -- what this person thinks it means
  confidence real not null check (confidence between 0 and 1),
  source_type text not null check (source_type in ('own_dream', 'witnessed', 'told_by', 'chronicle', 'faction')),
  source_person bigint references public.people(id),
  history jsonb not null default '[]'                   -- [{"year", "season", "interpretation", "confidence"}]
);

-- 11. FACTIONS: names, members and observable practices. Never an official meaning.
create table public.factions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,
  name text not null,                                   -- chosen by its members
  founded_event bigint references public.events(id)
);
create table public.faction_members (
  faction_id bigint not null references public.factions(id),
  person_id bigint not null references public.people(id),
  joined_year int not null, joined_season public.season not null,
  left_year int, left_season public.season,
  role text,
  primary key (faction_id, person_id, joined_year, joined_season)
);
create table public.faction_practices (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,
  faction_id bigint not null references public.factions(id),
  practice text not null,                               -- an ACTION: "pour wine into the sea before the first winter storm"
  started_event bigint references public.events(id)
);

-- Shared beliefs and disagreements are computed from beliefs, never stored.
create view public.faction_shared_beliefs with (security_invoker = true) as
  select m.faction_id, b.subject_type, b.subject_id, b.interpretation,
         count(*) as holders,
         count(*)::real / (select count(*) from public.faction_members x
                           where x.faction_id = m.faction_id and x.left_year is null) as share
  from public.faction_members m join public.beliefs b on b.holder_id = m.person_id
  where m.left_year is null
  group by m.faction_id, b.subject_type, b.subject_id, b.interpretation
  having count(*)::real / (select count(*) from public.faction_members x
                           where x.faction_id = m.faction_id and x.left_year is null) >= 0.6;

create view public.faction_disagreements with (security_invoker = true) as
  select m1.faction_id, b1.subject_type, b1.subject_id,
         b1.holder_id as person_a, b1.interpretation as belief_a,
         b2.holder_id as person_b, b2.interpretation as belief_b
  from public.faction_members m1
  join public.faction_members m2 on m2.faction_id = m1.faction_id and m2.person_id > m1.person_id
  join public.beliefs b1 on b1.holder_id = m1.person_id
  join public.beliefs b2 on b2.holder_id = m2.person_id
       and b2.subject_type = b1.subject_type and b2.subject_id = b1.subject_id
       and b2.interpretation <> b1.interpretation
  where m1.left_year is null and m2.left_year is null;

-- 12. CHRONICLES: an object a person made. Its text is that person's account, labelled as theirs.
create table public.chronicles (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null, season public.season not null,     -- when written
  author_id bigint not null references public.people(id),
  object_id bigint references public.objects(id),       -- the physical chronicle (a scroll, a carved board)
  events bigint[] not null default '{}',                -- the events it tells of
  text text not null,                                   -- the author's account: an attributed view, not fact
  readers bigint[] not null default '{}'
);

-- 13. VITAL SIGNS: one row per tick.
create table public.vital_signs (
  year int not null, season public.season not null,
  created_at timestamptz not null default now(),
  stats jsonb not null,
  primary key (year, season)
);

-- =====================================================================================
-- 14. The hard rule, checkable: any column outside `beliefs` whose name suggests meaning.
--     Returns no rows today. A test (daily/check_world_schema.py) fails the build if it ever does.
-- =====================================================================================
create or replace function public.world_meaning_lint()
returns table (table_name text, column_name text)
language sql stable set search_path = public as $$
  select c.table_name::text, c.column_name::text
  from information_schema.columns c
  join information_schema.tables t on t.table_schema = c.table_schema and t.table_name = c.table_name
  where c.table_schema = 'public'
    and t.table_type = 'BASE TABLE'          -- views store nothing; the belief views are computed from beliefs
    and c.table_name <> 'beliefs'
    and c.column_name ~* '(meaning|significan|symbolism|symbolic|interpret|omen|portent|signif|purpose|stands_for|represents|moral|lesson|prophecy|destiny)'
$$;

-- =====================================================================================
-- 15. Move Phase 2's memory into the world tables, then retire the memory_* tables.
-- =====================================================================================
insert into public.dreams (id, created_at, day, run, kind, tag, prompt, text, remembered, embedding, sky_x, sky_y, constellation)
  select id, created_at, day, run, kind, tag, prompt, text, remembered, embedding, sky_x, sky_y, constellation
  from public.memory_dreams;
insert into public.symbols (label, first_seen_dream, frequency, dreams)
  select name, first_seen, mentions, dreams from public.memory_symbols;
insert into public.symbol_occurrences (symbol_id, dream_id, mentions)
  select s.id, ds.dream_id, ds.mentions
  from public.memory_dream_symbols ds join public.symbols s on s.label = ds.symbol;
insert into public.sky_constellations select * from public.memory_constellations;

create or replace function public.match_dreams(query_embedding extensions.vector(384), match_count int default 8)
returns table (id text, tag text, kind text, text text, similarity real)
language sql stable set search_path = public, extensions as $$
  select d.id, d.tag, d.kind, d.text, (1 - (d.embedding <=> query_embedding))::real
  from public.dreams d where d.embedding is not null
  order by d.embedding <=> query_embedding limit match_count;
$$;
-- similar_dreams() keeps working unchanged: it calls match_dreams.
create or replace function public.similar_dreams(dream_id text, match_count int default 5)
returns table (id text, tag text, kind text, text text, similarity real)
language sql stable set search_path = public, extensions as $$
  select m.* from public.dreams d, lateral public.match_dreams(d.embedding, match_count + 1) m
  where d.id = dream_id and m.id <> dream_id limit match_count;
$$;

drop table public.memory_dream_symbols, public.memory_symbols, public.memory_constellations, public.memory_dreams;

-- =====================================================================================
-- 16. Access: the public site may READ the world; only the engine (secret key) writes.
--     The review gallery keeps its narrow write grants (mark/note) on review_dreams.
-- =====================================================================================
do $$
declare t text;
begin
  foreach t in array array['people', 'relationships', 'townsfolk', 'places', 'objects', 'storyteller_proposals',
                           'creator_plantings', 'events', 'dreams', 'symbols', 'symbol_occurrences',
                           'sky_constellations', 'memories', 'beliefs', 'factions', 'faction_members',
                           'faction_practices', 'chronicles', 'vital_signs']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy "public read" on public.%I for select to anon, authenticated using (true)', t);
    execute format('revoke insert, update, delete on public.%I from anon, authenticated', t);
  end loop;
end $$;
grant execute on function public.world_meaning_lint() to anon, authenticated;
