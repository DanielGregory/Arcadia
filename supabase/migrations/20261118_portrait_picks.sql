-- =====================================================================================
-- PORTRAIT CANDIDATES and PICKS (sandbox). Additive only.
--
--   sandbox_portrait_candidates  the engine's candidates (4 per principal, painted on Kaggle from the person's
--                                appearance record), published like every sandbox_* table: read-only to the site.
--   portrait_picks               Danny's choice on the review page, one per person. This is a REVIEW table, like
--                                images.picked and dreams.mark: the review page (publishable key) may insert and
--                                change a pick, and nothing else. It is not a world table: the engine reads the
--                                picks (python -m world.portraits adopt, also run nightly) and only then does the
--                                chosen image become the person's portrait and reference image, in the engine's
--                                own records.
-- Rollback: drop table public.portrait_picks, public.sandbox_portrait_candidates;
-- =====================================================================================

create table public.sandbox_portrait_candidates (
  id bigint primary key, person_id bigint not null, k int not null, seed int, prompt text, image text not null,
  made_at timestamptz
);
alter table public.sandbox_portrait_candidates enable row level security;
create policy "public read" on public.sandbox_portrait_candidates for select to anon, authenticated using (true);
revoke insert, update, delete on public.sandbox_portrait_candidates from anon, authenticated;

create table public.portrait_picks (
  person_id bigint primary key,
  candidate_id bigint not null,
  picked_at timestamptz not null default now()
);
alter table public.portrait_picks enable row level security;
create policy "public read" on public.portrait_picks for select to anon, authenticated using (true);
create policy "review picks" on public.portrait_picks for insert to anon, authenticated with check (true);
create policy "review repicks" on public.portrait_picks for update to anon, authenticated using (true) with check (true);
revoke delete on public.portrait_picks from anon, authenticated;

-- and each person's fixed physical description (world/appearance.yaml, PROPOSED drafts) and reference image path
alter table public.sandbox_people add column if not exists appearance jsonb;
alter table public.sandbox_people add column if not exists portrait_ref text;
