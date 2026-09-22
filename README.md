# evaluation_no_reference

Reference-free evaluation of a support genie (Workato Agent Studio) against
recorded production trajectories — plus controlled replays of those
trajectories against different backend models, judged by three LLM evaluators.

## What's here

- **`findings_eval_details.md`** — main results: three replay batches
  (intelligent router / fixed gpt-5.6-luna / fixed gpt-5.6-terra), each judged
  by gpt-4.1 + gemini-3.8-flash + glm-5.3 on groundedness, efficiency,
  adaptivity, goal alignment; trace-level rollups; cost/latency comparison;
  router model-churn analysis. Start here.
- **`evaluation_methodology_without_reference_final_solution.md`** /
  **`evaluation_methodology_with_reference.md`** — the evaluation design.
- **Trajectory data files are NOT included in this public repo** (they contain
  internal conversation data). The pipeline expects a Langfuse observations
  export shaped like a list of `agent_chat_completion` records; see
  `scripts/README.md` for the expected format.
- **`gpt_5_6_pricing_table.md`** — official price card used for cost math
  (Langfuse's built-in pricing is stale for these models).
- **`WORKATO_API_SETUP.md`** — how to authenticate against the Agentic API
  and the genie headless chat API.
- **`scripts/`** — the pipeline (see `scripts/README.md` for details):
  - `extract.py` / `evaluate.py` / `run_full_evaluation.py` — reference-free
    four-metric judge pipeline. `--model` selects the judge, `--src` the
    dataset, `--limit` bounds a run; results checkpoint per judge per dataset
    under `results/`. Logging/bookkeeping steps
    (`log_conversation_metadata`/`conversation_summary`) are skipped
    structurally, without LLM calls.
  - `replay_trajectories.py` — replays traces into the genie via the headless
    API. `--construct-history` embeds recorded history (incl. tool calls and
    results) in one message per trace, fitting the 12,288-char API limit.
  - `fetch_replay_trajectories.py` — pulls replayed traces from Langfuse in
    the source file's shape.
  - `workato_client.py` / `connect_workato_genie.py` — API clients and
    one-time genie client provisioning.

## Data notes

- This public copy is scrubbed: trajectory data, `results/`, real hostnames,
  internal IDs, and personal names/emails were removed or replaced with
  placeholders. The full data lives in the private original repo.
- Credentials are read from `.env` (gitignored): AIGW key for judges, Workato
  Agentic API token, genie headless API key + IDP test user, Langfuse keys.

## Quickstart

```bash
cd scripts
python3 evaluate.py                     # 3-record smoke test (default judge)
python3 evaluate.py fireworks/glm-5.3   # smoke test with another judge
python3 run_full_evaluation.py --limit 10
python3 run_full_evaluation.py --model vertex_global/gemini-3.8-flash \
    --src ../Genie_trajectories_replay_gpt-5.6-luna_20_sep_2026.json
```
