import json
import os

SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Genie_trajectories15_sep_2026.json",
)


def is_tool_def(msg):
    return (
        msg.get("role") == "tool"
        and isinstance(msg.get("content"), dict)
        and msg["content"].get("type") == "function"
    )


def strip_tool_defs(msgs):
    return [m for m in msgs if not is_tool_def(m)]


def last_user_message(msgs):
    for m in reversed(msgs):
        if m.get("role") == "user":
            return m.get("content")
    return None


def all_user_messages(msgs):
    """All user messages in order, not just the most recent one -- details
    relevant to the current step are often stated in an earlier turn of the
    same conversation, not repeated in the latest message."""
    return [m.get("content") for m in msgs if m.get("role") == "user"]


LOGGING_ACTIONS = {"log_conversation_metadata", "conversation_summary"}


def build_call_timestamp_index(records):
    """Map tool_call_id -> the startTime of the record whose output issued
    that call. Needed because evidence entries carry no timestamp of their
    own, so an evaluator can't otherwise tell a call made 2 seconds ago from
    one made 6 days ago."""
    index = {}
    for r in records:
        out = r.get("output") or {}
        for tc in out.get("tool_calls") or []:
            index[tc["id"]] = r.get("startTime")
    return index


def build_evidence_bank(msgs, call_timestamps=None):
    """Walk the (already-stripped) message list and pair assistant tool_calls
    with their following tool result messages, by tool_call_id."""
    call_timestamps = call_timestamps or {}
    evidence = []
    pending_calls = {}  # id -> (name, args)
    for m in msgs:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                pending_calls[tc["id"]] = (tc["name"], tc.get("args"))
        elif role == "tool":
            tcid = m.get("tool_call_id")
            if tcid in pending_calls:
                name, args = pending_calls.pop(tcid)
                evidence.append(
                    {
                        "action": name,
                        "input": args,
                        "observation": m.get("content"),
                        "timestamp": call_timestamps.get(tcid),
                        "is_logging_action": name in LOGGING_ACTIONS,
                    }
                )
    return evidence


FAILURE_FALSE_KEYS = {"successful", "completed", "available"}
# Deliberately excludes "is_valid" and "have_app_access": those are normal,
# successful informational answers to a business question ("no, this user
# doesn't have access" / "no, this request isn't valid") -- not a technical
# tool failure the agent needs to adapt around.


def last_observation_is_failure(evidence):
    """SUPERSEDED / not used by the current pipeline -- see FINDINGS_01_INITIAL_SAMPLE.md,
    "Round 3". evaluate.py's evaluate_record() now calls
    classify_is_failure() (an LLM classification call) directly instead of
    this heuristic; that approach is verified more accurate on every case
    where the two disagreed. Kept here only because scripts/archive/*.py
    (historical one-off correction scripts) still call it for provenance --
    do not wire this back into the main pipeline.

    Detect whether the last evidence entry represents a genuine tool
    failure. Deliberately stricter than a raw keyword scan: field NAMES like
    invalid_category/invalid_reason are null (i.e. not a problem) on a
    successful check, so naive substring matching on 'invalid'/'error'
    across the whole JSON text produces false positives whenever those keys
    are merely present-but-null. Even this stricter version has known gaps
    (a length cutoff that can exclude genuine long error strings, and no way
    to catch errors nested inside unexpected key names) -- see FINDINGS_01_INITIAL_SAMPLE.md
    for the specific cases that exposed this."""
    if not evidence:
        return False
    obs = evidence[-1]["observation"]

    if isinstance(obs, dict):
        parsed = obs
    elif isinstance(obs, str):
        try:
            parsed = json.loads(obs)
        except (json.JSONDecodeError, TypeError):
            parsed = None
    else:
        parsed = None

    if isinstance(parsed, dict):
        for key in FAILURE_FALSE_KEYS:
            if key in parsed and parsed[key] is False:
                return True
        if parsed.get("errorMessage") or parsed.get("error"):
            return True
        if parsed.get("invalid_reason") not in (None, "") or parsed.get("invalid_category") not in (None, ""):
            return True
        return False

    # Not JSON (e.g. a plain-text tool error like "422 Unprocessable Entity: ..."
    # or "This tool is not available now. consider other tools."). Genuine
    # short structured error strings in this dataset are all well under 600
    # chars; longer text is either a KB article dump (which failed to parse
    # as JSON solely because it's enormous/malformed) or a descriptive tool
    # reply that merely discusses an error as its subject matter -- keyword
    # scanning those produces false positives, so skip the scan entirely
    # above this length rather than risk matching incidental content.
    text = obs if isinstance(obs, str) else json.dumps(obs)
    if len(text) > 600:
        return False
    text = text.lower()
    return any(
        kw in text
        for kw in ["error", "unavailable", "not available", "fail", "unable", "422"]
    )


def extract_step(output):
    """Return the action(s) or final answer being judged for this record."""
    if output.get("tool_calls"):
        return {"kind": "action", "calls": output["tool_calls"]}
    return {"kind": "final", "content": output.get("content")}


def load_records(path=None):
    with open(path or SRC) as f:
        return json.load(f)


def prepare_record(record, call_timestamps=None):
    msgs = strip_tool_defs(record["input"])
    evidence = build_evidence_bank(msgs, call_timestamps)
    user_msgs = all_user_messages(msgs)
    goal = "\n\n---\n\n".join(str(m) for m in user_msgs) if user_msgs else None
    step = extract_step(record["output"])
    step["current_time"] = record.get("startTime")
    if step.get("kind") == "action":
        step["is_logging_action"] = all(
            c["name"] in LOGGING_ACTIONS for c in step["calls"]
        )
    return {
        "id": record["id"],
        "traceId": record["traceId"],
        "goal": goal,
        "evidence": evidence,
        "step": step,
        "preceding_failure": last_observation_is_failure(evidence),
    }


if __name__ == "__main__":
    records = load_records()
    call_timestamps = build_call_timestamp_index(records)
    for r in records[:3]:
        prepped = prepare_record(r, call_timestamps)
        print("id:", prepped["id"])
        print("  evidence entries:", len(prepped["evidence"]))
        print("  goal (truncated):", str(prepped["goal"])[:150])
        print("  step:", json.dumps(prepped["step"])[:200])
        print("  preceding_failure:", prepped["preceding_failure"])
        print()
