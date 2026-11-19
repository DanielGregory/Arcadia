-- =====================================================================================
-- SANDBOX MIRROR, part 3: procedural personalities. Additive only; read-only to the site like every sandbox_* table.
--   sandbox_people        + traits (humours, values, dispositions, quirks, seed_fixed), bio, bio_status
--                           ('proposed' by the model, or 'danny'), bio_occasion
--   sandbox_trait_changes   every change life made to someone's traits, with the event that caused it
-- Rollback: drop table public.sandbox_trait_changes; alter table public.sandbox_people drop column traits,
--           drop column bio, drop column bio_status, drop column bio_occasion;
-- =====================================================================================
alter table public.sandbox_people add column if not exists traits jsonb;
alter table public.sandbox_people add column if not exists bio text;
alter table public.sandbox_people add column if not exists bio_status text;
alter table public.sandbox_people add column if not exists bio_occasion text;
create table public.sandbox_trait_changes (
  id bigint primary key, year int, season text, person_id bigint, trait text, before real, after real,
  event_id bigint, reason text
);
alter table public.sandbox_trait_changes enable row level security;
create policy "public read" on public.sandbox_trait_changes for select to anon, authenticated using (true);
revoke insert, update, delete on public.sandbox_trait_changes from anon, authenticated;
