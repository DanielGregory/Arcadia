-- Undo 20261118_sandbox_mirror.sql (the sandbox snapshot only; production tables are untouched).
drop table if exists public.sandbox_world, public.sandbox_places, public.sandbox_houses, public.sandbox_people,
  public.sandbox_events, public.sandbox_beliefs, public.sandbox_dreams, public.sandbox_house_clients,
  public.sandbox_chronicles, public.sandbox_house_feelings, public.sandbox_vital_signs, public.sandbox_previews;
