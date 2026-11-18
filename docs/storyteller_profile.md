# Storyteller speed: prompt length per call, seasons 1 to 3, and the caps

## What a call costs (Qwen2.5-3B-Instruct, bfloat16, this 4-core CPU)

Measured on the season 4 world (one house at a time):

| Part | Cost |
|---|---|
| Reading the prompt | ~7 s for 1,771 tokens, ~5 s for 1,300 (roughly linear) |
| Writing the answer | ~0.24 s per output token, schema-guided JSON included |
| First call after loading | the weights are read from disk on first use: **208 s** on a cold machine |

So the answer's length matters more than the prompt: 175 output tokens is ~42 s, 320 would be ~77 s.

## Prompt length per house call

The storyteller's system prompt is 294 tokens. The house's context, rebuilt from the saved state of each season:

| Season (its input) | Mean | Max | Biggest parts, all ten houses together |
|---|---:|---:|---|
| 1 (winter, year 0) | - | - | not rebuildable: season 1 ran the 1.5B model on an older, shorter prompt |
| 2 (spring, year 1) | 1,220 | 1,247 | family ties 4,172; other houses' notable people 2,590; recent events 1,080; legends 973 |
| 3 (summer, year 1) | 1,296 | 1,370 | the same, recent events 1,240 |
| 4 (autumn, year 1), before the caps | 1,376 | 1,494 | the same, recent events 1,410 |
| **4, with the caps** | **897** | **995** | |

Growth came from recent events (longer each season) and the feelings line; the family ties (every house got all the
ties of every notable person, ~420 tokens each call) were the largest fixed part.

## Seconds per call

| Season | Storyteller step | Calls | Seconds per call | Why |
|---|---:|---:|---:|---|
| 2 | 488 s | 10 | ~49 | |
| 3 | 737 s | 10 | ~74 | ~200 s of it was the weights being read on the first call; the rest ~53 s (longer answers) |
| test on season 4, with the caps | | 2 | **38.3, 39.4** | 1,166 to 1,280 prompt tokens, 172 to 177 output tokens |

## The caps (config/rules.yaml, storyteller)

- **Family ties:** only the house's own people's (`max_ties: 12`); other houses' ties were rarely used.
- **Legends:** the house's own, cut to 200 characters (`legends_in_context: 1`, `legend_chars: 200`).
- **A token budget** for the house's context (`max_context_tokens: 1300`): if it is over, the least needed parts are
  halved in order (legends, family ties, recent events, other houses' notable people, feelings) until it fits. The
  members, their drives, the house's state and the strategy question are never cut. At 1,300 tokens plus the system
  prompt the reading costs ~7 s however long the history grows.
- **Shorter answers:** strategy at most 150 characters, each "why" 110, max 240 new tokens: ~150 to 180 tokens, ~40 s.
- **The weights are read when the model is loaded** (a 16-token warm-up), so the load step pays for it, not the
  first house.
- **Every call is now logged** (`model_calls`: prompt tokens, output tokens, seconds), and each season log has a
  profile table, so a creeping slowdown shows at once.
