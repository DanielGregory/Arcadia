-- Undo 20261117_world_schema.sql (only if something breaks). If 20261118_drop_memory_tables.sql has NOT run yet,
-- skip the memory_* "create table" statements below (those tables still exist). Then restore the memory_* rows
-- with `python daily/memory_sync.py` (it rebuilds them from the repo) or from the JSON backup.
drop view if exists public.faction_disagreements, public.faction_shared_beliefs;
drop table if exists public.vital_signs, public.chronicles, public.faction_practices, public.faction_members,
  public.factions, public.beliefs, public.memories, public.sky_constellations, public.symbol_occurrences,
  public.symbols, public.dreams, public.events, public.creator_plantings, public.storyteller_proposals,
  public.objects, public.places, public.townsfolk, public.relationships, public.people cascade;
drop function if exists public.events_append_only(), public.world_meaning_lint();
drop type if exists public.season;
alter table public.review_dreams rename to dreams;

create table public.memory_dreams (
  id text primary key, run text not null, kind text not null, tag text not null, prompt text, text text not null,
  remembered text, day date, embedding extensions.vector(384), sky_x real, sky_y real, constellation int,
  created_at timestamptz not null default now());
create index memory_dreams_embedding on public.memory_dreams using hnsw (embedding extensions.vector_cosine_ops);
create table public.memory_symbols (name text primary key, dreams int not null default 0, mentions int not null default 0, first_seen text);
create table public.memory_dream_symbols (dream_id text references public.memory_dreams(id) on delete cascade,
  symbol text references public.memory_symbols(name) on delete cascade, mentions int not null, primary key (dream_id, symbol));
create table public.memory_constellations (id int primary key, label text not null, symbols text[] not null, x real, y real, size int not null);
alter table public.memory_dreams enable row level security;
alter table public.memory_symbols enable row level security;
alter table public.memory_dream_symbols enable row level security;
alter table public.memory_constellations enable row level security;
create policy "public read" on public.memory_dreams for select to anon, authenticated using (true);
create policy "public read" on public.memory_symbols for select to anon, authenticated using (true);
create policy "public read" on public.memory_dream_symbols for select to anon, authenticated using (true);
create policy "public read" on public.memory_constellations for select to anon, authenticated using (true);
revoke insert, update, delete on public.memory_dreams, public.memory_symbols, public.memory_dream_symbols,
  public.memory_constellations from anon, authenticated;
create or replace function public.match_dreams(query_embedding extensions.vector(384), match_count int default 8)
returns table (id text, tag text, kind text, text text, similarity real)
language sql stable set search_path = public, extensions as $$
  select d.id, d.tag, d.kind, d.text, (1 - (d.embedding <=> query_embedding))::real from public.memory_dreams d
  where d.embedding is not null order by d.embedding <=> query_embedding limit match_count; $$;
create or replace function public.similar_dreams(dream_id text, match_count int default 5)
returns table (id text, tag text, kind text, text text, similarity real)
language sql stable set search_path = public, extensions as $$
  select m.* from public.memory_dreams d, lateral public.match_dreams(d.embedding, match_count + 1) m
  where d.id = dream_id and m.id <> dream_id limit match_count; $$;
grant execute on function public.match_dreams(extensions.vector, int) to anon, authenticated;
grant execute on function public.similar_dreams(text, int) to anon, authenticated;
