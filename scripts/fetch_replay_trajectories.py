"""Fetch replayed trajectories from Langfuse, shaped like Genie_trajectories15_sep_2026.json.

Reads replay results (JSONL with genie_conversation_id + started/finished
timestamps), finds the matching Langfuse traces via a narrow time-window list
query + client-side sessionId filter (the API's sessionId filter is broken on
this instance), then keeps only `agent_chat_completion` GENERATION observations
projected onto the original export's Langfuse-native key set.

Usage:
    python3 scripts/fetch_replay_trajectories.py [replay_jsonl] [out_json]
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), override=True)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REPLAY = os.path.join(ROOT, "results", "replay_constructed_history_gpt-5.6-terra_136_20260920.jsonl")
ORIGINAL = os.path.join(ROOT, "Genie_trajectories15_sep_2026.json")
OUT = os.path.join(ROOT, "Genie_trajectories_replay_gpt-5.6-terra_20_sep_2026.json")

# Langfuse-native keys of the original export (the rest are downstream
# evaluation-annotation columns that only exist after scoring).
TRACE_KEYS = {"traceName", "traceTags", "traceTimestamp", "userId"}


def main():
    replay = sys.argv[1] if len(sys.argv) > 1 else REPLAY
    out = sys.argv[2] if len(sys.argv) > 2 else OUT
    base = os.environ["LANGFUSE_BASE_URL"].strip()
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])

    with open(ORIGINAL) as f:
        orig_keys = set(json.load(f)[0].keys())
    obs_keys = orig_keys - TRACE_KEYS

    replays = [json.loads(l) for l in open(replay) if l.strip()]
    sessions = {r["genie_conversation_id"] for r in replays}
    lo = min(r["started_at"] for r in replays)
    hi = max(r["finished_at"] for r in replays)
    pad = timedelta(minutes=2)
    frm = (datetime.fromisoformat(lo) - pad).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = (datetime.fromisoformat(hi) + pad).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"window {frm} .. {to}, sessions: {len(sessions)}")

    # list candidates in the window (paginate defensively)
    candidates, page = [], 1
    while True:
        r = requests.get(f"{base}/api/public/traces", auth=auth,
                         params={"fromTimestamp": frm, "toTimestamp": to,
                                 "limit": 100, "page": page}, timeout=120)
        r.raise_for_status()
        d = r.json()
        candidates.extend(d.get("data", []))
        if page >= d.get("meta", {}).get("totalPages", 1):
            break
        page += 1
    matched = [t for t in candidates if t.get("sessionId") in sessions]
    print(f"candidates in window: {len(candidates)}, matched sessions: {len(matched)}")

    records, missing = [], sessions - {t["sessionId"] for t in matched}
    for t in matched:
        r = requests.get(f"{base}/api/public/traces/{t['id']}", auth=auth, timeout=120)
        r.raise_for_status()
        trace = r.json()
        for o in trace.get("observations", []):
            if o.get("type") != "GENERATION" or o.get("name") != "agent_chat_completion":
                continue
            rec = {k: o.get(k) for k in obs_keys if k in o or k in orig_keys}
            rec.update({
                "traceName": trace.get("name"),
                "traceTags": trace.get("tags"),
                "traceTimestamp": trace.get("timestamp"),
                "userId": trace.get("userId"),
            })
            records.append(rec)
    records.sort(key=lambda r: (r["traceTimestamp"] or "", r["startTime"] or ""))

    with open(out, "w") as f:
        json.dump(records, f)
    print(f"wrote {len(records)} records across {len({r['traceId'] for r in records})} traces -> {out}")
    if missing:
        print(f"WARNING: {len(missing)} sessions not found in Langfuse: {sorted(missing)}")


if __name__ == "__main__":
    main()
