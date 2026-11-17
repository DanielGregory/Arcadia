# Arcadia: the master vision

> In Poussin's painting, shepherds find an inscription they can't agree on.
> Arcadia is a world built the same way: it records what happens, never what it means.

Arcadia is a simulated world that runs on its own, day after day. Things happen in
it; its inhabitants dream, remember and argue about what those things meant. Nobody,
human or machine, decides the meaning. There is no master narrator.

## The four parts

### 1. The world engine: truth

The world engine is the single source of truth. It holds the world's state (places
such as Corva, the first city; people; objects; weather and sky; time) and the record
of what has actually happened. It applies the world's rules and decides what is
possible.

- It records **events**, never interpretations: "the river flooded the lower market",
  not "the gods punished the market".
- Nothing becomes real unless the world engine accepts it.

### 2. The storyteller (game master): proposes anything, reality decides

The storyteller keeps the world moving. It may propose anything: a storm, a stranger
at the gate, a birth, a theft, a miracle. A proposal is only a proposal: the world
engine checks it against the world's state and rules and accepts, changes or
rejects it. The storyteller never writes the history directly and never explains what
an event means.

### 3. The inhabitants: interpret through their own beliefs

The inhabitants live inside the record. Each has their own memories and beliefs, and
each interprets the same events differently: a flood can be an omen, a punishment, bad
luck or engineering. Their interpretations shape what they do next and what they
dream, and they can disagree permanently. Beliefs spread, change and harden into
culture, but none of them is ever marked "correct".

### 4. The transformer: language and imagination

The transformer is the world's imagination, not its authority. It supplies
language: dreams, sayings, stories, the words inhabitants use to describe what
happened to them. It is trained from scratch on an old, mythic literary voice
(Homer, Ovid, Theocritus, Virgil, Hesiod, Aesop), a dream layer (Dunsany, MacDonald,
Coleridge, Carroll, the Arabian Nights), a little seasoning, and real dream reports
from DreamBank. What it writes can inspire proposals and beliefs, but it never
changes the world's state by itself.

## No master narrator

No single part tells "the story". The world engine knows what happened but not what it
means; the storyteller proposes but does not decide; the inhabitants interpret but
cannot change the facts; the transformer imagines but has no authority. Meaning exists
only as the inhabitants' competing beliefs, the way the shepherds in Poussin's
painting read the same inscription and cannot agree.

## Phases

1. **Dream engine:** train the transformer to generate dreams. *(current)*
1.5. **Morning wallpaper:** each night's dream, rendered as a daily image.
   Built: `daily/morning.py` launches `daily/morning_job.py` on Kaggle (dream 12,
   select, remember, paint with Corva's style, set the text); the Today tab shows
   it and `daily/mornings/` keeps the record.
2. **Memory and Sky:** the world remembers past dreams, and the sky reflects them.
3. **World and beliefs:** the world engine, the storyteller and inhabitants with beliefs.
4. **Culture and release:** shared stories, rituals and a public release.

The world engine, the storyteller, the database (Supabase) and the public site
(Vercel) wait until Phase 1 passes its gate.
