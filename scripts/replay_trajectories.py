"""Replay sampled Genie trajectories into the connected genie via the headless API.

Per trace (= trajectory): create a fresh genie conversation, then send every
recorded user turn in order -- history turns first, final input last -- so the
genie rebuilds the conversation history itself. Results are appended as JSONL
(one line per trace) so the run is resumable: already-replayed traceIds are
skipped on re-run.

Usage:
    python3 scripts/replay_trajectories.py --limit 2          # smoke test
    python3 scripts/replay_trajectories.py                    # full 100
"""

import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), override=True)

import workato_client as w  # noqa: E402
from extract import strip_tool_defs  # noqa: E402

TOOL_RESULT_CAP = 4000
MAX_MESSAGE = 12288  # genie headless API hard limit on the message field
MESSAGE_TARGET = 12200  # small safety margin


def render_trace_input(msgs, tool_result_cap=TOOL_RESULT_CAP, drop_oldest=0):
    """Flatten one trace's message list into a single user message.

    History = every user turn, assistant reply, assistant tool call and tool
    result before the final user message, verbatim (tool results capped at
    tool_result_cap chars; cap None omits the body entirely). drop_oldest
    skips that many leading history entries (used to fit MAX_MESSAGE).
    First-turn traces return the bare user message.
    """
    convo = [m for m in msgs if m.get("role") in ("user", "assistant", "tool")]
    last_user = max(i for i, m in enumerate(convo) if m["role"] == "user")
    history, current = convo[:last_user], convo[last_user]["content"]

    call_names = {}  # tool_call_id -> tool name, for labeling results
    blocks = []  # list of rendered history entries (each = list of lines)
    for m in history:
        role = m["role"]
        if role == "user":
            blocks.append(["[User]", m["content"], ""])
        elif role == "assistant":
            if m.get("content"):
                blocks.append(["[Assistant]", m["content"], ""])
            for tc in m.get("tool_calls") or []:
                call_names[tc["id"]] = tc["name"]
                blocks.append([f"[Assistant calls tool: {tc['name']}]",
                               "Arguments: " + json.dumps(tc.get("args"), default=str), ""])
        elif role == "tool":
            c = m.get("content")
            c = c if isinstance(c, str) else json.dumps(c, default=str)
            name = call_names.get(m.get("tool_call_id"))
            head = f"[Tool result: {name}]" if name else "[Tool result]"
            if tool_result_cap is None:
                blocks.append([head, f"[omitted, {len(c)} chars]", ""])
            else:
                if len(c) > tool_result_cap:
                    c = c[:tool_result_cap] + f" …[truncated, {len(c)} chars total]"
                blocks.append([head, c, ""])
    if not blocks:
        return current
    blocks = blocks[drop_oldest:]
    body = "\n".join(ln for b in blocks for ln in b).rstrip()
    return ("This is a continuation of an earlier support conversation. Below is the transcript "
            "so far, including your previous replies and the results of tools you called.\n\n"
            f"--- CONVERSATION HISTORY ---\n{body}\n--- END OF HISTORY ---\n\n"
            f"Now respond to the user's latest message:\n\n[User]\n{current}")


def construct_input(records):
    """Single constructed message for a trace (v2 replay): history incl. tool
    calls/results embedded in the prompt, current turn last. Fits the genie's
    12288-char message limit by shrinking tool-result caps, then dropping the
    oldest history entries; the current turn is never altered."""
    rec = max(records, key=lambda r: (len(r.get("input") or []), r["startTime"]))
    msgs = strip_tool_defs(rec["input"])
    # first: shrink tool-result bodies, keeping every history entry
    for cap in (TOOL_RESULT_CAP, 1500, 600, 200, None):
        msg = render_trace_input(msgs, tool_result_cap=cap)
        if len(msg) <= MESSAGE_TARGET:
            return msg
    # last resort: omit tool bodies AND drop oldest history entries
    n_entries = sum(1 for m in msgs if m.get("role") in ("user", "assistant", "tool")) - 1
    for drop in range(1, n_entries + 1):
        msg = render_trace_input(msgs, tool_result_cap=None, drop_oldest=drop)
        if len(msg) <= MESSAGE_TARGET:
            return msg
    return msg  # user/assistant text alone exceeds the limit; send as-is (will 400)

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Genie_trajectories15_sep_2026.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "replay_100_seed42_20260919.jsonl")
OUT_FIRST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "replay_first_turns_52_20260919.jsonl")
OUT_CONSTRUCT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "replay_constructed_history_gpt-5.6-terra_136_20260920.jsonl")
SAMPLE_SIZE = 100
SEED = 42
WORKERS = 4
MSG_TIMEOUT = 420  # tool-using turns are much slower than a greeting

_write_lock = threading.Lock()


def extract_turns(records):
    """User turns of a trace, in order, from its fullest generation record."""
    rec = max(records, key=lambda r: (len(r.get("input") or []), r["startTime"]))
    return [m["content"] for m in rec["input"] if m.get("role") == "user" and isinstance(m.get("content"), str)]


def send_turn(conv_id: str, text: str) -> dict:
    genie = os.environ["WORKATO_GENIE_ID"]
    base = os.environ["WORKATO_GENIE_BASE_URL"]
    headers = {
        "Authorization": f"Bearer {os.environ['WORKATO_GENIE_API_KEY']}",
        "X-IDP-User-Id": os.environ["WORKATO_IDP_USER_ID"],
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    t0 = time.time()
    r = requests.post(
        f"{base}/genies/{genie}/chat/conversations/{conv_id}/messages",
        headers=headers,
        json={"message": text, "stream": True},
        stream=True,
        timeout=MSG_TIMEOUT,
    )
    replies, events, errors = [], [], []
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        etype = ev.get("type")
        if etype == "agent.message" and ev.get("message"):
            replies.append(ev["message"])
        elif etype and "error" in etype.lower():
            errors.append(ev)
        elif etype:
            events.append(etype)
    return {
        "http_status": r.status_code,
        "latency_s": round(time.time() - t0, 2),
        "reply": "\n".join(replies) if replies else None,
        "n_agent_messages": len(replies),
        "events": events,
        "errors": errors or None,
    }


def replay_trace(trace_id: str, turns: list) -> dict:
    conv = w.create_conversation()["result"]["conversation_id"]
    result = {
        "trace_id": trace_id,
        "genie_conversation_id": conv,
        "n_turns": len(turns),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "turns": [],
    }
    for i, text in enumerate(turns):
        try:
            outcome = send_turn(conv, text)
        except Exception as e:  # network/timeout -- record and stop this trace
            outcome = {"exception": f"{type(e).__name__}: {e}"}
        result["turns"].append({"turn": i, "sent": text, **outcome})
        if outcome.get("exception") or (outcome.get("http_status") or 200) != 200:
            result["aborted"] = True
            break
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help=f"cap traces replayed (default: {SAMPLE_SIZE} in sample modes, all in --construct-history)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--first-turn-only", action="store_true",
                        help="replay only traces with exactly one user turn (no history)")
    parser.add_argument("--construct-history", action="store_true",
                        help="v2: one message per trace with recorded history (incl. tool "
                             "calls/results) embedded in the prompt; replays ALL traces")
    args = parser.parse_args()

    if args.construct_history:
        out = OUT_CONSTRUCT
    elif args.first_turn_only:
        out = OUT_FIRST
    else:
        out = OUT

    with open(SRC) as f:
        data = json.load(f)
    by_trace = {}
    for it in data:
        by_trace.setdefault(it["traceId"], []).append(it)

    if args.construct_history:
        turns_by_trace = {t: [construct_input(recs)] for t, recs in by_trace.items()}
        sample = sorted(turns_by_trace)[: args.limit] if args.limit else sorted(turns_by_trace)
    else:
        turns_by_trace = {t: extract_turns(recs) for t, recs in by_trace.items()}
        turns_by_trace = {t: u for t, u in turns_by_trace.items() if u}
        if args.first_turn_only:
            turns_by_trace = {t: u for t, u in turns_by_trace.items() if len(u) == 1}
        sample = random.Random(args.seed).sample(sorted(turns_by_trace), min(args.limit or SAMPLE_SIZE, len(turns_by_trace)))

    done = set()
    if os.path.exists(out):
        with open(out) as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["trace_id"])
    todo = [t for t in sample if t not in done]
    total_turns = sum(len(turns_by_trace[t]) for t in todo)
    print(f"sample={len(sample)} already_done={len(done)} todo={len(todo)} total_turns={total_turns}", flush=True)
    if not todo:
        return

    os.makedirs(os.path.dirname(out), exist_ok=True)
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool, open(out, "a") as out_f:
        futures = {pool.submit(replay_trace, t, turns_by_trace[t]): t for t in todo}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {"trace_id": t, "exception": f"{type(e).__name__}: {e}",
                          "finished_at": datetime.now(timezone.utc).isoformat()}
            with _write_lock:
                out_f.write(json.dumps(result) + "\n")
                out_f.flush()
            completed += 1
            status = "ABORTED" if result.get("aborted") else ("EXC" if result.get("exception") else "ok")
            print(f"[{completed}/{len(todo)}] {t} turns={result.get('n_turns')} {status}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
