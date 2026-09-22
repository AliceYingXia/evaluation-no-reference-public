# Smart Routing Evaluation Methodology with Reference

## Overview
Evaluation framework for intelligent model routing based on task complexity, cost-efficiency, and performance requirements with reference available and DeepEval framework can be applied.
**This version assumes that the ground truth of tool call exists and it will be used as reference of trajectory evaluation! And the final output of each turn of conversation will be evaluated by LLM as judge. However, this approach faces challenges since groudtruth needs human labelling. Meanwhile, the conversations are mostly Q&A and it is challenging to evaluate the final output given user input without reference.**

---

### Evaluation Tooling Note

Not all metrics below need to be hand-built — [DeepEval](https://deepeval.com) (open-source LLM eval framework) covers some directly, while others require custom instrumentation from the model/gateway responses:

| Metric group | DeepEval coverage |
|---|---|
| Tool Call Recall / Precision | Covered by DeepEval's **Tool Correctness** metric (compares called vs. expected tools) and **Argument Correctness** (validates call arguments) |
| Output Quality | Planned as human review; DeepEval's **Arena G-Eval** may help as an LLM-as-evaluator |

---

## TIER 1: SMALL / BUDGET (Simple Queries)

| Model | Input/Output Cost | Cached Input Cost | Context Window | Provider | Status | Type | KV Cache |
|-------|-------------------|-------------------|-----------------|----------|--------|------|----------|
| Qwen 3.5-9B | $0.10 / $0.15 | — | 262K tokens | AI Gateway | ✓ Live | Open-weight | ✓ Available |
| GPT-5.6 Luna | $0.20 / $1.20 | $0.05 | 1.05M tokens | OpenAI | ✓ Live | Closed API | ✓ Available |

### Use Cases
- Application access requests (standard provisioning flows)
- Login issues (SSO/Okta/MFA problems)
- Password resets
- Account lockout troubleshooting
- Simple access permission verification
- Device connectivity basics
- VPN connection issues
- Basic account creation or reactivation
- Standard application onboarding
- Access revocation or de-provisioning requests

---

## TIER 2: MEDIUM (Multi-Step Reasoning / Coding)

| Model | Input/Output Cost | Cached Input Cost | Context Window | Provider | Status | Type | KV Cache |
|-------|-------------------|-------------------|-----------------|----------|--------|------|----------|
| GLM-5.3 | $1.12 / $3.52 | $0.225 | 1M tokens | AI Gateway | ✓ Live | Open-weight | ✓ Available |
| GPT-5.6 Terra | $2.00 / $12.00 | $0.50 | 1.05M tokens | OpenAI | ✓ Live | Closed API | ✓ Available |

### Use Cases
- Multi-step troubleshooting (2-3 steps) using KB runbooks
- Application access troubleshooting with specific error messages
- SSO/MFA troubleshooting across multiple systems
- Device setup and configuration issues
- Firefighter request ticket composition and submission
- Complex access scenarios requiring escalation
- Browser/VPN configuration troubleshooting
- Authentication error diagnosis and resolution
- Application permission level verification and adjustment
- KB synthesis for similar but slightly different issues
- Troubleshooting with partial information requiring clarification
- IT policy explanation and application

---

## TIER 3: COMPLEX / FRONTIER (Advanced Reasoning)

| Model | Input/Output Cost | Cached Input Cost | Context Window | Provider | Status | Type | KV Cache |
|-------|-------------------|-------------------|-----------------|----------|--------|------|----------|
| Kimi K3 | $2.55 / $12.75 | $0.26 | 1M tokens | AI Gateway | ✓ Live | Open-weight | ✓ Available |
| Claude Opus 5 | $5.00 / $25.00 | $1.25 | 1M tokens | Anthropic | ✓ Live | Closed API | ✓ Available |

### Use Cases
- Complex escalations requiring detailed Jira Service Desk ticket creation
- Multi-step troubleshooting (4+ steps) with advanced KB synthesis
- Out-of-scope detection and proper escalation handling
- Security incident identification and escalation
- Novel or undocumented IT issues requiring investigation
- Cross-system access or permission issues
- Conflicting requirements or policy interpretation
- High-stakes access decisions requiring audit trails
- Compliance and governance validation
- Integration of sensitive information handling in tickets
- Recovery from ticket creation failures with schema adaptation
- Complex Jira asset field resolution and global ID mapping
- Exceptional access request scenarios
- Post-troubleshooting decision logic (escalate vs. resolve)

---

## Tool Call Evaluation Metrics

For each conversation/turn, define:
- **Expected tools** = the set of tools that *should* be called to correctly resolve the request (ground truth).
- **Called tools** = the set of tools the model actually called.
- **Correct tools called** = tools that appear in both the expected set and the called set (i.e. the model called the right tool at the right point).

| Metric | Formula | What it captures |
|--------|---------|-------------------|
| Tool Call Recall | Correct tools called / All tools that should be called | Whether the model calls every tool it needed to (misses = under-triggering) |
| Tool Call Precision | Correct tools called / All tools that were called | Whether the tools it did call were actually necessary (extra/wrong calls = over-triggering) |
| Tool Error Rate | Tool calls that errored / All tool calls made | Whether calls that were made executed successfully (bad args, wrong schema, failed execution, etc.) |

Notes:
- Recall and precision are computed per-turn or per-conversation over the tool *names* (or name+key-argument signature, if two calls to the same tool with different args should be distinguished), then averaged across the eval set.
- Tool Error Rate is independent of recall/precision — a "correct" tool call (right tool, right time) can still error out (e.g. malformed arguments, timeout, permission failure) and should count toward this metric.
- Track these three metrics per experiment (Exp 1a–7) and per tier, so routing decisions can be evaluated on tool-use quality in addition to cost/latency.

---

## Efficiency Metrics

| Metric | Definition | What it captures |
|--------|------------|-------------------|
| Latency (per turn) | Wall-clock time from request sent to response received, for a single turn | Responsiveness of the model/router at each step |
| Latency (per conversation) | Sum (or end-to-end wall-clock) of all turn latencies across a full conversation | Total time to resolve the request, including routing overhead across turns |
| Token Usage — Input | Count of input tokens consumed per turn and summed per conversation | Cost driver; also reflects context/prompt size |
| Token Usage — Output | Count of output tokens generated per turn and summed per conversation | Cost driver; also reflects response verbosity |
| Token Usage — Cached | Count of input tokens served from cache per turn and summed per conversation | Cost savings realized from prompt caching |
| KV Cache Hit Rate | Cached input tokens / total input tokens (per turn and per conversation) | How effectively the model/router is reusing cached context instead of reprocessing it |
| Steps to Completion | Number of turns/steps (user turns, model turns, and/or tool calls) taken until the task is resolved | Efficiency of the interaction — fewer steps for the same outcome means less overhead/cost |

Notes:
- Report latency and token usage both per-turn (to catch outliers/slow steps) and aggregated per-conversation (to reflect end-user experience and total cost).
- KV Cache Hit Rate should be tracked alongside cached token cost (see pricing tables above) since it directly affects the effective cost per experiment.
- Track these metrics per experiment (Exp 1a–7) and per tier alongside the tool-call metrics, so routing decisions can be evaluated on cost/speed together with correctness.

---

## Router Accuracy

| Metric | Formula | What it captures |
|--------|---------|-------------------|
| Router Accuracy | Queries where router-selected tier = ground-truth label / All queries | How often each router (Exp 4–7) picks the tier that actually matches the query's true complexity |

**Deriving the ground-truth label (Output Quality Pairwise Comparison):**
For each query, run the same request through the Tier 1, Tier 2, and Tier 3 models (fixed baselines Exp 1–3) and pairwise-compare their final outputs to determine relative quality — better / equivalent / worse — using a consistent rubric (e.g., correctness, completeness, actionability), ideally via blind judging (LLM-judge or human rater) to avoid position/model-identity bias.

Labeling logic (cascading, cheapest-first):
1. If Tier 1's output is not worse than Tier 2's and Tier 3's → ground-truth label = **Simple**.
2. Else if Tier 2's output is not worse than Tier 3's → ground-truth label = **Medium**.
3. Else → ground-truth label = **Complex**.

Notes:
- The ground-truth label is derived once per query from the pairwise comparisons above, then reused as the fixed reference to score every router (Exp 4–7).
- Router Accuracy complements the tool-call and efficiency metrics above — a router can be accurate on tier selection while still scoring poorly on tool-call recall/precision or efficiency, and vice versa.

---

## Benchmark-Style Aggregate Metrics (AvgAcc / Gain@R / Gain@B / Gap@O)

| Metric | Formula | What it captures |
|--------|---------|-------------------|
| AvgAcc | Average accuracy (or output-quality win rate) across all evaluated queries for a given router | Overall routing quality on a single comparable scale |
| Gain@R | (AvgAcc(router) − AvgAcc(Random)) / AvgAcc(Random) | Relative improvement of a router over the Random baseline |
| Gain@B | (AvgAcc(router) − AvgAcc(Best Single)) / AvgAcc(Best Single) | Relative improvement of a router over always using the single best fixed model |
| Gap@O | (AvgAcc(Oracle) − AvgAcc(router)) / AvgAcc(Oracle) | Remaining gap to the theoretical upper bound (lower is better) |

Comment: we can calculate these directly with the baselines already defined in this plan — no new experiments needed. **Random** = Exp 4; **Best Single** = whichever of Exp 1a–3b (fixed Tier 1/2/3 models) scores highest on AvgAcc; **Oracle** = the per-query best tier, i.e. the tier matching the ground-truth complexity label from the Output Quality Pairwise Comparison above. AvgAcc for each dynamic router (Exp 5–7) can then be compared against these three to compute Gain@R, Gain@B, and Gap@O.

---

## Experiments

### Baseline Experiments (Single Model Only)

| Experiment | Description | Model Used | Tier | Routing Logic |
|------------|-------------|-----------|------|----------------|
| Exp 1a | Budget - Open-weight | Qwen 3.5-9B | Tier 1 | Fixed - all turns use Tier 1 (open-weight) |
| Exp 1b | Budget - Closed API | GPT-5.6 Luna | Tier 1 | Fixed - all turns use Tier 1 (closed API) |
| Exp 2a | Medium - Open-weight | GLM-5.3 | Tier 2 | Fixed - all turns use Tier 2 (open-weight) |
| Exp 2b | Medium - Closed API | GPT-5.6 Terra | Tier 2 | Fixed - all turns use Tier 2 (closed API) |
| Exp 3a | Complex - Open-weight | Kimi K3 | Tier 3 | Fixed - all turns use Tier 3 (open-weight) |
| Exp 3b | Complex - Closed API | Claude Opus 5 | Tier 3 | Fixed - all turns use Tier 3 (closed API) |

### Dynamic Routing Experiments

| Experiment | Description | Router Model | Routing Logic |
|------------|-------------|-----------|----------------|
| Exp 4 | Random router | N/A | Random selection at each turn |
| Exp 5 | Qwen 3.5-9B router | Qwen 3.5-9B (9B parameters) | Uses Tier 1 model as router decision-maker at each turn |
| Exp 6 | NotDiamond router | NotDiamond-0001 (fine-tuned BERT text classifier, ~110M parameters) | Text classification model trained on hundreds of thousands of cross-domain evaluation benchmarks; routes between strong/weak models |
| Exp 7 | RORF router | Random Forest Classifier (Jina embeddings + Random Forest trees) | Uses RoRF pairwise random forest-based router at each turn; trained on prompt embeddings with voyage-gpt4o-gpt4omini model pair |





### Notes
**Provider Context:**
- **AI Gateway** is your internal deployment platform hosting open-weight models. The pricing shown for open-weight models reflects OpenRouter reference rates for benchmarking and comparison purposes.
- Token prices for open-weight models (Qwen 3.5-9B, GLM-5.3, Kimi K3) are sourced from OpenRouter and may differ from your actual internal AI Gateway costs.
- Actual costs on your internal AI Gateway may differ based on your infrastructure, licensing, compute optimization, and operational overhead.
- Cached input costs represent typical 70-90% discounts; actual cache performance depends on workload patterns and implementation.

_Add evaluation findings, routing logic decisions, and performance comparisons here._

---

## Routing Prompt (Copy-Ready)

```
You are a helpful assistant that classifies the complexity of a user's IT request and selects the single most suitable route.
You are provided with a list of available routes enclosed within <routes></routes> XML tags:
<routes>
{"name":"simple","description":"TIER 1 - Simple IT requests: standard access provisioning, password resets, account lockouts, login/SSO/MFA basic issues, simple permission verification, device connectivity basics, VPN connection issues, standard onboarding/de-provisioning. Single-step resolution or straightforward KB lookup."}
{"name":"medium","description":"TIER 2 - Multi-step troubleshooting: 2-3 step KB runbook synthesis, application access troubleshooting with specific errors, authentication error diagnosis, device configuration issues, Firefighter ticket composition, complex access scenarios, browser/VPN configuration, permission level verification with clarification."}
{"name":"complex","description":"TIER 3 - Complex escalations: 4+ step troubleshooting with advanced KB synthesis, Jira Service Desk ticket creation with schema handling, out-of-scope detection and escalation, security incident identification, novel/undocumented issues, cross-system access problems, compliance validation, sensitive information handling, ticket creation error recovery, global ID mapping for Jira assets."}
</routes>

You are also given the conversation context enclosed within <conversation></conversation> XML tags:
<conversation>
[
    {
        "role": "user",
        "content": "User IT support request here"
    }
]
</conversation>

## Instructions
1. Analyze the latest user intent from the conversation.
2. Every request has exactly one complexity level — compare the request against the available routes and choose the single best-matching route. Do not select more than one, and do not return an empty list: every request maps to a route, even if the match is imperfect.
3. If you are genuinely unsure between two adjacent tiers, choose the cheaper (lower) one. Do not escalate to a more demanding tier by default just because you are uncertain - only choose a higher tier when the request clearly needs it.
4. Respond only with the exact route name from <routes>.

## Response Format
Return your answer strictly in JSON as follows:
{"route": ["route_name"]}
```
