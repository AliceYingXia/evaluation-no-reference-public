# Evaluating BT Genie Trajectories Without Reference

This documents the approach used to score agent trajectories in
`Genie_trajectories15_sep_2026.json` — a Langfuse export of real BT Genie
(Workato IT support agent) conversations — with no ground-truth answer key
and no annotated reference trajectory available.

## Data shape

- 533 `GENERATION` records, grouped by `traceId` into 136 conversations.
- Each record's `input` already contains the **full accumulated message
  history** up to that point (system + all prior user/assistant/tool
  messages), confirmed verbatim (not summarized) across turns.
- Each record's `input` also has a static, repeated **tool-definition tail**
  (~17 `role: "tool"` messages whose `content.type == "function"`) — this is
  the tool catalog, not real history, and must be stripped before use.
- Each record's `output` is exactly one new step: either `tool_calls`
  (`name` + `args`) or a final `content` reply.
- The agent's underlying model (`azure/gpt-5.2`) hides its chain-of-thought
  — `content` is always `""` on tool-calling steps, so there is no explicit
  `thought` text to evaluate, unlike the ReAct-style trajectories TRACE was
  built for.

## Evaluation unit and rule

**Each record (turn) is evaluated completely independently.** Records
sharing a `traceId` are never grouped, merged, or aggregated for scoring or
reporting — even though later turns structurally contain earlier ones. This
was an explicit user requirement, not an artifact of the data.

## Explicit definition of "step"

**A step is a record's `output` field, and only that field.** Nothing else
in the record is treated as a step:

- `role: "user"` messages are never scored as a step — the most recent one
  is used only as the `goal` context a step is judged against.
- `role: "tool"` messages (real observations) are never scored as a step —
  they are only used to build the evidence bank `E` a step is judged
  against.
- `role: "tool"` messages that are actually tool-definition schemas (the
  static catalog tail) are not steps and are not evidence either — they are
  stripped and discarded entirely.
- The **assistant's `output`** — either a `tool_calls` bundle (one or more
  simultaneous tool calls) or a final `content` reply — is the one and only
  thing being judged per record. If an output contains multiple parallel
  `tool_calls`, the whole bundle is treated as **one single step** (e.g.,
  efficiency judges whether any call in the bundle is redundant with
  another in the same bundle, not each call separately).

So: **1 record = 1 step = 1 assistant output**, judged against the evidence
bank and goal derived from everything else in that same record's `input`.

## Mapping to a TRACE-style step

| TRACE concept | Source in this data |
|---|---|
| Evidence bank `E` | Built by walking the record's `input` (tool-def tail stripped), pairing each `assistant.tool_calls` entry with its following `tool` result message via `tool_call_id` |
| Step being judged | The record's own `output` |
| User's goal (proxy for missing "plan") | The most recent `role: user` message in `input` |
| Preceding failure (for adaptivity) | Detected by keyword scan of the last evidence entry's observation (`error`, `unavailable`, `422`, etc.) |

## Why TRACE's prompts needed adapting

TRACE's published prompts (see `Beyond the Final Answer.pdf`, Figures 15–17)
judge a `thought` string against the evidence bank. This agent never exposes
that string, so the hallucination and adaptivity prompts were rewritten to
judge the **action itself** (tool call name/args, or final-reply claims)
against the evidence bank, instead of a thought. This also borrows the
"judge the action/plan alignment directly" idea from the Agent GPA paper,
which doesn't require an exposed thought/plan either.

## Metrics implemented (all reference-free)

1. **Groundedness** (replaces TRACE's hallucination metric) — is the new
   action or final-reply claim logically supported by the evidence bank +
   current user goal, without fabricating facts (ticket status, names,
   dates)?
2. **Efficiency** — is the new action redundant given evidence already
   collected (including redundancy among multiple simultaneous tool calls
   in the same step)?
3. **Adaptivity** — only scored when the last evidence entry looks like a
   tool failure; does the next step recover sensibly?
4. **Goal alignment** (borrowed from Agent GPA) — is the action a
   reasonable step toward the user's current stated goal?

Correctness of final answers is **not** checked against a ground-truth
label (none exists). A stronger future addition, borrowed from
Agent-as-a-Judge, would be **tool-augmented verification**: independently
re-calling the same read-only tools (e.g., `get_jira_service_desk_issue_details`)
to check the agent's factual claims against live system state, rather than
trusting the transcript alone.

## Pipeline / scripts

- `extract.py` — parses a record: strips the tool-definition tail, builds
  the evidence bank, extracts the goal and the step to judge.
- `evaluate.py` — formats the four judge prompts, calls the judge model,
  and parses each `Verdict:` line.
- Judge model: `fireworks/kimi-k3`, called via the internal gateway
  `https://ai-gateway.example.internal/v1`, using the key in `.env`
  (`AIGW_API_KEY`).
- Currently validated on a 10-record test batch; not yet run on the full
  533 records pending review of test output quality.

## Known limitations

- No ground-truth final-answer check (by design — none exists for real
  support tickets).
- Efficiency/groundedness verdicts are single-pass LLM judgments, not
  independently verified against live systems yet (see tool-augmented
  verification note above).
- Long tool outputs are truncated to 500 characters per evidence entry
  before being passed to the judge, to control prompt size; this could
  drop relevant detail for unusually verbose tool responses.

## Reference papers

- **Kim, W., Park, S., In, Y., Kim, S., Lee, D., Park, C.** *Beyond the
  Final Answer: Evaluating the Reasoning Trajectories of Tool-Augmented
  Agents.* ICML 2026. [arXiv:2510.02837](https://arxiv.org/pdf/2510.02837)
  — source of the TRACE framework (evidence bank; efficiency, hallucination,
  adaptivity metrics) this approach is adapted from. Local copy:
  `Beyond the Final Answer.pdf`.
- **Kim, T., Singh, J., Mehri, S., Acikgoz, E. C., Mukherjee, S., Beyza
  Bozdag, N., Shashidhar, S., Tur, G., Hakkani-Tür, D.** *PIPA: A Unified
  Evaluation Protocol for Diagnosing Interactive Planning Agents.*
  arXiv:2505 — cited within TRACE as a "state consistency" baseline;
  relevant because it doesn't require an explicit thought/plan text either.
- **Zhang, Y., Chen, J., Wang, J., Liu, Y., Yang, C., Shi, C., Zhu, X.,
  Lin, Z., Wan, H., Yang, Y.** *ToolBEHonest: A Multi-Level Hallucination
  Diagnostic Benchmark for Tool-Augmented Large Language Models.* EMNLP
  2024. — narrower hallucination-only benchmark, referenced for comparison
  in TRACE's related work.
- **Jia, A. S., Huang, D., Vytla, N., et al.** *What Is Your Agent's GPA?
  A Framework for Evaluating Agent Goal-Plan-Action Alignment.*
  [arXiv:2510.08847](https://arxiv.org/abs/2510.08847) — source of the
  Goal Fulfillment / Plan Adherence framing used for the "goal alignment"
  metric here, chosen because it doesn't require an exposed thought or
  plan string.
- **You, R., Cai, H., Zhang, C., et al.** *A Survey on Agent-as-a-Judge.*
  [arXiv:2601.05111](https://arxiv.org/abs/2601.05111) — source of the
  tool-augmented verification idea (judge independently re-verifies claims
  against live system state instead of trusting the transcript), proposed
  here as a future enhancement to break the "judge and judged share the
  same blind spots" circularity risk of pure LLM-as-judge scoring.
- **Fourney, A., et al.** *Magentic-One: A Generalist Multi-Agent System
  for Solving Complex Tasks.* arXiv:2411.04468 — cited in TRACE as the
  multi-agent system TRACE was extended to (Appendix D.1), relevant if
  BT Genie's skill/orchestrator structure is later treated as multi-agent.

## Open items / decisions still pending

- Confirm judge output quality on the (rerun) 10-record test batch before
  scaling to all 533 records.
- Decide whether to add tool-augmented verification for final-reply
  correctness (requires read access to the same Jira/employee-directory
  tools the agent itself calls).
- Decide whether to persist per-record results back into this repo (with
  employee PII in mind) or keep them in the session scratchpad only.
