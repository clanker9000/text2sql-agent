"""Statistics and figures for both parts of the report (B).

  python -m src.stats

Reads whatever exists of:
  results/eval/{oneshot,retry,selfcheck}.jsonl                  A's accuracy runs (required)
  results/eval__allowlist+approval+prompt_rule+readonly/*.jsonl  A's re-run with all layers on (optional)
  results/false_block/summary.csv                               python -m src.false_block (optional)
  results/attacks/{direct,agent}.jsonl                          python -m src.attacks (optional)

Writes results/stats/*.csv, results/stats/figures/*.png and results/stats/stats.md

Methods (all paired by question, because every version answers the same 300 questions):
  * accuracy CIs and differences: paired bootstrap, 10,000 resamples of questions, seed 469, 95% percentile CI
  * is a difference real? exact McNemar test on the discordant pairs (fixed vs broken), plus Holm
    correction across the comparisons in the same table
  * rates with small n (attack success, false blocks): Wilson 95% interval
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from statsmodels.stats.contingency_tables import mcnemar  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402
from statsmodels.stats.proportion import proportion_confint  # noqa: E402

from . import agent, config, harness  # noqa: E402

SEED, B = 469, 10_000
RES = config.RESULTS_DIR
OUT = RES / "stats"
FIG = OUT / "figures"
ALL_LAYERS_TAG = "eval__" + "+".join(sorted(harness.ALL_LAYERS))
NAMES = {"oneshot": "Guess once", "retry": "Retry on error", "selfcheck": "Self-check"}
DIFFS = ["simple", "moderate", "challenging"]

# Reference palette (dataviz skill, light mode). First three categorical slots validate all-pairs.
COLORS = {"oneshot": "#2a78d6", "retry": "#eb6834", "selfcheck": "#1baf7a"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"


def style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "legend.frameon": False,
    })


def wilson(k, n):
    if n == 0:
        return (np.nan, np.nan)
    lo, hi = proportion_confint(k, n, alpha=0.05, method="wilson")
    return float(lo), float(hi)


def load_runs(folder):
    frames = []
    for c in agent.CONDITIONS:
        p = folder / f"{c}.jsonl"
        if p.exists():
            frames.append(pd.DataFrame([json.loads(l) for l in p.open(encoding="utf-8")]))
    return pd.concat(frames, ignore_index=True) if frames else None


def paired_bootstrap(wide, rng):
    """wide: DataFrame qid x condition of 0/1. Returns resampled means, shape (B, n_conditions)."""
    m = wide.to_numpy(dtype=float)
    idx = rng.integers(0, len(m), size=(B, len(m)))
    return m[idx].mean(axis=1)


def ci(a):
    return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))


def mcnemar_row(a, b, label_a, label_b):
    fixed = int((~a & b).sum())
    broken = int((a & ~b).sum())
    table = [[int((a & b).sum()), broken], [fixed, int((~a & ~b).sum())]]
    p = mcnemar(table, exact=True).pvalue if fixed + broken else 1.0
    return {"from": label_a, "to": label_b, "fixed": fixed, "broken": broken, "net": fixed - broken,
            "mcnemar_exact_p": float(p)}


# ------------------------------------------------------------------------------------------
# Part 1: accuracy
# ------------------------------------------------------------------------------------------
def accuracy_part(md):
    df = load_runs(RES / "eval")
    if df is None:
        raise SystemExit("results/eval/*.jsonl not found")
    conds = [c for c in agent.CONDITIONS if c in set(df.condition)]
    wide = df.pivot(index="qid", columns="condition", values="correct")[conds].astype(bool)
    diff_of = df.drop_duplicates("qid").set_index("qid").difficulty.reindex(wide.index)
    rng = np.random.default_rng(SEED)

    # accuracy + CI, overall and by difficulty
    acc_rows = []
    for grp in ["all"] + DIFFS:
        w = wide if grp == "all" else wide[diff_of == grp]
        bs = paired_bootstrap(w, rng)
        for j, c in enumerate(conds):
            lo, hi = ci(bs[:, j])
            acc_rows.append({"subset": grp, "condition": c, "n": len(w), "correct": int(w[c].sum()),
                             "EX": float(w[c].mean()), "ci_low": lo, "ci_high": hi})
    acc = pd.DataFrame(acc_rows)
    acc.to_csv(OUT / "accuracy.csv", index=False)

    # pairwise: difference CI (paired bootstrap) + exact McNemar + Holm
    bs = paired_bootstrap(wide, np.random.default_rng(SEED))
    pairs = [("oneshot", "retry"), ("retry", "selfcheck"), ("oneshot", "selfcheck")]
    pw = []
    for a, b in pairs:
        r = mcnemar_row(wide[a], wide[b], a, b)
        d = bs[:, conds.index(b)] - bs[:, conds.index(a)]
        r.update({"diff_EX": float(wide[b].mean() - wide[a].mean()),
                  "diff_ci_low": ci(d)[0], "diff_ci_high": ci(d)[1]})
        pw.append(r)
    pw = pd.DataFrame(pw)
    pw["holm_p"] = multipletests(pw.mcnemar_exact_p, method="holm")[1]
    pw.to_csv(OUT / "pairwise.csv", index=False)

    # cross-check against A's transitions.csv
    tr_path = RES / "eval" / "transitions.csv"
    check = "not found"
    if tr_path.exists():
        tr = pd.read_csv(tr_path)
        ok = all(int(tr[(tr["from"] == r["from"]) & (tr["to"] == r["to"])]["fixed (wrong->right)"].iloc[0]) == r["fixed"]
                 and int(tr[(tr["from"] == r["from"]) & (tr["to"] == r["to"])]["broken (right->wrong)"].iloc[0]) == r["broken"]
                 for r in pw.to_dict("records"))
        check = "matches" if ok else "DOES NOT MATCH (investigate)"

    # cost
    cost = (df.groupby("condition")
              .agg(avg_llm_calls=("n_llm_calls", "mean"), avg_tokens=("tokens", "mean"),
                   avg_latency_s=("latency_s", "mean"), median_latency_s=("latency_s", "median"))
              .reindex(conds).reset_index())
    base = cost.set_index("condition").loc[conds[0]]
    cost["tokens_x_vs_oneshot"] = cost.avg_tokens / base.avg_tokens
    cost["latency_x_vs_oneshot"] = cost.avg_latency_s / base.avg_latency_s
    cost.to_csv(OUT / "cost.csv", index=False)

    # figures
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    groups = ["all"] + DIFFS
    width = 0.26
    for j, c in enumerate(conds):
        sub = acc[acc.condition == c].set_index("subset").loc[groups]
        x = np.arange(len(groups)) + (j - 1) * width
        ax.bar(x, sub.EX * 100, width - 0.03, color=COLORS[c], label=NAMES[c], zorder=2)
        ax.errorbar(x, sub.EX * 100, yerr=[(sub.EX - sub.ci_low) * 100, (sub.ci_high - sub.EX) * 100],
                    fmt="none", ecolor=INK2, elinewidth=1, capsize=2.5, zorder=3)
    labels = [f"{g.capitalize() if g != 'all' else 'All'}\n(n={int(acc[(acc.subset == g)].n.iloc[0])})" for g in groups]
    ax.set_xticks(np.arange(len(groups)), labels)
    ax.set_ylabel("Execution accuracy (%)")
    ax.set_ylim(0, 100)
    ax.grid(axis="x", visible=False)
    ax.set_title("Accuracy by version, with 95% paired-bootstrap CIs")
    ax.legend(ncol=3, loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "accuracy.png", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.3), sharey=True)
    overall = acc[acc.subset == "all"].set_index("condition")
    for ax, (col, xlabel) in zip(axes, [("avg_tokens", "Average tokens per question"),
                                        ("avg_latency_s", "Average LLM latency per question (s)")]):
        for c in conds:
            x = float(cost.set_index("condition").loc[c, col])
            y, lo, hi = overall.loc[c, ["EX", "ci_low", "ci_high"]] * 100
            ax.errorbar([x], [y], yerr=[[y - lo], [hi - y]], fmt="o", ms=8, color=COLORS[c],
                        ecolor=COLORS[c], elinewidth=1.5, capsize=3, mec=SURFACE, mew=1.5)
            off = {"oneshot": (-8, -14), "retry": (8, 6)}.get(c, (8, 4))
            ax.annotate(NAMES[c], (x, y), xytext=off, textcoords="offset points", fontsize=9, color=INK,
                        ha="right" if off[0] < 0 else "left")
        ax.set_xlabel(xlabel)
        ax.set_xlim(0, None)
        lo_x, hi_x = ax.get_xlim()
        ax.set_xlim(0, hi_x * 1.25)
    axes[0].set_ylabel("Execution accuracy (%)")
    axes[0].set_ylim(50, 72)
    k = cost.set_index("condition")
    fig.suptitle(f"Cost vs accuracy: self-check uses {k.loc[conds[-1], 'tokens_x_vs_oneshot']:.1f}x the tokens "
                 f"of guess once (95% CIs)", x=0.02, ha="left", fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "cost_vs_accuracy.png", dpi=200)
    plt.close(fig)

    # markdown
    md.append("## Part 1: does self-correction help?\n")
    md.append(f"n = {len(wide)} questions, every version answers all of them (paired). "
              f"Fixed/broken counts {check} A's transitions.csv.\n")
    md.append("| Version | EX | 95% CI | Avg tokens | Avg LLM latency (s) |\n|---|---:|---|---:|---:|")
    for c in conds:
        o = overall.loc[c]
        k = cost.set_index("condition").loc[c]
        md.append(f"| {NAMES[c]} | {o.EX:.1%} | {o.ci_low:.1%} to {o.ci_high:.1%} | {k.avg_tokens:,.0f} "
                  f"({k.tokens_x_vs_oneshot:.2f}x) | {k.avg_latency_s:.2f} ({k.latency_x_vs_oneshot:.2f}x) |")
    md.append("\n| Comparison | Fixed | Broken | Difference in EX | 95% CI | McNemar exact p | Holm p |\n"
              "|---|---:|---:|---:|---|---:|---:|")
    for r in pw.to_dict("records"):
        md.append(f"| {NAMES[r['from']]} -> {NAMES[r['to']]} | {r['fixed']} | {r['broken']} | "
                  f"{r['diff_EX']:+.1%} | {r['diff_ci_low']:+.1%} to {r['diff_ci_high']:+.1%} | "
                  f"{r['mcnemar_exact_p']:.3f} | {r['holm_p']:.3f} |")
    md.append("")
    return wide


# ------------------------------------------------------------------------------------------
# Guardrail cost on accuracy (needs A's --layers all re-run)
# ------------------------------------------------------------------------------------------
def guardrail_cost_part(md, wide_plain):
    df = load_runs(RES / ALL_LAYERS_TAG)
    md.append("## Do the guardrails cost accuracy?\n")
    if df is None:
        md.append(f"_Not run yet: waiting for `results/{ALL_LAYERS_TAG}/` (A: `python -m src.run --split eval --layers all`)._\n")
        return
    rows = []
    for c in sorted(set(df.condition), key=agent.CONDITIONS.index):
        g = df[df.condition == c].set_index("qid").correct.astype(bool)
        common = wide_plain.index.intersection(g.index)
        a, b = wide_plain.loc[common, c], g.loc[common]
        r = mcnemar_row(a, b, f"{c} (no layers)", f"{c} (all layers)")
        bs_rng = np.random.default_rng(SEED)
        m = np.column_stack([a.to_numpy(float), b.to_numpy(float)])
        idx = bs_rng.integers(0, len(m), size=(B, len(m)))
        d = m[idx][:, :, 1].mean(1) - m[idx][:, :, 0].mean(1)
        r.update({"condition": c, "n": len(common), "EX_no_layers": float(a.mean()), "EX_all_layers": float(b.mean()),
                  "diff_ci_low": ci(d)[0], "diff_ci_high": ci(d)[1],
                  "pct_runs_with_a_block": float(df[df.condition == c].blocked.mean())})
        rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "guardrail_cost.csv", index=False)
    md.append("| Version | EX no layers | EX all layers | Fixed | Broken | 95% CI of difference | McNemar p | Runs with a block |\n"
              "|---|---:|---:|---:|---:|---|---:|---:|")
    for r in t.to_dict("records"):
        md.append(f"| {NAMES[r['condition']]} | {r['EX_no_layers']:.1%} | {r['EX_all_layers']:.1%} | {r['fixed']} | "
                  f"{r['broken']} | {r['diff_ci_low']:+.1%} to {r['diff_ci_high']:+.1%} | {r['mcnemar_exact_p']:.3f} | "
                  f"{r['pct_runs_with_a_block']:.1%} |")
    md.append("\nNote: the model is not deterministic and the prompt changes (prompt_rule is appended), so some "
              "fixed/broken pairs are run-to-run noise rather than an effect of the layers.\n")


# ------------------------------------------------------------------------------------------
# False blocks
# ------------------------------------------------------------------------------------------
def false_block_part(md):
    p = RES / "false_block" / "summary.csv"
    md.append("## False blocks on the normal questions\n")
    if not p.exists():
        md.append("_Not run yet: `python -m src.false_block`._\n")
        return
    s = pd.read_csv(p)
    s = s[s.condition == "all_versions"].copy()
    s[["ci_low", "ci_high"]] = [wilson(k, n) for k, n in zip(s.blocked, s.n)]
    s.to_csv(OUT / "false_block.csv", index=False)
    md.append("Every predicted query from the three versions (all from innocent questions) replayed through the harness.\n")
    md.append("| Layer setting | Queries | Blocked | False-block rate | Wilson 95% CI |\n|---|---:|---:|---:|---|")
    order = ["none", "allowlist", "readonly", "approval", "all"]
    for r in s.set_index("config").reindex(order).dropna(subset=["n"]).reset_index().to_dict("records"):
        md.append(f"| {r['config']} | {int(r['n'])} | {int(r['blocked'])} | {r['false_block_rate']:.2%} | "
                  f"{r['ci_low']:.2%} to {r['ci_high']:.2%} |")
    md.append("")


# ------------------------------------------------------------------------------------------
# Attacks
# ------------------------------------------------------------------------------------------
CAT_ORDER = ["destructive", "disguised_write", "escape_hatch", "exfiltration", "runaway",
             "indirect_modified", "indirect_leaked", "indirect_poisoned"]
CAT_NAMES = {"destructive": "Destructive writes", "disguised_write": "Disguised writes",
             "escape_hatch": "SQLite escape hatches", "exfiltration": "Data exfiltration (reads)",
             "runaway": "Runaway queries", "indirect_modified": "Injected: modify data",
             "indirect_leaked": "Injected: leak secrets", "indirect_poisoned": "Injected: fake answer"}


def heatmap(ax, df, configs, title):
    cats = [c for c in CAT_ORDER if c in set(df.category)]
    k = df.pivot_table(index="category", columns="config", values="success", aggfunc="sum").reindex(index=cats, columns=configs)
    n = df.pivot_table(index="category", columns="config", values="success", aggfunc="size").reindex(index=cats, columns=configs)
    rate = (k / n).to_numpy(float)
    ax.imshow(rate, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i in range(len(cats)):
        for j in range(len(configs)):
            if np.isnan(rate[i, j]):
                continue
            ax.text(j, i, f"{int(k.iloc[i, j])}/{int(n.iloc[i, j])}", ha="center", va="center", fontsize=8.5,
                    color=SURFACE if rate[i, j] > 0.55 else INK)
    ax.set_xticks(range(len(configs)), configs, rotation=0, fontsize=8.5)
    ax.set_yticks(range(len(cats)), [CAT_NAMES.get(c, c) for c in cats], fontsize=8.5)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-.5, len(configs)), minor=True)
    ax.set_yticks(np.arange(-.5, len(cats)), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="both", length=0)
    ax.set_title(title, fontsize=10)


def attack_table(df, by):
    t = df.groupby(by).success.agg(["sum", "size"]).reset_index().rename(columns={"sum": "succeeded", "size": "n"})
    t["attack_success_rate"] = t.succeeded / t.n
    t[["ci_low", "ci_high"]] = [wilson(k, n) for k, n in zip(t.succeeded, t.n)]
    return t


def attacks_part(md):
    md.append("## Attacks\n")
    p = RES / "attacks" / "direct.jsonl"
    if p.exists():
        df = pd.DataFrame([json.loads(l) for l in p.open(encoding="utf-8")])
        configs = ["none", "allowlist", "readonly_uri_only", "readonly", "approval", "all"]
        configs = [c for c in configs if c in set(df.config)]
        t = attack_table(df, ["config"]).set_index("config").reindex(configs).reset_index()
        t.to_csv(OUT / "attacks_direct.csv", index=False)
        attack_table(df, ["config", "category"]).to_csv(OUT / "attacks_direct_by_category.csv", index=False)
        n_att = df.attack_id.nunique()
        fig, ax = plt.subplots(figsize=(7.6, 3.4))
        heatmap(ax, df, configs, "")
        fig.suptitle(f"Direct SQL attacks that succeeded, by layer ({n_att} payloads, no LLM)",
                     x=0.01, ha="left", fontsize=10.5, fontweight="bold")
        fig.tight_layout()
        fig.savefig(FIG / "attacks_direct.png", dpi=200)
        plt.close(fig)
        md.append(f"### Direct SQL ({n_att} payloads, each run on a fresh copy, no LLM)\n")
        md.append("| Layer setting | Succeeded | Attack success rate | Wilson 95% CI |\n|---|---:|---:|---|")
        for r in t.to_dict("records"):
            md.append(f"| {r['config']} | {r['succeeded']}/{r['n']} | {r['attack_success_rate']:.0%} | "
                      f"{r['ci_low']:.0%} to {r['ci_high']:.0%} |")
        md.append("")
    else:
        md.append("_Direct tier not run yet: `python -m src.attacks --tier direct`._\n")

    p = RES / "attacks" / "agent.jsonl"
    if p.exists():
        df = pd.DataFrame([json.loads(l) for l in p.open(encoding="utf-8")])
        model = ", ".join(sorted(set(df.model)))
        configs = [c for c in ["none", "prompt_rule", "allowlist", "readonly", "approval", "all"] if c in set(df.config)]
        t = attack_table(df, ["condition", "config"])
        t["_c"] = t.condition.map(agent.CONDITIONS.index)
        t["_k"] = t.config.map(configs.index)
        t = t.sort_values(["_c", "_k"]).drop(columns=["_c", "_k"])
        t.to_csv(OUT / "attacks_agent.csv", index=False)
        attack_table(df, ["condition", "config", "category"]).to_csv(OUT / "attacks_agent_by_category.csv", index=False)
        conds = [c for c in agent.CONDITIONS if c in set(df.condition)]
        fig, axes = plt.subplots(1, len(conds), figsize=(10, 3.6), sharey=True)
        axes = np.atleast_1d(axes)
        for ax, c in zip(axes, conds):
            heatmap(ax, df[df.condition == c], configs, NAMES[c])
            ax.tick_params(axis="x", labelrotation=30)
        fig.suptitle(f"Agent attacks that succeeded, by layer (model: {model})", x=0.01, ha="left",
                     fontweight="bold", fontsize=10.5)
        fig.tight_layout()
        fig.savefig(FIG / "attacks_agent.png", dpi=200)
        plt.close(fig)
        md.append(f"### Through the agent (model: {model}; {df.attack_id.nunique()} scenarios)\n")
        if "mock" in model:
            md.append("**WARNING: these numbers come from the scripted mock model, not a real LLM. Do not report them.**\n")
        md.append("| Version | Layer setting | Succeeded | Rate | Wilson 95% CI |\n|---|---|---:|---:|---|")
        for r in t.to_dict("records"):
            md.append(f"| {NAMES[r['condition']]} | {r['config']} | {r['succeeded']}/{r['n']} | "
                      f"{r['attack_success_rate']:.0%} | {r['ci_low']:.0%} to {r['ci_high']:.0%} |")
        # oneshot vs selfcheck with no layers, paired by scenario (one pair per scenario keeps them independent)
        if {"oneshot", "selfcheck"} <= set(df.condition) and "none" in configs:
            w = df[df.config == "none"].pivot_table(index="attack_id", columns="condition", values="success",
                                                    aggfunc="first")
            r = mcnemar_row(w["oneshot"].astype(bool), w["selfcheck"].astype(bool), "oneshot", "selfcheck")
            md.append(f"\nNo layers, guess once vs self-check, paired by scenario (n = {len(w)}): {r['fixed']} "
                      f"attacks succeeded only against self-check, {r['broken']} only against guess once "
                      f"(exact McNemar p = {r['mcnemar_exact_p']:.3g}). Guess once never sees the data, so "
                      f"indirect injection cannot reach it by construction.\n")
    else:
        md.append("_Agent tier not run yet: `python -m src.attacks --tier agent` (needs the API key)._\n")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    style()
    md = ["# Stats and figures (generated by `python -m src.stats`)\n",
          "Methods: paired bootstrap (10,000 resamples of questions, seed 469, 95% percentile interval) for "
          "accuracy and differences; exact McNemar test on fixed/broken pairs with Holm correction across the three "
          "comparisons; Wilson 95% intervals for attack-success and false-block rates.\n"]
    wide = accuracy_part(md)
    guardrail_cost_part(md, wide)
    false_block_part(md)
    attacks_part(md)
    (OUT / "stats.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\nwrote {OUT}/*.csv, {FIG}/*.png, {OUT / 'stats.md'}")


if __name__ == "__main__":
    main()
