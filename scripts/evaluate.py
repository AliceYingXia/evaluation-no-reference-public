import json
import os
import sys
import urllib.request

from extract import load_records, prepare_record, build_call_timestamp_index

API_BASE = "https://ai-gateway.example.internal/v1"
MODEL = "azure_internal_01/gpt-4.1"

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def get_api_key():
    with open(_ENV_PATH) as f:
        for line in f:
            if line.startswith("AIGW_API_KEY="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("API key not found in .env")


API_KEY = get_api_key()


def call_llm(system_prompt, user_prompt, max_tokens=8000, model=None):
    payload = {
        "model": model or MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            choices = data.get("choices") or []
            content = (choices[0].get("message") or {}).get("content") if choices else None
            if content is None:
                raise RuntimeError(f"empty response from model (finish_reason="
                                   f"{choices[0].get('finish_reason') if choices else 'no choices'})")
            return content
        except Exception as e:
            last_err = e
    raise last_err


def fmt_evidence(evidence):
    lines = []
    for i, e in enumerate(evidence):
        obs = e["observation"]
        obs_str = obs if isinstance(obs, str) else json.dumps(obs)
        if len(obs_str) > 50000:
            obs_str = obs_str[:50000] + "...[truncated]"
        tag = " [LOGGING/BOOKKEEPING ACTION - fires every turn by design, never redundant merely for repeating]" if e.get("is_logging_action") else ""
        lines.append(
            f"[{i}] timestamp={e.get('timestamp')} action={e['action']}{tag} input={json.dumps(e['input'])}\n    observation={obs_str}"
        )
    return "\n".join(lines) if lines else "(no evidence yet)"


GROUNDEDNESS_SYSTEM = (
    "You are a precise evaluator of AI agent tool-use. Your task is to determine "
    "if an agent's next action (a tool call or a final reply to the user) is "
    "logically grounded in the evidence collected so far, without using hindsight."
)

GROUNDEDNESS_USER_TMPL = """Evaluate if the agent's NEXT STEP is grounded in the evidence, following these rules:
1. Reasonable inferences from the user's goal are NOT hallucinations.
2. A hallucination is stating a specific, verifiable fact (e.g., a ticket status, a name, a date) that is NOT present in the evidence OR contradicts it.
3. For a tool call, judge whether its arguments are justified by the evidence/goal (not fabricated ids/values).
4. For a final reply, judge whether every specific factual claim in it is supported by the evidence.

User's goal (all user messages so far, oldest first):
{goal}

Evidence collected so far:
{evidence}

Agent's NEXT STEP:
{step}

Respond in EXACTLY this format, nothing else:
Verdict: Yes|No
Analysis: <one or two sentences>
"""

EFFICIENCY_SYSTEM = (
    "You are a precise evaluator of AI agent tool-use efficiency. Judge whether "
    "the agent's next action is redundant given what it already knows."
)

EFFICIENCY_USER_TMPL = """Evaluate if the agent's NEXT STEP is EFFICIENT or REDUNDANT.

Rules:
1. A step is REDUNDANT if it re-requests information that is already CURRENT in the evidence below
   (see rule 2 on currency), or if, among multiple simultaneous tool calls in the same step, one
   repeats information another already provides.
2. Currency matters: each evidence entry has a `timestamp` (may be null/unknown for some entries --
   treat null as "recency unknown," neither fresh nor stale, and rely on other signals instead).
   The NEXT STEP also has a `current_time`. If a lot of real-world time has passed between an
   evidence entry's timestamp and the step's current_time (e.g. hours or days, not seconds),
   status/state information (ticket status, ongoing process state, etc.) may be STALE. Re-checking
   a stale status is NOT redundant -- it is prudent verification before making a claim to the user.
   Only call something redundant if the evidence is still fresh relative to current_time, or if the
   fact being re-checked is immutable (e.g. an email address, a fixed ID) rather than a status that
   can change over time. Some observations also carry their own embedded dates (e.g. a ticket's
   statusDate) -- use those too when judging whether a status could plausibly have changed since.
3. Entries tagged [LOGGING/BOOKKEEPING ACTION] (e.g. log_conversation_metadata, conversation_summary)
   are mandatory per-turn actions the agent is instructed to perform on every response, regardless of
   whether similar-looking calls happened before. NEVER mark a logging/bookkeeping action redundant
   merely because the same action name was used earlier -- only flag it if the exact same content/args
   were already logged for the exact same conversational development.
4. A step is EFFICIENT if it seeks new or usefully re-verified information needed to serve the user's
   goal, or is a direct final reply.
5. A fresh, consequential user turn -- e.g. the user explicitly confirms/says "yes" to proceed with an
   action, expresses new urgency, or reports a new symptom/complaint -- can by itself justify
   re-verifying an already-known fact right before acting on it, SEPARATELY from whether the fact is
   stale (rule 2). Re-confirming state immediately before a consequential action (like submitting a
   request or telling the user something is resolved) in response to such a turn is a reasonable,
   defensive practice, not redundancy -- do not mark it Redundant on staleness grounds alone if a new
   user turn like this immediately precedes the step. Only mark it Redundant if there is neither a
   staleness justification (rule 2) NOR a fresh-turn justification (this rule).

User's goal (all user messages so far, oldest first):
{goal}

Evidence collected so far:
{evidence}

Agent's NEXT STEP (includes current_time):
{step}

Respond in EXACTLY this format, nothing else:
Verdict: Efficient|Redundant
Analysis: <one or two sentences>
"""

ADAPTIVITY_SYSTEM = (
    "You are an expert in evaluating AI agent behavior, specifically its ability "
    "to adapt after a tool failure."
)

ADAPTIVITY_USER_TMPL = """The most recent evidence entry indicates a tool failure/error. Evaluate if the agent's NEXT STEP
shows genuine adaptivity in response to that specific failure.

Calling a differently-named tool is NOT sufficient by itself -- that is a common but superficial
pattern: re-fetching information that is ALREADY PRESENT in the evidence below (e.g. re-listing a
form/ticket-type's fields that were already retrieved earlier) looks like "doing something
different" but does not diagnose or address the specific cause of the failure, and does not count
as Adaptive.

This "already known" check applies ONLY when deciding whether a lookup/read-style call (e.g.
list_request_types_and_fields, search/get-style tools) is fetching genuinely new information versus
repeating a prior one -- it does NOT apply to judging retries of the failing call itself (see (a)
below), where any concrete argument/value change should be evaluated on its own merits regardless of
how "small" it looks.

For lookup/read-style calls: before concluding one merely repeats "already known" information, you
MUST verify this at the argument level, not just the tool-name level: find the specific identifying
argument in the NEXT STEP (e.g. a request_type_id, app_name, or email) and check whether an evidence
entry using that EXACT SAME tool AND that EXACT SAME identifying argument value already exists below.
The same tool name called with a DIFFERENT identifying argument (e.g. list_request_types_and_fields
for request_type_id "443" when only "452" was looked up before, or a first-ever call to a tool not
used anywhere in the evidence yet) is NOT a repeat -- it is gathering genuinely new information.
Only mark Not Adaptive for "already known" reasons if you can point to the specific matching
evidence entry with the same argument value; if you cannot, do not use that justification.

Only mark Adaptive if the step does at least one of:
  (a) changes an actual argument/value from the failing call in a way that COULD plausibly respond
      to the specific error -- e.g. changing a field's data type or value. Give the agent the
      benefit of the doubt here: a concrete, targeted change to the previously-failing arguments
      counts as Adaptive even if you are not certain it will fix the error, as long as it is not
      merely re-submitting identical arguments unchanged,
  (b) asks the user for information the error indicates is missing or invalid, or
  (c) gathers information that is NOT already present in the evidence below and is specifically
      relevant to diagnosing this failure (not a generic re-fetch of something already known).
If the step does none of these -- including if it just repeats the same failing call unchanged, or
calls a different tool that only re-derives already-known information -- mark Not Adaptive.

Evidence collected so far (note the last entry's observation):
{evidence}

Agent's NEXT STEP:
{step}

Respond in EXACTLY this format, nothing else:
Verdict: Adaptive|Not Adaptive
Analysis: <one or two sentences>
"""

GOAL_ALIGNMENT_SYSTEM = (
    "You are an expert evaluator of whether an AI agent's action serves the user's stated goal."
)

GOAL_ALIGNMENT_USER_TMPL = """Given the user's current goal and the evidence gathered so far, judge whether the
agent's NEXT STEP is a reasonable step toward satisfying that goal (not off-topic, not skipping a needed check).

User's goal (all user messages so far, oldest first):
{goal}

Evidence collected so far:
{evidence}

Agent's NEXT STEP:
{step}

Respond in EXACTLY this format, nothing else:
Verdict: Aligned|Misaligned
Analysis: <one or two sentences>
"""


def extract_verdict(text):
    verdict = None
    for line in text.strip().splitlines():
        if line.strip().lower().startswith("verdict:"):
            verdict = line.split(":", 1)[1].strip()
    return verdict if verdict is not None else "Inconclusive"


FAILURE_CLASSIFIER_SYSTEM = (
    "You are a precise classifier of tool-call observations in an AI agent's "
    "trajectory. You decide whether an observation represents a genuine "
    "technical tool failure that the agent would need to recover from -- "
    "not a normal negative business answer, and not text that merely "
    "discusses errors/failures as its subject matter."
)

FAILURE_CLASSIFIER_USER_TMPL = """Decide whether this tool observation represents a genuine FAILURE.

A genuine FAILURE means the tool call itself could not be completed as intended: an HTTP error
(400/401/403/404/422/429/500/503), a validation error, a malformed-request error, a "not found" /
"does not exist" error for something the agent specifically asked to look up (e.g. an invalid ID),
an explicit unavailable-tool message, or a structured "successful": false / "completed": false status.

This is NOT a failure if it is:
- A normal, successful answer to a business question, even if the answer is "no" (e.g.
  have_app_access: false, is_valid: true/false with no invalid_reason, an empty search result set
  for apps/tickets that legitimately don't exist for this user).
- Reference/knowledge-base content that merely discusses errors, failures, or troubleshooting as its
  topic (e.g. a KB article titled "how to fix X error").
- A descriptive reply about something else containing the word "error" (e.g. summarizing a
  screenshot that shows an error message to the user).

Tool action: {action}
Observation:
{observation}

Respond in EXACTLY this format, nothing else:
Verdict: Failure|NotFailure
"""


def classify_is_failure(action, observation, model=None):
    obs_str = observation if isinstance(observation, str) else json.dumps(observation)
    if len(obs_str) > 4000:
        obs_str = obs_str[:4000] + "...[truncated]"
    analysis = call_llm(
        FAILURE_CLASSIFIER_SYSTEM,
        FAILURE_CLASSIFIER_USER_TMPL.format(action=action, observation=obs_str),
        # See note in is_only_redundancy_reasoning: reasoning models need
        # headroom beyond the verdict text itself.
        max_tokens=2000,
        model=model,
    )
    return extract_verdict(analysis) == "Failure"


# Groundedness/efficiency conflation fix: prompt-level attempts to teach the
# groundedness judge "redundant isn't the same as ungrounded" repeatedly
# bled leniency into genuinely fabricated/wrong cases too (tested and
# reverted -- see FINDINGS_03_REFINED_FULL_RUN.md). Handled instead as a
# separate, narrow classification applied only to "No" verdicts: does the
# stated reasoning actually argue fabrication, or does it only argue
# repetition/redundancy? Only overrides to "Yes" in the latter case.
REDUNDANCY_VS_FABRICATION_SYSTEM = (
    "You are a precise classifier of evaluator reasoning. You decide whether a stated justification "
    "for marking an AI agent's step 'ungrounded' is actually about fabrication, or only about "
    "the step being redundant/unnecessary/not the optimal choice."
)

REDUNDANCY_VS_FABRICATION_USER_TMPL = """An evaluator marked an agent's step "ungrounded" (a hallucination) with this reasoning:

{reasoning}

Decide: does this reasoning argue that some SPECIFIC VALUE OR CLAIM in the step is fabricated,
invented, unverified, or contradicts the evidence (e.g. a wrong person, an invented entity, a
policy claim not backed by evidence, a wrong category choice that contradicts what the evidence
says is correct, a placeholder value never seen in evidence)?

Or does it ONLY argue one of these, WITHOUT independently claiming any specific value is fabricated
or wrong:
- the step repeats/re-fetches information already known, OR
- an empty/wildcard argument (e.g. an empty id meaning "list everything") is criticized as if it
  were an invented specific value, when it is actually just a general/exploratory query with
  nothing to fabricate, OR
- a self-generated tracking/bookkeeping identifier (e.g. a conversation_id on a logging-type call)
  is criticized as unsupported, when such internal identifiers -- whether an explicit placeholder
  like "unknown"/"pending" or a realistic-looking generated value -- are not user-facing factual
  claims that need to appear in evidence.

IMPORTANT: "there's no evidence this action was needed/necessary" is NOT automatically
OnlyRedundancy -- check WHY it's being called unnecessary. If it's unnecessary because the specific
target (a person, entity, or fact) is wrong for this request, that IS a fabrication-adjacent problem
(a wrong-target mistake), not mere redundancy -- respond Fabrication. Only use OnlyRedundancy for
this "not needed" phrasing when the actual target/value itself is correct and the only issue is
that it duplicates something already known.

If the reasoning is ONLY one of the three bulleted things above (correctly scoped per the note),
with no independent claim that a specific value is factually wrong, invented, or targets the wrong
person/entity, respond OnlyRedundancy. Otherwise respond Fabrication.

Respond in EXACTLY this format, nothing else:
Verdict: Fabrication|OnlyRedundancy
"""


def is_only_redundancy_reasoning(reasoning, model=None):
    analysis = call_llm(
        REDUNDANCY_VS_FABRICATION_SYSTEM,
        REDUNDANCY_VS_FABRICATION_USER_TMPL.format(reasoning=reasoning),
        # Reasoning models (gemini-3.8, glm-5.3) spend tokens on hidden
        # reasoning before the verdict; a tiny budget yields empty content.
        max_tokens=2000,
        model=model,
    )
    return extract_verdict(analysis) == "OnlyRedundancy"


def evaluate_record(prepped, model=None):
    result = {"id": prepped["id"], "traceId": prepped["traceId"], "judge_model": model or MODEL}

    # Steps consisting solely of mandatory bookkeeping calls
    # (log_conversation_metadata/conversation_summary) are not evaluated at
    # all: they make no user-facing progress, so every metric is "Skipped"
    # without spending LLM calls. Handled structurally in code, NOT via a
    # prompt exception -- asking judges to selectively excuse logging steps
    # made them measurably more lenient on genuine substantive findings
    # (known Misaligned cases flipped to Aligned under every wording tried).
    if prepped["step"].get("is_logging_action"):
        for metric in ("groundedness", "efficiency", "adaptivity", "goal_alignment"):
            result[f"{metric}_raw"] = None
            result[f"{metric}_verdict"] = "Skipped"
        return result

    goal = str(prepped["goal"])[:30000]
    evidence = fmt_evidence(prepped["evidence"])
    step = json.dumps(prepped["step"])[:8000]

    analysis = call_llm(GROUNDEDNESS_SYSTEM, GROUNDEDNESS_USER_TMPL.format(goal=goal, evidence=evidence, step=step), model=model)
    result["groundedness_raw"] = analysis
    verdict = extract_verdict(analysis)
    if verdict == "No" and is_only_redundancy_reasoning(analysis, model=model):
        verdict = "Yes"
        result["groundedness_correction"] = "overridden: reasoning was only about redundancy, not fabrication"
    result["groundedness_verdict"] = verdict

    analysis = call_llm(EFFICIENCY_SYSTEM, EFFICIENCY_USER_TMPL.format(goal=goal, evidence=evidence, step=step), model=model)
    result["efficiency_raw"] = analysis
    result["efficiency_verdict"] = extract_verdict(analysis)

    # LLM-based failure classification, not the heuristic prepped["preceding_failure"]:
    # two rounds of hand-written heuristics (keyword scan, then structured-field
    # checks) each fixed some false positives/negatives and introduced or missed
    # others (see FINDINGS_01_INITIAL_SAMPLE.md, "Round 3"). Still not provably 100% reliable, but
    # verified more accurate than the heuristic on every case where they disagreed.
    is_failure = False
    if prepped["evidence"]:
        last = prepped["evidence"][-1]
        is_failure = classify_is_failure(last["action"], last["observation"], model=model)

    if is_failure:
        analysis = call_llm(ADAPTIVITY_SYSTEM, ADAPTIVITY_USER_TMPL.format(evidence=evidence, step=step), model=model)
        result["adaptivity_raw"] = analysis
        result["adaptivity_verdict"] = extract_verdict(analysis)
    else:
        result["adaptivity_verdict"] = "N/A"

    analysis = call_llm(GOAL_ALIGNMENT_SYSTEM, GOAL_ALIGNMENT_USER_TMPL.format(goal=goal, evidence=evidence, step=step), model=model)
    result["goal_alignment_raw"] = analysis
    result["goal_alignment_verdict"] = extract_verdict(analysis)

    return result


if __name__ == "__main__":
    # Smoke test: evaluate the first 3 records so a bad prompt/config edit is
    # caught quickly before running the full dataset via run_full_evaluation.py.
    # Optional arg: judge model id, e.g.
    #   python3 evaluate.py bedrock_internal_01/claude-sonnet-4-6
    model = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"Judge: {model or MODEL}")
    records = load_records()[:3]
    call_timestamps = build_call_timestamp_index(records)
    for r in records:
        prepped = prepare_record(r, call_timestamps)
        print(f"Evaluating {prepped['id']}...")
        res = evaluate_record(prepped, model=model)
        print(f"  groundedness={res.get('groundedness_verdict')} "
              f"efficiency={res.get('efficiency_verdict')} "
              f"adaptivity={res.get('adaptivity_verdict')} "
              f"goal_alignment={res.get('goal_alignment_verdict')}")
