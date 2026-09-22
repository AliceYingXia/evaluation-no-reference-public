"""
Run the TRACE-adapted, reference-free evaluation (groundedness, efficiency,
adaptivity, goal-alignment) over every record in Genie_trajectories15_sep_2026.json.

Each record (turn) is evaluated completely independently -- see
EVALUATION_APPROACH.md for the methodology and why. Results are written
incrementally to OUT_PATH so a mid-run failure doesn't lose completed work.

Two modes:
  python3 run_full_evaluation.py                 full run: all four metrics,
                                                  skips ids already in the
                                                  results file
  python3 run_full_evaluation.py --adaptivity-only
                                                  re-evaluates ONLY the
                                                  adaptivity verdict, for
                                                  records that already have
                                                  one (~20-25 of 533), using
                                                  whatever ADAPTIVITY_USER_TMPL
                                                  currently is. Use this
                                                  instead of a full rerun
                                                  whenever you change just the
                                                  adaptivity prompt -- much
                                                  cheaper, and the other three
                                                  metrics don't depend on it.
                                                  Used for two rounds of
                                                  adaptivity prompt fixes so
                                                  far (see
                                                  FINDINGS_02_FULL_RUN.md).

Judge selection: the default judge is evaluate.MODEL (azure_internal_01/gpt-4.1,
temperature 0). Pass --model to use a different judge, e.g.
  python3 run_full_evaluation.py --model bedrock_internal_01/claude-sonnet-4-6
A non-default judge writes to results/full_evaluation_results_<model>.json so
per-judge result sets stay separate and can be compared for agreement.
--limit N bounds the number of newly-evaluated records (smoke tests).
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from extract import load_records, prepare_record, build_call_timestamp_index
from evaluate import (
    evaluate_record,
    fmt_evidence,
    ADAPTIVITY_SYSTEM,
    ADAPTIVITY_USER_TMPL,
    GROUNDEDNESS_SYSTEM,
    GROUNDEDNESS_USER_TMPL,
    MODEL as DEFAULT_MODEL,
    call_llm,
    extract_verdict,
    is_only_redundancy_reasoning,
)


def _dataset_label(src):
    """None for the original Sept-15 dataset (keeps historic result file
    names); otherwise a filesystem-safe label derived from the file name."""
    if not src:
        return None
    name = os.path.splitext(os.path.basename(src))[0]
    if name == "Genie_trajectories15_sep_2026":
        return None
    name = re.sub(r"^Genie_trajectories_?", "", name) or "dataset"
    return re.sub(r"[^A-Za-z0-9.-]+", "-", name)


def _out_path(model=None, src=None):
    """Default judge + original dataset -> the historic results file; other
    judges and/or datasets get their own file so verdicts never mix."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
    name = "full_evaluation_results"
    label = _dataset_label(src)
    if label:
        name += f"_{label}"
    if model and model != DEFAULT_MODEL:
        name += "_" + re.sub(r"[^A-Za-z0-9.-]+", "-", model.split("/")[-1])
    return os.path.normpath(os.path.join(base, name + ".json"))


OUT_PATH = _out_path()
JUDGE_MODEL = None  # None -> evaluate.MODEL; set via --model
SRC_PATH = None     # None -> extract.SRC; set via --src
CHECKPOINT_EVERY = 20
MAX_WORKERS = 6
ADAPTIVITY_MAX_WORKERS = 8

_lock = threading.Lock()


def _save(results):
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp_path = OUT_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(results, f, indent=2)
    os.replace(tmp_path, OUT_PATH)


def _load_existing():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            return json.load(f)
    return []


def run_full(limit=None):
    records = load_records(SRC_PATH)
    call_timestamps = build_call_timestamp_index(records)

    existing = _load_existing()
    done_ids = {r["id"] for r in existing}
    todo = [r for r in records if r["id"] not in done_ids]
    if limit:
        todo = todo[:limit]

    print(f"Judge: {JUDGE_MODEL or DEFAULT_MODEL} -> {OUT_PATH}")
    print(f"Total records: {len(records)} | already done: {len(done_ids)} | remaining: {len(todo)}")

    results = existing
    completed_since_checkpoint = 0
    start = time.time()

    def worker(record):
        prepped = prepare_record(record, call_timestamps)
        try:
            return evaluate_record(prepped, model=JUDGE_MODEL)
        except Exception as e:
            return {"id": prepped["id"], "traceId": prepped["traceId"], "error": str(e)}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(worker, r): r["id"] for r in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            with _lock:
                results.append(res)
                completed_since_checkpoint += 1
                if completed_since_checkpoint >= CHECKPOINT_EVERY:
                    _save(results)
                    completed_since_checkpoint = 0
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else float("inf")
            print(f"[{len(done_ids) + i}/{len(records)}] {res.get('id')} "
                  f"groundedness={res.get('groundedness_verdict')} "
                  f"efficiency={res.get('efficiency_verdict')} "
                  f"adaptivity={res.get('adaptivity_verdict')} "
                  f"goal_alignment={res.get('goal_alignment_verdict')} "
                  f"| eta {eta/60:.1f}min", flush=True)

    _save(results)
    print(f"\nDone. Wrote {len(results)} total results to {OUT_PATH}")


def run_adaptivity_only():
    records = load_records(SRC_PATH)
    ts = build_call_timestamp_index(records)
    by_id = {r["id"]: r for r in records}

    results = _load_existing()
    if not results:
        print(f"No existing results at {OUT_PATH} -- run a full evaluation first.")
        return

    targets = [res for res in results if res.get("adaptivity_verdict") not in (None, "N/A", "Skipped")]
    print(f"Re-evaluating adaptivity for {len(targets)} records with the current prompt...")

    def refresh(res):
        rid = res["id"]
        r = by_id.get(rid)
        if r is None:
            return rid, res.get("adaptivity_verdict"), None
        p = prepare_record(r, ts)
        evidence = fmt_evidence(p["evidence"])
        step = json.dumps(p["step"])[:8000]
        analysis = call_llm(ADAPTIVITY_SYSTEM, ADAPTIVITY_USER_TMPL.format(evidence=evidence, step=step), model=JUDGE_MODEL)
        return rid, extract_verdict(analysis), analysis

    changed = 0
    by_result_id = {res["id"]: res for res in results}
    with ThreadPoolExecutor(max_workers=ADAPTIVITY_MAX_WORKERS) as pool:
        futures = {pool.submit(refresh, res): res["id"] for res in targets}
        for fut in as_completed(futures):
            rid, new_verdict, new_raw = fut.result()
            old_verdict = by_result_id[rid].get("adaptivity_verdict")
            if new_verdict != old_verdict:
                changed += 1
                print(f"  {rid}: {old_verdict} -> {new_verdict}")
            by_result_id[rid]["adaptivity_verdict"] = new_verdict
            by_result_id[rid]["adaptivity_raw"] = new_raw

    _save(results)
    print(f"\nRe-evaluated {len(targets)} records, {changed} verdicts changed.")
    print(f"Wrote updated results to {OUT_PATH}")


def run_groundedness_only(all_records=False):
    """Re-evaluate the groundedness verdict using the current
    GROUNDEDNESS_USER_TMPL plus the redundancy-vs-fabrication classifier
    gate. By default only re-checks records currently 'No' (cheap, for
    tuning the classifier). With all_records=True, recomputes groundedness
    from scratch for every record -- use this to check for false negatives
    (records the current pipeline never flagged at all), not just to tune
    false positives among existing 'No's."""
    records = load_records(SRC_PATH)
    ts = build_call_timestamp_index(records)
    by_id = {r["id"]: r for r in records}

    results = _load_existing()
    if not results:
        print(f"No existing results at {OUT_PATH} -- run a full evaluation first.")
        return

    if all_records:
        targets = results
        print(f"Re-evaluating groundedness for ALL {len(targets)} records (full recheck)...")
    else:
        targets = [res for res in results if res.get("groundedness_verdict") == "No"]
        print(f"Re-evaluating groundedness for {len(targets)} records with the current prompt...")

    def refresh(res):
        rid = res["id"]
        r = by_id.get(rid)
        if r is None:
            return rid, res.get("groundedness_verdict"), None, None
        p = prepare_record(r, ts)
        if p["step"].get("is_logging_action"):
            return rid, "Skipped", None, None
        goal = str(p["goal"])[:30000]
        evidence = fmt_evidence(p["evidence"])
        step = json.dumps(p["step"])[:8000]
        analysis = call_llm(GROUNDEDNESS_SYSTEM, GROUNDEDNESS_USER_TMPL.format(goal=goal, evidence=evidence, step=step), model=JUDGE_MODEL)
        verdict = extract_verdict(analysis)
        correction = None
        if verdict == "No" and is_only_redundancy_reasoning(analysis, model=JUDGE_MODEL):
            verdict = "Yes"
            correction = "overridden: reasoning was only about redundancy, not fabrication"
        return rid, verdict, analysis, correction

    changed = 0
    by_result_id = {res["id"]: res for res in results}
    with ThreadPoolExecutor(max_workers=ADAPTIVITY_MAX_WORKERS) as pool:
        futures = {pool.submit(refresh, res): res["id"] for res in targets}
        for fut in as_completed(futures):
            rid, new_verdict, new_raw, correction = fut.result()
            old_verdict = by_result_id[rid].get("groundedness_verdict")
            if new_verdict != old_verdict:
                changed += 1
                print(f"  {rid}: {old_verdict} -> {new_verdict}" + (f" ({correction})" if correction else ""))
            by_result_id[rid]["groundedness_verdict"] = new_verdict
            by_result_id[rid]["groundedness_raw"] = new_raw
            if correction:
                by_result_id[rid]["groundedness_correction"] = correction

    _save(results)
    print(f"\nRe-evaluated {len(targets)} records, {changed} verdicts changed.")
    print(f"Wrote updated results to {OUT_PATH}")


def main():
    global OUT_PATH, JUDGE_MODEL, SRC_PATH
    args = sys.argv[1:]
    if "--model" in args:
        i = args.index("--model")
        JUDGE_MODEL = args[i + 1]
        OUT_PATH = _out_path(JUDGE_MODEL)
        del args[i:i + 2]
    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]

    if "--src" in args:
        i = args.index("--src")
        SRC_PATH = args[i + 1]
        OUT_PATH = _out_path(JUDGE_MODEL, SRC_PATH)
        del args[i:i + 2]
    if "--adaptivity-only" in args:
        run_adaptivity_only()
    elif "--groundedness-full" in args:
        run_groundedness_only(all_records=True)
    elif "--groundedness-only" in args:
        run_groundedness_only()
    else:
        run_full(limit=limit)


if __name__ == "__main__":
    main()
