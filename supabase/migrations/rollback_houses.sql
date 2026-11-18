-- Undo 20261118_houses.sql. Destructive: run only to roll back (the Supabase connector asks first).
drop view if exists public.house_feelings;
drop table if exists public.sealed_facts, public.legends, public.house_clients, public.lineage, public.house_members;
alter table public.dreams drop column if exists recalled, drop column if exists shared_with;
alter table public.storyteller_proposals drop column if exists house_id;
alter table public.events drop column if exists houses;
alter table public.beliefs drop column if exists about_house, drop column if exists stance;
alter table public.people drop column if exists tier, drop column if exists dream_temperament,
  drop column if exists absent, drop column if exists proposed;
drop table if exists public.houses;
