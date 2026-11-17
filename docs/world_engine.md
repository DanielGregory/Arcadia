# World engine: design spec (draft)

Status: draft for Daniel to edit. No code yet. **LOCKED** = Daniel's decision; **PROPOSED** = Claude's
suggestion, open to change. Follows `docs/VISION.md`: the engine records what happens, never what it means.

## 0. Ground rules

- **LOCKED: time.** One Arcadia year per real day, run as 4 seasonal ticks (spring, summer, autumn, winter).
- **LOCKED: population.** ~25 named inhabitants as full agents and ~200 townsfolk as aggregate counts. When a
  named person dies, someone from the crowd can be promoted to a named agent.
- **LOCKED: creator.** Daniel plants one thing a week (object, stranger or dream) and never controls its meaning.
- **LOCKED: budget.** About 1 hour of CPU per daily run, ~150–200 pretrained-model calls.
- **LOCKED: the hard rule.** No table stores what anything *means*. Objects, events, places and symbols hold
  facts only (owner, location, history, who was involved). Meaning, significance and interpretation live only
  in `beliefs`, per person, with a confidence. Factions store practices and members, never an official meaning.
- **PROPOSED: enforcing the hard rule.**
  1. No column named meaning, significance, purpose, omen, symbolism or anything like it, outside `beliefs`.
     A schema lint checks this in CI.
  2. Event text is written by the engine from structured fields using templates ("Ione and Damas raised a wall
     at the spring."). The storyteller's own wording stays in the proposal log and never enters `events`.
  3. Anything that interprets (chronicles, faction "shared beliefs") is either attributed to a specific person or
     computed as a view over `beliefs`. It is never stored as fact.

## 1. Data model (Supabase)

All tables share `id`, `created_at` and the in-world time `(year, season)`. **PROPOSED** everywhere below.

| Table | Holds (facts only) | Notes |
|---|---|---|
| `people` | name, born_year, died_year, origin, household, traits (0–1: openness, caution, warmth, pride, piety), temperament (one of 4), needs (hunger, warmth, safety, belonging, standing; 0–1), health, place_id, alive, promoted_from_crowd | Traits are fixed; needs change each tick. |
| `relationships` | person_a, person_b, kind (kin / spouse / friend / rival / teacher), strength −1..1, formed_event | PROPOSED split from `people`. |
| `memories` | person, source (event / dream / told-by / chronicle), source_id, text *as remembered*, vividness 0–1, distortions (count + list), last_recalled | Text may drift (§4); `source_id` still points at the true record. |
| `townsfolk` | per tick: count, births, deaths, mood −1..1, food_share, faction_sizes (json) | Aggregate only, no individuals. |
| `places` | name(s) and who uses each name, kind (shore, spring, field, grove, house, wall, harbour, stone, …), parent place, built_by, built_event, condition | A place's *use* is recorded as activity counts, not purpose. |
| `objects` | kind and physical description, made_by, owner (person / faction / none), location (place or person), condition, made_event | History is the list of events that touched it. |
| `events` | append-only. kind (closed vocabulary), place, actors[], objects[], outcome (success / partial / failure), facts (json), template text, proposal_id, planting_id | No updates or deletes. Corrections are new events. |
| `dreams` | dreamer, (year, season), tag used, memory seeds used, text, model run | Raw text; no "as remembered" pass (§6). |
| `symbols` | label (a short *image* phrase: "the sea sleeping in the sky"), embedding, first_seen, frequency | The label describes an image, never what it stands for. |
| `symbol_occurrences` | symbol, dream_id or event_id, (year, season) | Links each symbol to every dream and event it appears in. |
| `beliefs` | holder, subject_type (event / symbol / object / place / person / planting), subject_id, interpretation (free text), confidence 0–1, source (own dream, told by X, chronicle, faction), formed, history of changes | **The only place meaning lives.** |
| `factions` | name (chosen by members), founded_event | No stored meaning. |
| `faction_members` / `faction_practices` | person, joined, role / an *observable* practice ("pour wine into the sea before the first winter storm"), started_event | Practices are actions, not reasons. |
| views: `faction_shared_beliefs`, `faction_disagreements` | beliefs held by ≥60% of members / pairs of members with conflicting beliefs about the same subject | Computed from `beliefs`, never stored. |
| `chronicles` | author, events[], text, written (year, season), readers[] | A chronicle is an object a person made. Its text is that person's account and is labelled as such. |
| `storyteller_proposals` | tick, kind, payload (json), storyteller's wording, status (accepted / partial / failed / rejected), reason, resulting event | Every attempt, including rejections. |
| `creator_plantings` | week, kind (object / stranger / dream), payload, planted tick, event_id | Plus a view of everything that followed (§7). |
| `vital_signs` | one row per tick (§7) | |

## 2. The seasonal tick, step by step (PROPOSED)

1. **Advance time and the world.** Season, weather roll, needs drift, resources produced and consumed, aging (§4).
   Pure code.
2. **Retrieve memories.** For each living named person, pick the 3–5 memories most likely to surface: vivid,
   recent, emotionally strong, or sharing a symbol with something that just happened. Pure code.
3. **Dream.** Each named person dreams once per tick with the run 4 model (the best checkpoint at that time),
   primed with fragments of their retrieved memories. The tag comes from temperament: melancholic → `<tale>`,
   choleric → `<saga>`, sanguine → `<dream>`, phlegmatic → `<myth>`, with a 30% chance of a random tag so nobody
   is fixed. The mode-switching sampler can blend tags later.
4. **Interpret.** The 8 most salient dreams and events of the tick (by surprise, symbol recurrence, emotional
   weight, and anything planted) are interpreted by the people involved, through a small instruct model given the
   person's traits, needs, beliefs and relationships. The output is a belief (interpretation and confidence) or
   an intention ("I will go to the stone at dawn").
5. **Propose.** The storyteller is given the world summary, recent events, intentions and needs. It proposes
   4–6 actions or events: people acting on intentions, or the world acting (storm, illness, a ship on the horizon).
6. **Validate.** The world engine checks each proposal against the rules (§3) and resolves it as success,
   partial, failure or rejected. All of them are logged.
7. **Record.** Accepted outcomes are written to `events` as template text. Objects, places, people and townsfolk
   update. Witnesses get memories.
8. **Extract symbols.** New dreams and events are scanned for recurring images, batched 5 at a time. Each candidate
   is matched by embedding to existing `symbols` (a match increases its frequency) or creates a new one.
9. **Update and spread beliefs.** People who witnessed or heard of an event may form or revise a belief. Beliefs
   spread along relationships: a person's chance of adopting a belief rises with the teller's strength and
   standing and with how well it fits what they already believe. Confidence changes when evidence repeats or
   contradicts. Once a year someone may write a chronicle.
10. **Log vital signs.**

## 3. Validation rules (PROPOSED)

- **Rejected (impossible; logged, not an event).** The actor is dead, absent or a child. The object or place
  doesn't exist. The action breaks physics or the season (planting in winter, sailing in a winter storm without a
  boat). A cause from nowhere ("the gods send fire"). Or the proposal *asserts a meaning* ("the omen tells them…").
  Each rejection records which rule it broke.
- **Possible: roll for the outcome.** Chance = base rate for the kind × the actor's relevant traits × needs ×
  resources × weather.
  - **Success:** the full effect, with costs paid.
  - **Partial:** a reduced effect (half a harvest, a wall that leans) with full costs.
  - **Failure:** costs paid and no effect, sometimes with a side-effect (an injury, a lost tool).

  A failed attempt is still a fact and is recorded as an event; it often matters more than a success.
- **Strange but possible.** The storyteller may propose rare natural events (a stranded whale, a comet, a red
  tide) out of a "strangeness budget" of about 2 per year. Beyond that they are rejected as "budget spent".
- **Creator plantings always enter the world** as an arrival or a discovery. Everything after that goes through
  normal validation.

## 4. The simplest rules that could work (PROPOSED)

- **Resources (3):** food, materials (wood and stone), goods (tools, cloth, wine). Fields, sea and groves produce
  food by season; building costs materials.
- **Needs (5):** hunger, warmth, safety, belonging, standing. They drift each tick and are eased by resources or
  events. Unmet needs raise the chance of conflict, migration or illness.
- **Seasons and weather:** spring sowing; summer fishing and building; autumn harvest; winter storms and scarcity.
  Each tick rolls the weather from a seasonal table (calm / rain / heat / storm / drought).
- **Aging and death:** +1 year per day. Annual death chance rises gently after 50 and steeply after 70, and is
  raised by hunger, illness and injury. A named death promotes a townsperson if the crowd has someone suitable.
- **Births:** spouses aged 18–40 have about a 25% chance a year, scaled by food. Townsfolk use the same rates
  applied to counts.
- **Forgetting:** memory vividness × 0.8 per tick; recalling or retelling it adds 0.3. Below 0.1, the memory is
  forgotten.
- **Distortion:** each retelling has a 15% chance of changing one detail (who was there, where, the weather), or of
  absorbing a symbol from the teller's recent dreams. The memory's `source_id` still points at the true event,
  so the gap between the record and what people remember can be measured.

## 5. Genesis (PROPOSED except where locked)

- **LOCKED:** the founders arrive at an empty Mediterranean shore and build Corva from nothing. An inscription is
  already there; nobody knows who made it or can read it.
- **The founders:** 25 named people (5 households and 4 people travelling alone), ages 2–64, plus about 40
  unnamed people who become the first townsfolk. They arrive together on two ships.
- **Why they came:** each person has their *own* reason, recorded as a memory, not a fact about the group: flight
  from a war, exile, debt, trade, following a dream, or simply going where their family went. The founders don't
  agree on why they left, so that disagreement exists from day one.
- **The inscription:** an `objects` row: a weathered standing stone near the spring, with lines of marks. Its
  marks are generated once as a random glyph sequence. **No translation exists anywhere**, not in the database,
  not in code, not in prompts.
- **First contact:** the inscription enters the world as an event at tick 1 ("Ione found a marked stone by the
  spring"). Witnesses form memories. The interpretation step (§2.4) then produces each person's first beliefs about
  the stone from their own traits, with low confidence. Nobody, including the storyteller, is given a
  suggested reading.
- **Year 0 goals:** water, shelter and the first harvest. The storyteller is biased toward survival proposals for
  the first 3 years.

## 6. Daily compute budget (PROPOSED)

The pretrained instruct model is the same family as the editor (Qwen2.5-1.5B on CPU), at about 20 seconds a call.
That allows about 170 calls in ~57 minutes. Dreams come from our own run 4 model (about 2 seconds each), which
doesn't count against the pretrained-model call budget.

| Step | Calls per tick | Calls per day | ~Minutes |
|---|---:|---:|---:|
| Dreams (run 4, 25 per tick) | (100 small) | (100) | ~4 |
| Interpretations | 10 | 40 | 13 |
| Storyteller proposals | 4 | 16 | 6 |
| Symbol extraction (batched) | 5 | 20 | 7 |
| Belief formation and revision | 10 | 40 | 13 |
| Chronicles and faction practices | 2 | 8 | 3 |
| Creator planting reactions | n/a | ~10 a week | 2 |
| Reserve (retries, genesis, spikes) | 9 | 36 | 12 |
| **Total** | **~40** | **~160** | **~60** |

The time advance, memory retrieval, validation, recording and belief spread are all plain code.

## 7. Vital signs, and how to read the proposal log (PROPOSED)

Logged every tick:
- population (named and crowd), births, deaths, food stores
- crowd mood
- number of beliefs; **belief diversity** per subject (how widely interpretations differ); mean confidence
- faction count and sizes; polarisation (share of conflicting belief pairs between factions)
- new symbols, and the top 5 symbols by frequency
- memory drift (share of memories distorted)
- proposal acceptance rate, by kind
- reach of each planting

**Reading the storyteller log:**
- **Healthy:** 40–70% of proposals accepted, with varied rejection reasons.
- **Over 85% accepted:** the rules are too loose, or the storyteller is playing safe. The world will get bland.
- **Under 30% accepted, the same reason repeating:** the storyteller misunderstands a rule. Fix its prompt, not
  the rule.
- **Frequent "asserts a meaning" rejections:** the storyteller is drifting into narrating. Tighten its prompt.
- **Belief diversity falling toward one view per subject:** a monoculture. That's interesting, but worth watching.
- **No new symbols for many days:** dreams are stagnating. Reconsider the model, the tags or the memory seeds.

## 8. Open questions for Daniel

1. Should the founders' homeland exist anywhere (a name, a sea they crossed), or only in their conflicting memories?
2. Can the creator see interpretations as they form, or only weekly summaries? Seeing everything may tempt you
   to steer.
3. Can a belief change the world indirectly (people *act* on beliefs, e.g. building at the stone), or should
   belief-driven actions be limited in early years?
4. Should anyone ever be able to *learn to read* the inscription, i.e. get a translation that is itself only a
   belief? Or is it unreadable forever?
5. Does the crowd dream, in aggregate (a "dream of the town" each season), or only the 25?
6. Can named people leave Corva or found a second settlement, and do strangers arrive other than through your
   plantings?
7. Is the storyteller one voice, or several with different tastes (harsh / gentle / strange) taking turns?
8. Should Phase 1.5's morning wallpaper show one inhabitant's dream from the night, and whose?
9. Where does the simulation run daily: a scheduled cloud session, Kaggle CPU, or your laptop?
