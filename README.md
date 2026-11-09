# Self-correcting Text-to-SQL agent with a guardrailed harness

> Working with Claude Code? Project context, decisions and status are in `CLAUDE.md`.

IS469 team project. **A** owns the agent and the accuracy results (`src/agent.py`, `src/scorer.py`, `src/run.py`, `src/summarize.py`).
**B** owns the guardrail harness and the attack suite (`src/harness.py` + whatever B adds), plus the stats and plots.

## What's here

| File | What it does |
|---|---|
| `src/agent.py` | The agent: three versions (`oneshot`, `retry`, `selfcheck`) with the same budget of 4 LLM calls. **The prompts you tune are at the top.** |
| `src/harness.py` | **Stand-in** for B's harness. B replaces the body of `execute()` (see `docs/HARNESS_INTERFACE.md`). |
| `src/scorer.py` | Execution accuracy (the official BIRD metric: same set of result rows as the gold query). |
| `src/run.py` | Runs a version on a split and logs one JSON line per question to `results/`. Resumable. |
| `src/summarize.py` | Accuracy/cost table, fixed-vs-broken counts, and a failures sheet for error analysis. |
| `src/llm.py` | Works with any OpenAI-compatible API. Caches every call on disk, so re-runs are free. |
| `src/data.py` | Fixed split: **pilot = 30** questions (tune on these only), **eval = 300** (report on these). |
| `tests/make_fake_dbs.py` | Empty copies of the databases for testing before the real download finishes. |
| `data/mini_dev_prompt.jsonl` | The 500 BIRD mini-dev questions with schema, hints and gold SQL (from github.com/bird-bench/mini_dev, CC BY-SA 4.0). |

## Setup (do this together on the call)

**1. Install** (Python 3.10+)
```bash
pip install -r requirements.txt
```

**2. Get the databases.** Download `minidev.zip` from the BIRD mini-dev page (github.com/bird-bench/mini_dev):
Alibaba mirror `https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip`, or the Google Drive / Hugging Face links in that README.
Unzip it and find the folder that contains `california_schools/`, `card_games/`, … (usually `MINIDEV/dev_databases`).

**3. Configure.** Copy `.env.example` to `.env`, then set `DB_ROOT` to that folder and fill in your API details.

**4. Check everything works.**
```bash
python -m src.check_setup
```
You want 11 `[ok]` databases, a gold query that returns rows, and the LLM replying `pong`.

> No API key or databases yet? `python tests/make_fake_dbs.py`, then set `DB_ROOT=data/fake_databases` and `LLM_MODEL=mock`, and run everything below. The numbers will be meaningless, but you can confirm the pipeline works.

## Workflow for A

**Smoke test (on the call):**
```bash
python -m src.run --split pilot --limit 20 --condition oneshot
```

**Tune on the pilot set only (until about 17:00):**
```bash
python -m src.run --split pilot            # all three versions on the 30 pilot questions
python -m src.summarize --split pilot      # table + results/pilot/failures.csv
```
Open `failures.csv`, read the wrong ones, edit the prompts at the top of `src/agent.py`, then delete `results/pilot/` and run again.
Old LLM calls stay cached; only the changed prompts cost anything. Typical BIRD mistakes to look for:
- extra columns in the SELECT (BIRD marks it wrong);
- integer division (needs `CAST(x AS REAL)`);
- ignoring the evidence hint;
- wrong value spelling or case.

**17:00: freeze the prompts.** Commit them. From here on, don't change `src/agent.py` prompts.

**Full run:**
```bash
python -m src.run --split eval --workers 8          # ~300 questions x 3 versions
python -m src.summarize --split eval
```
Hit a rate limit? Lower `--workers`. Crashed? Just rerun the same command: finished questions are skipped.
Rough size: ~1.7k tokens per first attempt, about 2–3M tokens in total for all three versions (the first attempt is shared through the cache).

**Error analysis:** fill in the `error_category` column of `results/eval/failures.csv`. For example: `schema-linking`, `value-spelling`, `extra-columns`, `aggregation`, `join`, `hint-ignored`, `gold-questionable`.
`transitions.csv` already tells you how many questions each step fixed and broke.

**With B's guardrails switched on** (to show whether the guardrails cost accuracy):
```bash
python -m src.run --split eval --layers all
python -m src.summarize --split eval__allowlist+approval+prompt_rule+readonly
```

## Results format (B reads these for stats and plots)
`results/<split>[__<layers>]/<condition>.jsonl`: one line per question with
`qid, db_id, difficulty, condition, layers, model, question, gold_sql, pred_sql, correct, blocked,
n_llm_calls, n_retries, n_exec, prompt_tokens, completion_tokens, tokens, latency_s, stop_reason, final_exec_ok, trajectory`.
Every version answers the same questions, so pair them on `qid` (McNemar uses the fixed/broken counts from `transitions.csv`).
