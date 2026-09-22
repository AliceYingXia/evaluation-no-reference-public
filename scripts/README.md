# Evaluation scripts

Reference-free, TRACE-adapted evaluation of BT Genie conversation turns. See
`../EVALUATION_APPROACH.md` for the methodology and `../FINDINGS_01_INITIAL_SAMPLE.md` for
results and the history of pipeline fixes.

## Connecting to the Workato preview genie

- **`workato_client.py`** — reusable clients for the Agent Studio management
  API (`list_genies()`, `get_genie()`, `list_genie_clients()`, …) and the
  Genie headless chat API (`create_conversation()`, `send_message()`). Reads
  credentials from `../.env`; the headless helpers automatically send
  `WORKATO_GENIE_API_KEY` + `WORKATO_IDP_USER_ID`.
- **`connect_workato_genie.py`** — one-time provisioning: creates an API-key
  genie client, saves its one-time key to `../.env`, and attaches it to the
  target genie. Already run on 2026-09-18; only re-run if you need a new
  client (`--genie-id`, `--client-name` to override).

Full setup guide, gotchas (two API hosts, end-user vs collaborator identity
pools), and a runnable "say hello" example: `../WORKATO_API_SETUP.md`.

## Replaying trajectories into the genie

- **`replay_trajectories.py`** — replays traces from
  `../Genie_trajectories15_sep_2026.json` into the genie configured in
  `../.env`. Per trace: fresh conversation, then every recorded user turn
  sent in order (history first, final input last) so the genie rebuilds
  context itself. 4 concurrent conversations; resumable via the JSONL
  output (one line per trace; re-running skips completed traceIds).
  `--first-turn-only` restricts to the 52 traces with exactly one user turn
  (empty history — exactly comparable replay, output
  `../results/replay_first_turns_52_20260919.jsonl`; completed 2026-09-19,
  52/52 clean). `--construct-history` (v2): replays ALL 136 traces, one fresh
  conversation and one message per trace, with the recorded history — user
  turns, assistant replies, AND tool calls/results — embedded in the prompt
  via render_trace_input()'s template, so every trace is answered against the
  ORIGINAL conversational past. The genie's headless API caps messages at
  12,288 chars (400 otherwise); construct_input() fits by shrinking
  tool-result caps (4000→1500→600→200→omit body), then dropping oldest
  history entries — never touching the current turn. Replay files carry the
  `intelligent_router` label because the genie routes each call per-request
  (226 records: gpt-5.6-terra 144 / -sol 53 / -luna 29). Inputs manifest:
  `../results/replay_constructed_history_inputs.json`; results:
  `replay_constructed_history_intelligent_router_136_20260920.jsonl`
  (completed 2026-09-20, 136/136 clean). Default mode: seeded random sample
  (default 100, seed 42, output `replay_100_seed42_20260919.jsonl`).
  `--limit N` for a smoke test.
- **`fetch_replay_trajectories.py`** — pulls a replay's new traces from
  Langfuse (time-window list + sessionId match; the API's sessionId filter is
  broken on this instance) and writes them in the exact shape of
  `../Genie_trajectories15_sep_2026.json` (agent_chat_completion GENERATION
  records only, same key set; evaluation-annotation columns null). Args:
  `[replay_jsonl] [out_json]`. Ran 2026-09-20 →
  `../Genie_trajectories_replay_intelligent_router_20_sep_2026.json`
  (226 records / 136 traces).

## Current pipeline (run these)

- **`extract.py`** — parses a raw trajectory record: strips the tool-catalog
  tail, builds the evidence bank (with per-entry timestamps and
  logging-action tags), extracts the goal (all user messages) and the step
  being judged.
- **`evaluate.py`** — the four judge prompts (groundedness, efficiency,
  adaptivity, goal alignment) and `evaluate_record()`, which runs all four
  against one prepared record. Steps consisting solely of mandatory
  bookkeeping calls (`log_conversation_metadata`/`conversation_summary`, 101
  of 533 records) are NOT evaluated: every metric is marked `Skipped` in
  code, with no LLM calls — prompt-level exceptions were tried and made
  judges lenient on genuine findings. Includes `classify_is_failure()`, an LLM call
  that gates the adaptivity check — this is the current, most-accurate
  failure-detection method (see `FINDINGS_01_INITIAL_SAMPLE.md`, "Round 3"). Run directly
  (`python3 evaluate.py`) for a 3-record smoke test before a full run.
- **`run_full_evaluation.py`** — two modes, sharing the same loading/
  threading/checkpointing machinery:
  - default: runs `evaluate_record()` (all four metrics) over every record
    in the dataset with concurrency, checkpointing every 20 records to
    `../results/full_evaluation_results.json` so a mid-run failure doesn't
    lose progress. Safe to re-run: it skips ids already present in the
    results file.
  - `--adaptivity-only`: re-evaluates ONLY the adaptivity verdict for every
    record that already has one (~20-25 of 533), using whatever the current
    `ADAPTIVITY_USER_TMPL` is. Use this instead of a full rerun whenever you
    change just the adaptivity prompt — much cheaper, and the other three
    metrics don't depend on it anyway. Already used twice for two rounds of
    adaptivity prompt fixes (see `FINDINGS_02_FULL_RUN.md`).

To run the full dataset from scratch:
```
cd scripts
python3 run_full_evaluation.py
```

Judge model: default `azure_internal_01/gpt-4.1` (temperature 0). Alternative
judges via `--model`, each writing its own results file for cross-judge
agreement analysis — verified working on 2026-09-20:
```
python3 run_full_evaluation.py --model vertex_global/gemini-3.8-flash
python3 run_full_evaluation.py --model fireworks/glm-5.3
```
(`bedrock_internal_01/claude-sonnet-4-6` is plumbed but the Bedrock account
needs the Anthropic use-case form submitted first — it 404s until then.)
`--limit N` bounds a run for smoke tests.

To pick up an adaptivity-prompt-only change without a full rerun:
```
cd scripts
python3 run_full_evaluation.py --adaptivity-only
```

## `archive/` — historical one-off correction scripts

These were used once, on this specific dataset, to retrofit
`full_evaluation_results.json` after `extract.py`'s failure-detection logic
was fixed (twice). They are **not** part of the pipeline going forward —
`evaluate.py`'s `evaluate_record()` now calls the corrected logic
(`classify_is_failure()`) natively, so a fresh `run_full_evaluation.py` run
no longer needs a follow-up correction pass. Kept only for provenance /
reproducibility of how the current results file was produced:

- `fix_adaptivity.py` — round 2 correction (heuristic keyword-scan →
  structured-field checks).
- `fix_adaptivity_llm.py` — round 3 correction (structured-field heuristic →
  LLM classifier). This is the script whose logic is now inlined in
  `evaluate.py`.
- `triage_flags.py` / `dump_unclassified.py` / `dump_all_flagged_v3.py` —
  one-off manual-review tooling used to read every flagged record's context
  in bulk while verifying results by hand (see `FINDINGS_02_FULL_RUN.md`,
  "Full manual coverage"). Not reusable pipeline code; `flagged_ids_v3.json`
  and `flagged_dump_v3.txt` are their generated/consumed data files from that
  specific review pass.

## A note on `extract.py`'s `last_observation_is_failure()`

This function still exists but is **not called by the current pipeline** —
`evaluate_record()` uses `classify_is_failure()` instead. It's kept only
because the archived scripts above reference it for their historical
reconciliation logic. Do not wire it back into new code; see its docstring
and `FINDINGS_01_INITIAL_SAMPLE.md` for why it was superseded.
