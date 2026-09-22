# FINDINGS 04 — Replay evaluations, three-judge comparison

Three replay batches of all 136 traces from `Genie_trajectories15_sep_2026.json`
into the non-production genie (`gin-XXXXXXXXXXXXXXXXXXXX`), evaluated with three
judges each. **Section 1**: intelligent-router backend (mixed gpt-5.6
terra/sol/luna). **Section 2**: fixed `gpt-5.6-luna`. **Section 3**: fixed
`gpt-5.6-terra`.

Date: 2026-09-20

## Overview

| Backend | Quality — traces with any ungrounded / redundant / misaligned step (judge majority, per trace, n=136) | Tool errors → recovered? (judge majority) | Cost (per replay) | Median latency (per turn) | Backend mix | Model change between turns |
| ------- | ----------------------------------------------------------- | -------------------------- | ----------------- | ------------------------- | -------------------------- | -------------------------- |
| **Router** (intelligent) | best — 11% / 2% / 38% | 0 errors | $4.34 | 11.0s | terra 64% / sol 23% / luna 13% | **47%** of transitions |
| **Luna** (fixed gpt-5.6-luna) | 15% / 7% / 48% | 7 errors → 4 recovered / 3 not | $0.48 | 8.7s | luna 100% | 0% (fixed) |
| **Terra** (fixed gpt-5.6-terra) | 15% / 1% / 49% | 5 errors → 1 recovered / 4 not | $4.44 | 8.3s | terra 100% | 0% (fixed) |

Router = quality, luna = cost, terra = speed; no batch dominates all three.
The router's 47% turn-to-turn model churn (no stickiness) coexists with its
best quality — its edge comes from routing away from terra on terra-weak
steps. Details: quality §1–§3, cost/latency §4, trace-level §5, churn §6.

---

## Four Metrics for Quality Evaluation

- **Groundedness**: Are the tool-call inputs grounded in the user’s inputs and relevant conversation history? Are the agent’s responses grounded in the user’s inputs and tool results? Does the agent introduce any unsupported or hallucinated information?
- **Efficiency**: Does the agent avoid redundant, repeated, or unnecessary tool calls while still gathering the information needed to complete the task?
- **Adaptivity**: When a tool call fails or returns an error or insufficient result, does the agent appropriately adjust its approach—for example, by modifying the inputs, trying an alternative tool or strategy, or otherwise recovering from the failure?
- **Goal Alignment**: Are the agent’s tool calls and final responses relevant to and consistent with the user’s query and intended goal?

---



## Judges (shared context for all sections)

All evaluation calls at temperature 0 through the AIGW gateway
(`https://ai-gateway.example.internal/v1`):


| Judge             | Model id                         |
| ----------------- | -------------------------------- |
| gpt-4.1 (default) | `azure_internal_01/gpt-4.1`      |
| gemini-3.8-flash  | `vertex_global/gemini-3.8-flash` |
| glm-5.3           | `fireworks/glm-5.3`              |


Every result row is stamped with `judge_model`. A fourth judge,
`bedrock_internal_01/claude-sonnet-4-6`, is plumbed but unavailable: the AWS
account behind the gateway hasn't submitted the Anthropic use-case form
(HTTP 404 until then).

---



## Section 1 — Intelligent-router replay



### What was evaluated

The v2 replay: all **136 traces** from `Genie_trajectories15_sep_2026.json`
replayed into the non-production genie (`ITSM support Genie_v2 copy`,
`gin-XXXXXXXXXXXXXXXXXXXX`) via the headless API — one fresh conversation and
one constructed message per trace, with recorded history (user turns,
assistant replies, tool calls + results) embedded in the prompt
(`--construct-history` mode of `scripts/replay_trajectories.py`).

- Dataset evaluated: `Genie_trajectories_replay_intelligent_router_20_sep_2026.json`
(**226** `agent_chat_completion` records / 136 traces), collected from
Langfuse by `scripts/fetch_replay_trajectories.py`.
- Backend models during replay (chosen per-request by the intelligent
router): `openai/gpt-5.6-terra` ×144, `openai/gpt-5.6-sol` ×53,
`openai/gpt-5.6-luna` ×29. 3.33M tokens, $4.34 total (official price card,
see §5; Langfuse-reported $5.06 is based on stale prices).



### Result files (226 rows each; judge set is documented in "Judges" above)

- `results/full_evaluation_results_replay-intelligent-router-20-sep-2026.json`
- `results/full_evaluation_results_replay-intelligent-router-20-sep-2026_gemini-3.8-flash.json`
- `results/full_evaluation_results_replay-intelligent-router-20-sep-2026_glm-5.3.json`

Coverage: **226/226 records with valid verdicts from all three judges**
(zero error/None/Inconclusive rows remaining).

## Final verdicts


| Metric             | gpt-4.1                     | gemini-3.8-flash | glm-5.3         |
| ------------------ | --------------------------- | ---------------- | --------------- |
| **Groundedness**   | 205 Yes / 21 No             | 215 Yes / 11 No  | 205 Yes / 21 No |
| **Efficiency**     | 225 Efficient / 1 Redundant | 220 / 6          | 215 / 11        |
| **Adaptivity**     | 226 N/A                     | 226 N/A          | 226 N/A         |
| **Goal alignment** | 194 Aligned / 32 Misaligned | 158 / 68         | 165 / 61        |




## Three-way agreement


| Metric         | Agreement (n/226) | Reading                                                                                                                                       |
| -------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Groundedness   | **88%** (198)     | gpt-4.1 and glm-5.3 identical (21 No each); gemini lenient (11 No). Majority: ~9% of replayed steps ungrounded                                |
| Efficiency     | **95%** (214)     | Near-consensus; the replayed genie wastes almost nothing (1–11 redundant steps of 226 depending on judge)                                     |
| Adaptivity     | 100% (226)        | Vacuous — zero tool failures occurred in the replay environment, so adaptivity was never triggered (the Sept-15 production data had failures) |
| Goal alignment | **72%** (163)     | Genuine judge disagreement: gpt-4.1 flags 14% Misaligned, gemini/glm ~28%                                                                     |




### Trace-level results

Records grouped back to their 136 source traces (via
`metadata.conversation_id` → replay JSONL → original traceId); a trace counts
as negative on a metric if **any** of its steps is negative. Per judge, plus
the 2-of-3 majority:


| Metric (any negative step)  | gpt-4.1  | gemini   | glm      | Majority |
| --------------------------- | -------- | -------- | -------- | -------- |
| Groundedness (No)           | 15% (21) | 8% (11)  | 15% (21) | 11% (15) |
| Efficiency (Redundant)      | 1% (1)   | 3% (4)   | 7% (10)  | 2% (3)   |
| Adaptivity (Not Adaptive)   | 0% (0)   | 0% (0)   | 0% (0)   | 0% (0)   |
| Goal alignment (Misaligned) | 22% (30) | 49% (66) | 43% (59) | 38% (52) |




## Takeaways

1. **Groundedness is trustworthy** — two of three judges agree exactly;
  ~9% of replayed steps are ungrounded (mostly addressing the wrong user
   name, e.g. replying "TestUser" — the headless test identity — instead of
   the Slack user named in the message payload).
2. **Efficiency is clean** — the replayed genie makes almost no redundant
  calls.
3. **Adaptivity is untestable on this replay** — no tool failures occurred
  in the preview environment. Needs failure-containing traces to evaluate.
4. **Goal alignment needs human arbitration** — gpt-4.1 says 14%
  Misaligned, gemini/glm say ~28%. The ~63 split records (gpt-4.1 Aligned
   vs gemini/glm Misaligned) are the hand-check list before trusting either
   number.



## Failure log during the runs (for provenance)

- **GLM empty-content** `Inconclusive` **rows (66):** GLM spends `max_tokens` on
a separate reasoning field; `max_tokens=2500` was exhausted by reasoning on
long prompts, leaving `content` empty. Fixed by raising judge
`max_tokens` to 8000, dropping bad rows, and resuming.
- **Gemini** `TypeError: 'NoneType' object is not subscriptable` **(8):** the
small classifiers ran with `max_tokens=20` (redundancy-vs-fabrication) and
60 (failure classifier); Gemini's hidden reasoning exceeds that before any
visible text, so the gateway returned `message: None` and `call_llm`
crashed. Fixed by raising both classifier budgets to 2000 and hardening
`call_llm` to raise a clear "empty response" error. All 8 refilled clean.
- **gpt-4.1 one** `Inconclusive`**:** a degenerate-output glitch (gibberish
tokens) on one record; cured by a plain re-run.
- (Bedrock judge unavailability — see "Judges" above.)

---



## Section 2 — Fixed gpt-5.6-luna replay

Date: 2026-09-20 (second batch, after the genie's model was switched from the
intelligent router to fixed `azure/gpt-5.6-luna`).

### What was evaluated

Same 136 traces, same constructed-history inputs, replayed against the genie
now pinned to luna. Fetched from Langfuse into
`Genie_trajectories_replay_gpt-5.6-luna_20_sep_2026.json` —
**230 records / 136 traces** (backend verified: `gpt-5.6-luna-2026-07-09` on
230/230 records; no router).

Why 230 vs 226 records (Section 1): a record = one LLM step, and step counts
are chosen at runtime by the model. Luna answered more turns in a single step
(68 vs 61 single-step traces) but ran longer tool loops elsewhere (one turn
took 11 steps). Net +4 steps. Compare verdicts per trace/turn, never per
record position.

Result files (one row per record, `judge_model` stamped):

- `results/full_evaluation_results_replay-gpt-5.6-luna-20-sep-2026.json`
- `results/full_evaluation_results_replay-gpt-5.6-luna-20-sep-2026_gemini-3.8-flash.json`
- `results/full_evaluation_results_replay-gpt-5.6-luna-20-sep-2026_glm-5.3.json`

Coverage: **230/230 records judged by all three judges**, one permanent
single-cell gap:

- `ae80afcb…` — gpt-4.1 groundedness `Inconclusive`. This 12k-char
no-evidence transcript deterministically derails gpt-4.1 into degenerate
output (failed at temp 0 ×3 and temp 0.3; `finish_reason: length` at
8000/8000 tokens of gibberish). A token-budget increase cannot fix it —
the model never starts a verdict. Gemini and GLM judge it fine.



### Final verdicts (all 230 records)


| Metric             | gpt-4.1                               | gemini-3.8-flash | glm-5.3         |
| ------------------ | ------------------------------------- | ---------------- | --------------- |
| **Groundedness**   | 205 Yes / 24 No / 1 Inconclusive      | 195 Yes / 35 No  | 202 Yes / 28 No |
| **Efficiency**     | 220 Efficient / 10 Redundant          | 213 / 17         | 201 / 29        |
| **Adaptivity**     | 223 N/A / 3 Adaptive / 4 Not Adaptive | 223 / 4 / 3      | 223 / 4 / 3     |
| **Goal alignment** | 197 Aligned / 33 Misaligned           | 142 / 88         | 153 / 77        |




### Three-way agreement


| Metric         | Agreement         | Reading                                                                                                                 |
| -------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Groundedness   | **77%** (177/229) | Gemini strictest (35 No), gpt-4.1 most lenient (24 No) — pattern flipped vs Section 1, where gemini was the lenient one |
| Efficiency     | **90%** (207/230) | Consensus: more redundancy than the router run (10–29 vs 1–11)                                                          |
| Adaptivity     | **99%** (228/230) | 7 failure-response steps now exist (tool failures DID occur under luna); judges essentially agree on them               |
| Goal alignment | **70%** (160/230) | Same split as Section 1: gpt-4.1 flags 14% Misaligned, gemini/glm flag 34–38%                                           |




### Trace-level results

Records grouped back to their 136 source traces; a trace counts as negative
on a metric if **any** of its steps is negative. Per judge, plus the 2-of-3
majority:


| Metric (any negative step)  | gpt-4.1  | gemini   | glm      | Majority |
| --------------------------- | -------- | -------- | -------- | -------- |
| Groundedness (No)           | 15% (20) | 26% (35) | 18% (24) | 15% (20) |
| Efficiency (Redundant)      | 3% (4)   | 7% (9)   | 15% (21) | 7% (9)   |
| Adaptivity (Not Adaptive)   | 1% (1)   | 1% (1)   | 1% (1)   | 1% (1)   |
| Goal alignment (Misaligned) | 21% (28) | 60% (81) | 51% (70) | 48% (65) |




### Failure log (this batch)

- GLM: 14 intermittent single-metric `Inconclusive` (empty content from
reasoning-token exhaustion at high prompt lengths); drop-and-resume
refills recovered all 14 across three rounds (`373239d9…` landed on the
third). GLM final coverage: 230/230.
- gpt-4.1: 1 permanent degenerate-output record (`ae80afcb…`), same source
input that broke it in Section 1 (identical 11,994-char goal).
- Gemini: clean on this batch (230/230 first pass) — the classifier-budget
fix from Section 1 held.

---



## Section 3 — Fixed gpt-5.6-terra replay

Date: 2026-09-20 (third batch, genie pinned to `azure/gpt-5.6-terra`).

Same 136 traces, same constructed-history inputs, one fresh conversation and
one message per trace. Fetched from Langfuse into
`Genie_trajectories_replay_gpt-5.6-terra_20_sep_2026.json` —
**226 records / 136 traces** (backend verified: `gpt-5.6-terra-2026-07-09` on
226/226 records).

Result files:

- `results/full_evaluation_results_replay-gpt-5.6-terra-20-sep-2026.json`
- `results/full_evaluation_results_replay-gpt-5.6-terra-20-sep-2026_gemini-3.8-flash.json`
- `results/full_evaluation_results_replay-gpt-5.6-terra-20-sep-2026_glm-5.3.json`

Coverage: 226/226 on all three judges, with two permanent gaps:

- `09ead9d7…` — gpt-4.1 groundedness `Inconclusive`: the SAME source input
(11,994-char no-evidence transcript) that broke gpt-4.1 in both prior
batches (as `e692a734…` in Section 1, `ae80afcb…` in Section 2).
Deterministic degenerate output; unfixable by budget/temperature.
- `d36fa28b…` — GLM adaptivity + goal_alignment `Inconclusive` (empty
content; reasoning budget exhausted on this long-failure-evidence record;
persisted across 4 refill rounds). GLM groundedness/efficiency judged it fine.



### Final verdicts (all 226 records)


| Metric             | gpt-4.1                               | gemini-3.8-flash | glm-5.3         |
| ------------------ | ------------------------------------- | ---------------- | --------------- |
| **Groundedness**   | 194 Yes / 31 No / 1 Inc               | 213 Yes / 13 No  | 196 Yes / 30 No |
| **Efficiency**     | 222 Efficient / 4 Redundant           | 219 / 7          | 206 / 20        |
| **Adaptivity**     | 221 N/A / 1 Adaptive / 4 Not Adaptive | 221 / 2 / 3      | 221 / 0 / 4     |
| **Goal alignment** | 189 Aligned / 37 Misaligned           | 148 / 78         | 148 / 77        |




### Three-way agreement


| Metric         | Agreement           | Reading                                                                       |
| -------------- | ------------------- | ----------------------------------------------------------------------------- |
| Groundedness   | **84%** (190/225)   | gemini most lenient (13 No), gpt-4.1/glm stricter (31/30 No)                  |
| Efficiency     | **89%** (202/226)   | glm strictest on redundancy (20), gpt-4.1 most lenient (4)                    |
| Adaptivity     | **~100%** (224/225) | 5 failure steps; judges agree the agent mostly failed to adapt (1–2 Adaptive) |
| Goal alignment | **76%** (171/225)   | persistent judge split: gpt-4.1 16% Misaligned, gemini/glm ~34%               |




### Trace-level results

Records grouped back to their 136 source traces; a trace counts as negative
on a metric if **any** of its steps is negative. Per judge, plus the 2-of-3
majority:


| Metric (any negative step)  | gpt-4.1  | gemini   | glm      | Majority |
| --------------------------- | -------- | -------- | -------- | -------- |
| Groundedness (No)           | 23% (31) | 10% (13) | 22% (30) | 15% (21) |
| Efficiency (Redundant)      | 1% (2)   | 4% (5)   | 12% (17) | 1% (2)   |
| Adaptivity (Not Adaptive)   | 1% (1)   | 1% (1)   | 1% (1)   | 1% (1)   |
| Goal alignment (Misaligned) | 26% (35) | 54% (73) | 53% (72) | 49% (67) |




### Failure log (this batch)

- gpt-4.1: 1 permanent degenerate record (`09ead9d7…`, third occurrence of
the same poisonous input across batches).
- GLM: 13 intermittent `Inconclusive` on first pass (reasoning-token
exhaustion), recovered to 1 persistent record (`d36fa28b…`) over 4 refill
rounds.
- Gemini: clean first pass, 226/226 — classifier-budget fix holding.

---



## Section 4 — Cost and latency comparison

Costs recomputed from recorded token counts (`usageDetails`: input +
cache-read + output incl. reasoning) using the official price card in
`gpt_5_6_pricing_table.md` (July 2026). Langfuse's built-in cost reporting is
stale for these models (e.g. luna input priced $1.00/M vs official $0.20/M)
and is not used. Cache writes (1.25× input rate) never occurred; cache reads
are 1.5–2.1M tokens per batch.


| Backend | Input   | Cached input | Output (incl. reasoning) |
| ------- | ------- | ------------ | ------------------------ |
| sol     | $5.00/M | $0.50/M      | $30.00/M                 |
| terra   | $2.00/M | $0.20/M      | $12.00/M                 |
| luna    | $0.20/M | $0.02/M      | $1.20/M                  |


### Cost (per full 136-trace replay)


| Batch     | Records | Cost      | Notes                                                        |
| --------- | ------- | --------- | ------------------------------------------------------------ |
| §1 Router | 226     | **$4.34** | 55% of spend on sol (23% of calls)                           |
| §2 Luna   | 230     | **$0.48** | ~9× cheaper — an order of magnitude down on unit price       |
| §3 Terra  | 226     | **$4.44** | ≈ router; pulls ~50% more input tokens than the router batch |


### Latency (per turn: message send → full SSE reply)


| Batch     | Median | Mean  | p95   | Max   | Notes                                  |
| --------- | ------ | ----- | ----- | ----- | -------------------------------------- |
| §1 Router | 11.0s  | 13.0s | 35.8s | 46.9s | slowest tail — routing overhead + sol  |
| §2 Luna   | 8.7s   | 10.4s | 21.6s | 62.4s | max is one 11-step tool-loop outlier   |
| §3 Terra  | 8.3s   | 9.0s  | 18.2s | 37.5s | fastest and most consistent            |


### Combined quality / cost / latency


| Batch     | Quality (majority)                  | Cost             | Latency |
| --------- | ----------------------------------- | ---------------- | ------- |
| §1 Router | best (6.6% No, 1.8% Red, 23.9% Mis) | $4.34            | slowest |
| §2 Luna   | worst (10.0% / 7.4% / 31.3%)        | $0.48 (cheapest) | middle  |
| §3 Terra  | middle (9.3% / 2.2% / 31.9%)        | $4.44            | fastest |


Router = quality, luna = cost, terra = speed; no batch dominates all three.

---



## Section 5 — Trace-level comparison across the three backends

Rollup: judge majority (2-of-3) per step; a trace is negative on a metric if
**any** of its steps is. All batches cover the same 136 source traces.

### Traces with any negative step (judge majority)


| Metric                          | Router       | Luna         | Terra        |
| ------------------------------- | ------------ | ------------ | ------------ |
| Groundedness (any No)           | 11% (15/136) | 15% (20/136) | 15% (21/136) |
| Efficiency (any Redundant)      | 2% (3/136)   | 7% (9/136)   | 1% (2/136)   |
| Adaptivity (any Not Adaptive)   | 0% (0)       | 1% (1)       | 1% (1)       |
| Goal alignment (any Misaligned) | 38% (52/136) | 48% (65/136) | 49% (67/136) |


Ranking: groundedness router > luna ≈ terra; efficiency terra ≈ router ≫
luna; goal alignment router (38%) clearly better than luna/terra (48–49%).

### Per-trace transitions vs the router batch


| Metric         | Direction      | Newly bad | Fixed | Bad in both |
| -------------- | -------------- | --------- | ----- | ----------- |
| Groundedness   | router → luna  | 12        | 7     | 8           |
|                | router → terra | 12        | 6     | 9           |
| Efficiency     | router → luna  | 7         | 1     | 2           |
|                | router → terra | 1         | 2     | 1           |
| Goal alignment | router → luna  | 24        | 11    | 41          |
|                | router → terra | 28        | 13    | 39          |


Churn runs in both directions with net regression on groundedness and
alignment — the backends differ per-scenario, not uniformly. **34 traces are
misaligned in ALL THREE backends** — a stable hard-trace core no backend
choice fixes; hand-review these first.

### Takeaway

Router vs best fixed backend (terra): −4pp groundedness-bad (11% vs 15%),
−11pp misaligned (38% vs 49%); efficiency (2% vs 1%) and cost ($4.34 vs
$4.44) are washes. The router's edge concentrates on groundedness + goal
alignment.

---



## Section 6 — Router model churn between conversation turns

Turn order reconstructed from the original file (grouped by
`metadata.conversation_id`, ordered by timestamp); each turn mapped to the
backend the router picked in the §1 replay (final-answer step's `model`).

### Result: the router changes models on 47% of turn transitions

81 consecutive-turn transitions across 55 conversations: **38 changes
(47%)**, 43 same-model (53%).


| From → To     | Count |        |
| ------------- | ----- | ------ |
| terra → terra | 33    | stays  |
| terra → sol   | 10    | change |
| terra → luna  | 8     | change |
| sol → terra   | 7     | change |
| sol → luna    | 6     | change |
| luna → terra  | 6     | change |
| sol → sol     | 6     | stays  |
| luna → luna   | 4     | stays  |
| luna → sol    | 1     | change |


- The router is effectively **stateless per call**; terra→terra is the only
stable attractor (33 of 43 same-model transitions). 3 turns also switched
models **mid-turn** (terra→sol between steps).
- Caveat: replay sessions were fresh conversations with constructed text
history, so the router saw less session-continuity signal than production.
- Cache interplay: model switches bust the prefix cache — a candidate
explanation for the router batch's higher cache-hit rate (64% vs ~47–49%),
though causality may run either way.

