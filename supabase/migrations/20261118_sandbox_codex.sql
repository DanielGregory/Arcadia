-- =====================================================================================
-- SANDBOX MIRROR, part 2: what the Codex, the character panel and the chroniclers need.
-- Additive only (new columns, new tables). Same rules as 20261118_sandbox_mirror.sql: the site reads,
-- only the engine (world/publish.py, secret key) writes; nothing private is ever copied here.
--
--   sandbox_people     + born_year, note (the public description), sex (PROPOSED: from the name),
--                        portrait (a path in the public 'arcadia' bucket, sandbox/portraits/)
--   sandbox_lineage      parent -> child (blood or fostered)
--   sandbox_relationships  public ties only: spouse, betrothed, kin, friend, rival, teacher (never 'lover')
--   sandbox_legends      each house's founding tale, as that house tells it (an account, not a fact)
--   sandbox_symbols      images that recur in the engine's dreams, with the dreams they appear in
--   sandbox_chronicles + title: whose history it is ("Iola Aurelian, scribe of the sea temple")
-- Rollback: rollback_sandbox_codex.sql
-- =====================================================================================

alter table public.sandbox_people add column if not exists born_year int;
alter table public.sandbox_people add column if not exists note text;
alter table public.sandbox_people add column if not exists sex text;
alter table public.sandbox_people add column if not exists portrait text;
alter table public.sandbox_chronicles add column if not exists title text;

create table public.sandbox_lineage (id bigint primary key, parent_id bigint, child_id bigint, kind text);
create table public.sandbox_relationships (id bigint primary key, person_a bigint, person_b bigint, kind text, strength real);
create table public.sandbox_legends (id bigint primary key, house_id bigint, title text, text text, proposed boolean);
create table public.sandbox_symbols (symbol text primary key, dreams int, dream_ids jsonb not null default '[]',
                                     first_year int, first_season text);

do $$
declare t text;
begin
  foreach t in array array['sandbox_lineage', 'sandbox_relationships', 'sandbox_legends', 'sandbox_symbols']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy "public read" on public.%I for select to anon, authenticated using (true)', t);
    execute format('revoke insert, update, delete on public.%I from anon, authenticated', t);
  end loop;
end $$;
