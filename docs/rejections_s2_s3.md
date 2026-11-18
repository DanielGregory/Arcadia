# Why proposals were rejected, seasons 2 and 3

*From `storyteller_proposals` in the sandbox (the engine's own log). Season 1 is left out: its 7 rejections were
actors that weren't real ids (5 "no such person", 2 "no target house"), which schema-guided ids fixed for season 2.*

## The count, by rule

| Rule broken | Season 2 | Season 3 | Dramatic actions among them |
|---|---:|---:|---|
| `already acting` (one action per person a season) | 9 of 9 | 10 of 10 | 4 accusations, 3 marriage proposals, 1 confession, 1 "expose" |
| any other rule | 0 | 0 | |

Every rejection in both seasons was the same rule, and in every case it was the house's **second** proposal.

### Season 2 (spring, year 1)

The storyteller named the house (`h1`...) as the actor of its second action; the engine then had the house's head
carry it out, and the head had already acted with the first. Rejected: Corvane's accusation of Galen Theren,
Solenne's accusation of House Corvane, Damaris's marriage proposal, Cassian's investigation, Severin's meeting,
and four searches.

### Season 3 (summer, year 1)

After the season 2 fix (a person who already acts hands the action to a free member), the storyteller named the
house **as a group** for both actions. The group's one action was used by the first, and the stand-in rule did not
yet cover groups, so all ten second proposals were rejected: Cassian's accusation, Damaris's confession, the
marriage proposals of Theren and Aurelian, Severin's "expose", five threats. (Fixed after season 3: a group's
second action now goes to a free member of the house too. With the current rules all 19 would have been carried
out, every house having two or more free adults.)

## Rules that block dramatic actions too readily

1. **Order decides who yields, and the storyteller puts routine moves first.** In 17 of the 19 houses whose
   second proposal was rejected, the first was routine (threaten, search, investigate) and the second dramatic or
   unusual. The one-action rule then always cost the drama.
2. **The repeat penalty is city-wide.** Each use of an action family this season multiplies its next chance by
   0.6, whichever house used it. A house's first accusation of the season can start at 0.7 x 0.36 = 0.25 because
   two other houses accused someone earlier.
3. **Marriage is hard and silent.** Base 0.4, plus 0.3 x the target house's feeling: between houses that dislike
   each other it falls near 0.1, and failure is only "it came to nothing". The one marriage proposal that was
   resolved (Damaris, season 2) failed.
4. **Confession needs a single listener.** `confess` requires a target person, so "confess before the council" is
   rejected for want of a target, and a house as a group cannot confess at all (right: only a person can).

## Proposed looser versions (PROPOSED: not applied; say which to adopt)

| # | Rule | Now | Proposed |
|---|---|---|---|
| 1 | Order within a house's proposals | first come, first served | **Dramatic first:** resolve marriage, accuse, confess, alliance, flee, bribe and insult before routine families, so if anyone yields to a stand-in it is the routine act. |
| 2 | Repeat penalty | x0.6 per earlier use in the city | **Per house:** x0.6 only for the same house repeating a family; other houses' uses cost x0.9. |
| 3 | Marriage chance | 0.4 + 0.3 x feeling | **0.5 + 0.25 x feeling**, and a partial result becomes **talks** (a `betrothed`-pending tie that can be confirmed or broken next season); a refusal cools the two houses' feelings a little, so it is a story, not "nothing". |
| 4 | Confession target | a person, required | **Optional:** with no target it is a public confession before the city (everyone's beliefs updated as hearsay); with a target, private as now. |
| 5 | Drives | no effect on chance | **A principal acting on one of their own drives gets +0.1** (Marius on "get Livia back", Lucan on his honour): the people with the most at stake push hardest. |

Season 3's interpretation and lean tables are in `docs/season3_log.md`.
