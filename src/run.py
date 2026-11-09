"""Run the agent on a split and log one JSON line per question.

  python -m src.run --condition oneshot --split pilot
  python -m src.run --condition all --split eval --workers 8
  python -m src.run --condition selfcheck --split pilot --limit 5 --layers allowlist,readonly

Output: results/<split>[__<layers>]/<condition>.jsonl  (resumable: finished questions are skipped)
"""
import argparse
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from . import agent, config, data, scorer


def out_path(split, condition, layers):
    tag = split + ("__" + "+".join(sorted(layers)) if layers else "")
    p = config.RESULTS_DIR / tag / f"{condition}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def run_one(item, condition, layers):
    db = data.db_path(item["db_id"])
    res = agent.solve(item, condition, db, layers=layers)
    correct, score_err = scorer.score(item, res.final_sql, db)
    return {
        "qid": item["question_id"], "db_id": item["db_id"], "difficulty": item["difficulty"],
        "condition": condition, "layers": sorted(layers), "model": config.LLM_MODEL,
        "question": item["question"], "gold_sql": item["SQL"],
        "pred_sql": res.final_sql, "correct": bool(correct), "score_error": score_err,
        "blocked": res.any_blocked,
        "n_llm_calls": res.n_llm_calls, "n_retries": res.n_retries, "n_exec": res.n_exec,
        "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens,
        "tokens": res.prompt_tokens + res.completion_tokens,
        "latency_s": round(res.llm_latency_s, 3), "stop_reason": res.stop_reason,
        "final_exec_ok": res.final_exec_ok, "trajectory": res.trajectory,
    }


def run_condition(items, condition, layers, workers, split):
    path = out_path(split, condition, layers)
    done = set()
    if path.exists():
        done = {json.loads(l)["qid"] for l in path.open(encoding="utf-8")}
    todo = [it for it in items if it["question_id"] not in done]
    print(f"\n== {condition} | {len(done)} done, {len(todo)} to run -> {path}")
    lock = threading.Lock()
    with ThreadPoolExecutor(workers) as ex, path.open("a", encoding="utf-8") as f:
        futs = {ex.submit(run_one, it, condition, layers): it for it in todo}
        for fut in tqdm(as_completed(futs), total=len(futs)):
            try:
                row = fut.result()
            except Exception:
                print(f"[error] qid={futs[fut]['question_id']}\n{traceback.format_exc()}")
                continue
            with lock:
                f.write(json.dumps(row, default=str) + "\n")
                f.flush()
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    acc = sum(r["correct"] for r in rows) / max(len(rows), 1)
    print(f"   {condition}: EX = {acc:.1%} on {len(rows)} questions")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", default="all", choices=list(agent.CONDITIONS) + ["all"])
    ap.add_argument("--split", default="pilot", choices=["pilot", "eval", "eval_full"])
    ap.add_argument("--limit", type=int, default=None, help="only the first N questions (smoke tests)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--layers", default="", help="comma list: prompt_rule,allowlist,readonly,approval or 'all'")
    args = ap.parse_args()

    layers = set()
    if args.layers == "all":
        layers = set(agent.harness.ALL_LAYERS)
    elif args.layers:
        layers = set(args.layers.split(","))
        assert layers <= agent.harness.ALL_LAYERS, f"unknown layer in {layers}"

    items = data.get_split(args.split)[: args.limit]
    conds = agent.CONDITIONS if args.condition == "all" else [args.condition]
    print(f"model={config.LLM_MODEL} split={args.split} n={len(items)} layers={sorted(layers) or 'none'}")
    t0 = time.time()
    for c in conds:  # oneshot first, so retry/selfcheck reuse its cached first attempt
        run_condition(items, c, frozenset(layers), args.workers, args.split)
    print(f"\ndone in {time.time() - t0:.0f}s. Next: python -m src.summarize --split {args.split}")
