"""False-block rate: replay A's predicted SQL (normal, innocent questions) through the harness.

  python -m src.false_block                    # replays results/eval/{oneshot,retry,selfcheck}.jsonl

For every predicted query and every layer setting, run harness.execute() and count how often a
layer BLOCKS it. Every one of these queries comes from an innocent question, so every block is a
false block. Identical (database, query) pairs are only executed once per setting.
prompt_rule is not replayed: it changes the prompt, not execution. Its accuracy cost shows up in
A's `--layers all` re-run instead.

Writes results/false_block/summary.csv and blocked_queries.csv
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import agent, config, data, harness

CONFIGS = {
    "none": frozenset(),
    "allowlist": frozenset({"allowlist"}),
    "readonly": frozenset({"readonly"}),
    "approval": frozenset({"approval"}),
    "all": harness.ALL_LAYERS,
}


def main(split="eval", workers=8, timeout_s=30.0):
    rows = []
    for c in agent.CONDITIONS:
        p = config.RESULTS_DIR / split / f"{c}.jsonl"
        rows += [json.loads(l) for l in p.open(encoding="utf-8")]
    unique = sorted({(r["db_id"], r["pred_sql"]) for r in rows})
    jobs = [(db, sql, cn) for db, sql in unique for cn in CONFIGS]
    print(f"{len(rows)} predicted queries ({len(unique)} unique) x {len(CONFIGS)} settings")

    def run(job):
        db, sql, cn = job
        res = harness.execute(sql, data.db_path(db), layers=CONFIGS[cn], timeout_s=timeout_s, max_rows=1)
        return job, {"ok": res.ok, "blocked": res.blocked, "blocked_by": res.blocked_by,
                     "block_reason": res.block_reason, "error": res.error,
                     "timed_out": bool(res.extra.get("timed_out"))}

    with ThreadPoolExecutor(workers) as ex:
        out = dict(ex.map(run, jobs))

    recs = []
    for r in rows:
        for cn in CONFIGS:
            o = out[(r["db_id"], r["pred_sql"], cn)]
            base = out[(r["db_id"], r["pred_sql"], "none")]
            recs.append({"qid": r["qid"], "db_id": r["db_id"], "condition": r["condition"], "config": cn,
                         "pred_sql": r["pred_sql"], "correct_without_layers": r["correct"],
                         "ran_without_layers": base["ok"], **o})
    df = pd.DataFrame(recs)
    out_dir = config.RESULTS_DIR / "false_block"
    out_dir.mkdir(parents=True, exist_ok=True)
    summ = (df.groupby(["config", "condition"])
              .agg(n=("blocked", "size"), blocked=("blocked", "sum"),
                   blocked_but_was_correct=("correct_without_layers",
                                            lambda s: int((s & df.loc[s.index, "blocked"]).sum())),
                   timed_out=("timed_out", "sum"))
              .reset_index())
    pooled = (df.groupby("config").agg(n=("blocked", "size"), blocked=("blocked", "sum"),
                                       timed_out=("timed_out", "sum")).reset_index())
    pooled["condition"] = "all_versions"
    summ = pd.concat([summ, pooled], ignore_index=True)
    summ["false_block_rate"] = summ.blocked / summ.n
    summ.to_csv(out_dir / "summary.csv", index=False)
    df[df.blocked].drop_duplicates(["db_id", "pred_sql", "config"]).to_csv(out_dir / "blocked_queries.csv",
                                                                           index=False)
    print(summ.to_string(index=False))
    print(f"\nwrote {out_dir / 'summary.csv'} and blocked_queries.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="eval")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    main(a.split, a.workers)
