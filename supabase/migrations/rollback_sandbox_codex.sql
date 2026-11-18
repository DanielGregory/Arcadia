-- Undo 20261118_sandbox_codex.sql (sandbox snapshot only).
drop table if exists public.sandbox_lineage, public.sandbox_relationships, public.sandbox_legends, public.sandbox_symbols;
alter table public.sandbox_people drop column if exists born_year, drop column if exists note,
  drop column if exists sex, drop column if exists portrait;
alter table public.sandbox_chronicles drop column if exists title;
