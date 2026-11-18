-- Retire Phase 2's memory_* tables: their rows were copied into the world tables (dreams, symbols,
-- symbol_occurrences, sky_constellations) by 20261117_world_schema.sql and nothing reads them any more.
-- Kept until now as an extra fallback. Destructive, so the Supabase connector asks for confirmation.
drop table public.memory_dream_symbols, public.memory_symbols, public.memory_constellations, public.memory_dreams;
