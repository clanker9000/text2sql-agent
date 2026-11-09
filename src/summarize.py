"""Turn results/*.jsonl into the tables you need for the report.

  python -m src.summarize --split eval

Writes into the same results folder:
  summary.csv      accuracy + cost per condition (overall and by difficulty)
  transitions.csv  per pair of conditions: how many questions got fixed / broken / stayed the same
  failures.csv     one row per question with every condition's SQL and outcome, plus an empty
                   `error_category` column for your manual error analysis
"""
import argparse
import json

import pandas as pd

from . import agent, config


def load(folder):
    frames = []
    for c in agent.CONDITIONS:
        p = folder / f"{c}.jsonl"
        if p.exists():
            frames.append(pd.DataFrame([json.loads(l) for l in p.open(encoding="utf-8")]))
    if not frames:
        raise SystemExit(f"no results in {folder}")
    return pd.concat(frames, ignore_index=True)


def main(folder):
    df = load(folder)
    conds = [c for c in agent.CONDITIONS if c in set(df.condition)]

    # Only compare questions that every condition finished (keeps it paired).
    common = set.intersection(*(set(df[df.condition == c].qid) for c in conds))
    df = df[df.qid.isin(common)]
    print(f"{folder.name}: {len(common)} questions completed by all of {conds}\n")

    # --- summary ---
    rows = []
    for c in conds:
        d = df[df.condition == c]
        r = {"condition": c, "n": len(d), "EX": d.correct.mean()}
        for diff in ["simple", "moderate", "challenging"]:
            r[f"EX_{diff}"] = d[d.difficulty == diff].correct.mean()
        r.update({
            "final_query_runs": d.final_exec_ok.mean(),
            "avg_llm_calls": d.n_llm_calls.mean(), "avg_tokens": d.tokens.mean(),
            "avg_latency_s": d.latency_s.mean(), "pct_blocked": d.blocked.mean(),
        })
        rows.append(r)
    summary = pd.DataFrame(rows)
    summary.to_csv(folder / "summary.csv", index=False)
    with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 200):
        print(summary.to_string(index=False), "\n")

    # --- transitions (what did adding a step fix / break?) ---
    wide = df.pivot(index="qid", columns="condition", values="correct")
    trans = []
    for a, b in [("oneshot", "retry"), ("retry", "selfcheck"), ("oneshot", "selfcheck")]:
        if a in wide and b in wide:
            trans.append({
                "from": a, "to": b,
                "fixed (wrong->right)": int((~wide[a] & wide[b]).sum()),
                "broken (right->wrong)": int((wide[a] & ~wide[b]).sum()),
                "both right": int((wide[a] & wide[b]).sum()),
                "both wrong": int((~wide[a] & ~wide[b]).sum()),
            })
    trans = pd.DataFrame(trans)
    trans.to_csv(folder / "transitions.csv", index=False)
    print(trans.to_string(index=False), "\n")
    print("(B: the fixed/broken counts are the inputs for McNemar's test.)")

    # --- failures sheet for manual error analysis ---
    base = df[df.condition == conds[0]][["qid", "db_id", "difficulty", "question", "gold_sql"]]
    for c in conds:
        d = df[df.condition == c].set_index("qid")
        base[f"{c}_correct"] = base.qid.map(d.correct)
        base[f"{c}_sql"] = base.qid.map(d.pred_sql)
        base[f"{c}_calls"] = base.qid.map(d.n_llm_calls)
    base["error_category"] = ""
    base.to_csv(folder / "failures.csv", index=False)
    print(f"wrote summary.csv, transitions.csv, failures.csv to {folder}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="pilot", help="results subfolder name, e.g. eval or eval__allowlist+readonly")
    main(config.RESULTS_DIR / ap.parse_args().split)
