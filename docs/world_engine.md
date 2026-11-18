# World engine: design spec v2

Status: v2, for Danny to edit. **LOCKED** = Danny's decision. **PROPOSED** = Claude's suggestion, open to change.
Follows `docs/VISION.md` and the seed story in `docs/seed_history.md`. v0 is built as an offline sandbox (§11).

## 0. Ground rules

- **LOCKED: the core architecture (VISION.md).** The world engine is the truth. The storyteller proposes anything;
  the world engine validates it. Inhabitants interpret through their own beliefs. The transformer gives language and
  imagination. There is no master narrator.
- **LOCKED: time.** One Arcadia year per real day, as 4 seasonal ticks. Adjustable.
- **LOCKED: the world.** One island (~5–10 km): Corva on the harbour, 2–4 villages in the hills, a central mountain,
  rivers, forests, olive groves. Visual anchor: terraced white houses with terracotta roofs climbing cliffs above the
  sea, Greek temples, golden light.
- **LOCKED: Corva is already old on Day 1.** No empty shore, no founders' arrival: its founding is legend.
  **There is no inscription.**
- **LOCKED: creator.** Danny plants one thing per week (object, stranger or dream) and never controls its meaning.
- **LOCKED: budget.** About 1 hour of CPU per daily run.
- **LOCKED: the hard rule.** No table stores what anything means. Facts live in objects, events, places and symbols;
  all meaning lives in `beliefs`, per person, with a confidence.
- **PROPOSED: enforcing the hard rule.**
  1. No column named meaning, significance, purpose, omen or the like outside `beliefs` (`world_meaning_lint()`).
  2. Event text is written by the engine from templates. The storyteller's own wording stays in the proposal log.
  3. Anything that interprets is attributed to a person or a house (accounts, chronicles, legends) or computed as a
     view over `beliefs` (house feelings, faction views). Never stored as fact.
  4. Proposals whose wording asserts a meaning ("the omen…", "fate…", "the gods want…") are rejected.

## 1. The seed (LOCKED: `docs/seed_history.md`)

Day 1 is the season after **the Flight from Corva**: at the autumn festival of the sea, Livia Corvane (20, only
daughter of Marius Corvane, betrothed to Lucan Valerius) and Soren of the Harbor (22, a foundling raised by Galen
Theren) vanished together. The public account (rumours of kidnap, of a willing flight, of a Theren plot; a sailor's
"east", a merchant's "northern road"; the old temple servant at the western gate; the old priestess's dream of a
golden ring sinking and two stars disappearing) enters the world as events and as each person's first beliefs.

- **Private truths** are character-only memories, never shown in public reports: Livia's (love, and also escape),
  Neria's (she knew, helped, and alone knew the night), Tiberon's (real resentment, never acted on). **Galen's**
  knowledge of Soren's father is undecided even to the creator and is **not stored at all**; nothing may resolve it.
  Soren's father has no lineage row: an unknown parent is a missing row, never an invented one.
- **Sealed at genesis:** the lovers' true location is chosen by the engine at random and stored in `sealed_facts`,
  readable by the engine only. No report prints it. (**PROPOSED:** an in-world discovery is possible: a search of
  the right place can, rarely, turn up a trace. Such an event is stored `sealed` and redacted in reports until Danny
  decides how a discovery should surface.)

## 2. The houses (LOCKED structure; roles an accepted draft)

Houses are **landed families first** (Greek *oikos*, Roman *gentes*). Each head controls land, marriages and
alliances. **Each house holds ONE hereditary claim**: rights and influence, not manual jobs.

| House | Role (accepted draft) | Hereditary claim (**PROPOSED** wording) | Head |
|---|---|---|---|
| Corvane | Ruling house; claims to be the founders. Old, proud, under pressure. Livia's house. | The council seat: the presiding voice | Marius Corvane |
| Valerius | Rising military power; wealth from ships and war. Ambitious, disciplined. Lucan's house. | Command of the war fleet and the harbour guard | Gaius Valerius (**PROPOSED**) |
| Theren | Old olive and vineyard land in the hills. Quiet, kind, guarded. Took in Soren. | The oldest grove rights: the first pressing | Galen Theren; eldest son Tiberon |
| Aurelian | Temple and priesthood. Pious, secretive, kingmakers. | The high priesthood of the sea temple | Theodric Aurelian (**PROPOSED**) |
| Marcellan | Merchant fleet, trade with other islands. Practical, plays all sides. | The harbour dues and trading charters | Octavia Marcellan (**PROPOSED**) |
| Cassian | Stonecutters and builders of the terraces. Hot-tempered, proud. | Cutting the quarries and building the terraces | Rufus Cassian (**PROPOSED**) |
| Severin | Law and judgment; their elders settle disputes. Severe, rigid. | The judges' bench | Aldric Severin (**PROPOSED**) |
| Damaris | Healers and midwives. Small, trusted, knows everyone's secrets. Neria serves here. | Attending every birth and death | Hesione Damaris (**PROPOSED**) |
| Veyra | Mountain herders and hunters. Isolated, suspicious of Corva. | Grazing and hunting the mountain | Kael Veyra (**PROPOSED**) |
| Solenne | Faded nobility, once great, now nearly gone. Bitter. | A seat of honour at the festival (all that remains) | Seraphine Solenne (**PROPOSED**) |

Everyone not in the seed story is a **PROPOSED placeholder** (`proposed = true` in the database) for Danny to
rewrite: the heads above marked so, their heirs and families, the old priestess's name (Ismene), the old temple
servant (Philo), the sailor (Dion) and the merchant (Hesper), and Livia's mother (Aelia, dead eight years; the ring
was hers).

**PROPOSED stores:** each house holds food, goods and materials; its land yields them by season
(`config/rules.yaml`, `houses.yield`); members and clients eat.

## 3. Population (LOCKED tiers, PROPOSED numbers in rules.yaml)

- **~25 principals:** full agents. They dream, interpret, and act through the storyteller.
- **~75 side characters:** named, in houses. They age, marry, die and dream, and act by simple rules.
- **~200 townsfolk:** counts only, as clients of houses or unattached.
- **Houses act as groups:** one storyteller call per house per season, proposing actions by its members.
- **Promotion:** a side character becomes a principal when something happens to them; a townsperson becomes named
  the same way (Soren is this mechanic in story form). **PROPOSED trigger:** being an actor or target in an
  event, or the teller of a dream that gets interpreted, twice in a year.

## 4. Patronage (LOCKED)

Townsfolk attach to houses as **clients**. A house's client count and average loyalty are its real power. Houses must
feed and protect their clients; in crises clients can defect; some townsfolk stay unattached. When houses choose
sides, their clients follow.

**PROPOSED rules (rules.yaml `clients`):** each tick a house feeds its clients from its stores (loyalty rises a
little if it can, falls if it can't); feasts and rites raise loyalty and draw in some of the unattached; being
accused or slighted in public lowers it; below a loyalty floor a share of clients leave to the unattached.
Recorded per tick in `house_clients` (count, loyalty, gained, lost). **Not yet in v0:** clients following their
house into a conflict (needs alliances and sides, §6).

## 5. Dreaming (LOCKED)

Every named person dreams each season (**run 5 model**, the voice chosen by temperament). Most dreams are
forgotten; some are shared; **only shared dreams are interpreted**. Forgotten dreams are still stored and feed
symbols and the Sky. There are occasional townsfolk **rumour dreams** of unknown origin.

**PROPOSED:**
- **Temperaments and voices:** mystic → `<dream>`, romantic → `<poem>`, traditionalist → `<myth>`, sage → `<wisdom>`,
  pragmatist → `<chronicle>`, skeptic → `<tale>`; 20% of the time any voice.
- **Seeds:** 60% of dreams begin from an image in the dreamer's own memories (the gold ring, the harbour at night,
  two stars, the western gate) or from their house's land.
- **Remembering:** chance by temperament (mystic 0.85 … skeptic 0.12) × vividness (length, variety, whether the
  model ended it itself).
- **Sharing:** a remembered dream is told to someone close (a relationship or a housemate), more often by the warm
  and by mystics. Absent people (the lovers) have no one in Corva to tell.
- **Interpreting:** the most salient shared dreams (vivid, full of the Flight's images, dreamed by principals or
  mystics), up to 8 a season, are interpreted by the dreamer through the instruct model. The result is a belief
  (reading, confidence, and optionally a stance toward a house) and perhaps an intention. The listener takes up the
  reading at a lower confidence.

## 6. Generational tension (LOCKED)

The Flight's fallout should echo for generations. **Inter-house events** (insults, debts, broken oaths, marriages,
betrayals) are permanent facts in the event log, tagged with the houses they touch. **How one house feels about
another is the aggregate of its members' beliefs about those events**: inherited by children, fading slowly,
reopened when new events touch old wounds. Wars emerge from grievances, scarcity, clients and alliances, and a
spark. They are never scripted.

**PROPOSED mechanics (rules.yaml `beliefs`):**
- A belief may carry `about_house` and a `stance` (−1..1). The view `house_feelings` is the confidence-weighted
  mean stance of a house's members toward another house. It is computed, never stored.
- Each inter-house event gives the target house's members a belief toward the actor's house (hearsay
  confidence) and the actor a belief toward the target, with stances by kind (accusation −0.6, gift +0.4…).
- **Fading:** inter-house beliefs lose 3% confidence a season. **Reopening:** a new event between the same two houses
  lifts their members' old negative beliefs about each other. **Inheritance:** children hold their parents'
  inter-house beliefs at 60% (applied at genesis; at birth later).
- Genesis seeds some older grievances (**PROPOSED**, marked in the event facts): Solenne lost the council seat to
  Corvane (−62); Valerius was given the fleet (−30); Severin judged for Marcellan against Cassian (−11); the council
  fined a Veyra herder for grazing Theren groves (−5).

## 7. Legends (LOCKED)

Stories become **legends, retold differently by each house**. Legends a character knows, in their house's version,
are **retrieved into the storyteller's context**, so past stories inspire, warn and shape future choices. Similar
events can recur.

**PROPOSED:** `legends` holds attributed tellings (house, title, text, the events they grew from). Genesis gives
each house its own version of the founding (all **PROPOSED**), plus the city's. The storyteller sees up to 2 per
house. **Not yet in v0:** turning the Flight itself into legends (a yearly step: each house retells the year's
biggest events in its own version, from its members' beliefs).

## 8. Data model (Supabase; v0 mirrors it in local SQLite)

Applied: `20261117_world_schema.sql` (people, relationships, townsfolk, places, objects, events, dreams, symbols,
memories, beliefs, factions, chronicles, storyteller_proposals, creator_plantings, vital_signs) and
`20261118_houses.sql` (backup first: `data/backups/supabase_20261118T1343Z`):

| New | Holds (facts only) |
|---|---|
| `houses` | name, claim (one hereditary right), land, seat, head, stores, proposed |
| `people` + | tier (principal / side), dream_temperament, absent, proposed |
| `house_members` | house, person, role (head / heir / spouse / child / kin / fosterling / servant / retainer), joined, left |
| `lineage` | parent, child, kind (blood / adoptive / fostered). A missing row is an unknown parent |
| `house_clients` | per tick: house (or NULL = unattached), count, loyalty, gained, lost |
| `legends` | house (whose version), title, text, events it grew from |
| `beliefs` + | about_house, stance: the material of house feelings |
| `events` + | houses touched; `dreams` + recalled, shared_with; `storyteller_proposals` + house |
| view `house_feelings` | per pair of houses: confidence-weighted mean stance |
| `sealed_facts` | truths only the engine may read (row level security on, no policy) |

**PROPOSED, sandbox only so far:** relationship kinds `betrothed` and `lover`, and `memories.private` (marks the
private truths). They go to Supabase when the sandbox does.

## 8b. After the season 1 review (Danny's decisions, PROPOSED details)

- **Drives** (`world/drives.py`): each principal has 1–3 active drives a season, from their situation and beliefs:
  Danny's story drives (Marius: get Livia back; Lucan: restore his honour; Galen: torn between Soren and the peace;
  Tiberon: resentment; Neria: fear of discovery) while their situation holds, plus drives derived from their reading
  of the Flight, an old grievance between houses, last season's dream intention, and (for heads) the house's state
  and aim. Stored in `drives`, per person: an aim, never a fact.
- **Open actions:** the storyteller may propose any action. A list (search, accuse, bribe, spread a rumour, feast,
  propose a marriage, threaten, form an alliance, pray, flee, investigate, confess) is inspiration, not a menu. The
  engine sorts each into a family by keywords (`rules.yaml validation.kinds`) to resolve it; unmatched actions are
  resolved as plain attempts. Repeating a family within a season lowers its chance (×0.6 each time), and the
  storyteller is told what has already been done.
- **Strategy:** each house call first answers a strategy question about the Flight.
- **Actors are ids:** the actor must be a person id (`p12`) or house id (`h3`) from the list given, enforced by
  schema-guided decoding; an unusable reply is retried once with the reason.
- **Schema-guided JSON** (`world/llm.py`, lm-format-enforcer) for proposals and interpretations; forgiving parsing
  only as a fallback.
- **Continuity:** the model is given the true family ties of everyone it is shown. Accounts and chronicles may
  contain false claims: they are stored in `chronicles` as the author's own claims, and nothing in them ever writes
  to facts. Only validated events change the world. First-person accounts are checked for third-person slips and
  retried once.
- **Nothing modern:** interpretations first retell the dream in Corva's own terms ("a beast of iron that ran without
  horses"); the retelling is what the dreamer remembers and tells. The raw dream stays in `dreams` (and the log).
- **Models:** the storyteller and the accounts use Qwen2.5-3B-Instruct; interpretations keep the 1.5B (loaded in
  turn: both don't fit in 15 GB together).

## 9. The seasonal tick (PROPOSED; v0 runs all of it)

1. **Advance:** land yields by season, members and clients eat; whether each house could feed its clients.
2. **Dream:** every named person (and 2 rumour dreams), run 5, voice by temperament, seeds from memories.
3. **Recall and share:** most dreams forgotten (still stored); remembered ones become memories; some are told.
4. **Interpret:** only shared dreams, the most salient first (≤ 8): belief, stance, intention.
5. **Propose:** one storyteller call per house (Qwen2.5-1.5B-Instruct, CPU). Context: the house's claim, land,
   stores, clients, members who can act, who is missing, its legends, its feelings toward others, its principals'
   beliefs and intentions, recent events. Up to 2 actions from a closed vocabulary, as JSON.
6. **Validate:** the engine checks each proposal (§10) and rolls the outcome; every attempt is logged.
7. **Record:** outcomes become events, in template text.
8. **Update:** beliefs from events (stances toward houses), old wounds reopened, fading, client loyalty and
   defections.
9. **Vital signs** (§12).
10. **Report:** the season's chronicle from several viewpoints, and the log.

**Not yet in v0:** ageing, births, deaths and marriages; promotion; symbol extraction; belief spread beyond the
houses involved; factions; creator plantings; yearly legends. All are designed above and come next.

## 10. Validation (PROPOSED; parameters in `config/rules.yaml`)

- **Rejected (logged, not an event), with the rule broken:** unreadable reply; asserts a meaning; unknown kind;
  no such person, place or house; actor dead, absent or a child; actor not of the proposing house; already acting
  this season; a house aiming at itself; cannot afford the cost; a question to someone absent.
- **Possible: roll.** Chance = the kind's base × the season's factor (searches and trade are harder in winter) ±
  the actor's relevant trait (pride for accusations, piety for rites, warmth for gifts…); alliances and marriage
  offers also depend on how the target house feels. Success, partial, or failure: a failure is still an event.
- **Searches** consult the sealed location: the wrong place always yields "no trace"; the right place yields a
  trace only rarely (`search_find_chance`), and that event is sealed in reports.
- **Strangeness budget:** about 2 rare natural events a year (not yet exercised in v0).

## 11. World engine v0: the offline sandbox

`python -m world.run_season --fresh` runs genesis, then one season. It uses a local SQLite file
(`data/world/sandbox.db`, git-ignored) with the same tables as Supabase. It does not touch Supabase, the
wallpaper, the 3D world or the daily job.

| File | What it does |
|---|---|
| `world/genesis.py` | Corva on Day 1, from the seed story; placeholders marked PROPOSED; the sealed location |
| `world/tick.py` | One seasonal tick, steps 1–9 |
| `world/report.py` | `docs/chronicle_season<N>.md` (in-world) and `docs/season<N>_log.md` (proposals, runtime, vital signs) |
| `world/backup_supabase.py` | Backs up every Supabase table before a migration |
| `config/rules.yaml` | Every rule parameter |

## 12. Vital signs, and how to read the proposal log (PROPOSED)

Logged every tick: population by tier; dreams dreamed, remembered, shared and interpreted; beliefs; how many
different readings of the Flight there are and their **diversity**; proposals by outcome; **acceptance rate** and
rejection reasons; clients per house (count and loyalty); the coldest and warmest feelings between houses; runtime
and model calls per step.

- **Healthy:** 40–70% accepted, with varied rejection reasons.
- **Over 85% accepted:** the rules are too loose, or the storyteller is playing safe.
- **Under 30% accepted with one reason repeating:** fix the storyteller's prompt, not the rule.
- **Many "asserts a meaning" rejections:** the storyteller is narrating. Tighten its prompt.
- **Flight belief diversity falling toward one view:** a consensus forming. Interesting, but worth watching.

## 13. Daily budget (PROPOSED)

Measured in v0 (one season) and projected to 4 seasons a day: see `docs/season1_log.md`. Run 5 dreams cost about
4 s each (about 100 a season). Instruct-model calls cost about 20–30 s each: about 8 interpretations, 10
storyteller calls and 5 chronicle passages a season.

## 14. Open questions for Danny

1. **Discovery of the lovers:** should a search ever be able to find them, and if so, how should it surface to you,
   given that the location is sealed from you?
2. **The lovers' own dreams** are dreamed and stored, but they have nobody to tell. Should they ever reach Corva
   (as rumour dreams, say)?
3. **Promotion triggers:** is "touched by events twice in a year" right?
4. **Clients in conflict:** when two houses clash, should clients be able to switch to the winning side mid-season,
   or only at season's end?
5. **Placeholders:** the 7 heads and their families, the claims as worded, the older grievances and the founding
   legends are yours to rewrite.
6. **Ageing, births and deaths** come next: one year per day means a principal ages fast. Are generations meant to
   turn over within a few weeks?
7. Where does the daily run happen once it leaves the sandbox: a scheduled cloud session, Kaggle CPU, or your laptop?
