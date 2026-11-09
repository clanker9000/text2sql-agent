# Project overview

IS469 team project (2 people: **A** = agent and accuracy, **B** = harness and safety).
**Deadline: Tue 10 Nov 2026, 12:00 SGT** (internal target 07:00, the rest is buffer).
Deliverables: written report, group presentation, code.

How to install and run things is in the [README](../README.md). This file explains *what* we are doing and *why*.

## The idea in one sentence

We built an AI agent that answers plain-English questions about a database by writing SQL, and we test
(1) whether letting it check its own work makes it more accurate, and (2) whether guardrails can stop it
from damaging the database, and what they cost in accuracy.

## The problem

Data lives in databases, and getting answers out means writing SQL, which most people can't do. An LLM can
translate a question into SQL:

> "What is the highest monthly consumption in 2012?"
> → `SELECT SUM(Consumption) FROM yearmonth WHERE SUBSTR(Date,1,4)='2012' GROUP BY SUBSTR(Date,5,2) ORDER BY 1 DESC LIMIT 1`

But LLMs make mistakes. Sometimes the SQL crashes; more often it runs fine and returns the wrong answer.
And an agent that can run SQL could also run *harmful* SQL (`DELETE`, `DROP TABLE`), for example if someone hides
instructions inside the data it reads.

## Part 1 (A): does self-correction help?

Three versions of the agent answer the same questions. They have the **same budget** (at most 4 LLM calls) and
the **same first turn**, so the comparison is fair and the first attempt is shared through the cache.

| Version | Plain English | What it does |
|---|---|---|
| `oneshot` | **Guess once** | Writes the SQL once. |
| `retry` | **Try again if it crashes** | Runs the SQL; if it errors, shows the error to the model and asks for a fix (up to 3 more tries). |
| `selfcheck` | **Double-check the answer** | Like retry, but also shows the model the result rows and asks "does this really answer the question?" The model replies `OK` or a corrected query. |

The loop is a **fixed policy**: the code always executes the query and decides when to give feedback. That keeps
the three versions comparable. It is still an agent in the course's sense: loop, tool use (execution),
observation, self-correction (Reflexion-style).

**Final answer** = the last query that executed successfully (or the last query written, if none ran).

## Part 2 (B): is it safe?

Four guardrail layers, tested one at a time and stacked:

| Layer | Plain English | What it does |
|---|---|---|
| `prompt_rule` | **Ask nicely** | The system prompt tells the model to only read data and ignore instructions inside the data. |
| `allowlist` | **The bouncer** | Parse the SQL (sqlglot) and only allow a single `SELECT` / `WITH` statement. |
| `readonly` | **The locked door** | Open the database read-only (sqlite `mode=ro`). |
| `approval` | **Ask a human** | Any write needs human approval (auto-denied in experiments). |

They are tested against ~40 attacks, including **indirect injection** (malicious instructions hidden in table cells,
which the agent sees during self-check). The contract between the agent and the harness is in
[HARNESS_INTERFACE.md](HARNESS_INTERFACE.md).

## Data

**BIRD mini-dev**: 500 questions over 11 real-world SQLite databases (schools, football, cards, finance, …), each
with a hint ("evidence"), an official gold SQL query and a difficulty level. We chose BIRD over Spider because it
is harder, so self-correction has something to fix.

Fixed, stratified split (seed 469, same for everyone):
- **pilot (30 questions):** the only questions we look at while tuning prompts;
- **eval (300 questions):** the questions we report on. Never tune on these.

## What we measure

| Metric | Plain English |
|---|---|
| **Execution accuracy (EX)** | "Did it get the right answer?" Run our SQL and the gold SQL; correct if they return the same set of rows (official BIRD metric). A programmatic check, no LLM judge. |
| Tokens, latency, LLM calls, retries per question | What the extra steps cost |
| **Block rate** (on the attacks) | How many attacks each layer stops |
| **False-block rate** (on the 300 normal questions) | "How often the bouncer turns away innocent people" |
| Paired stats (McNemar / paired bootstrap) | Is a difference real or luck? Every version answers the same questions, so results are paired by question. |

Key questions for the report:
1. Does *retry* beat *oneshot*, and does *selfcheck* beat *retry*? At what cost ("N× tokens for +X points")?
2. What does retrying fix, and what does it never fix (error analysis)?
3. Do the guardrails cost accuracy? (Run the eval with all layers on and compare.)

Course topics covered: **Topic 7** (agent loop, harness, guardrails, self-correction) and **Topics 5–6**
(automatic evaluation: "verify first, judge last", with EX as a programmatic check).

## Rules we agreed on

1. **Tune prompts on pilot only.** Never look at eval results while tuning.
2. **Prompt freeze at the 17:00 sync:** after that, no prompt changes in `src/agent.py`. The frozen prompts are
   committed and tagged `prompts-frozen`. If a change is unavoidable, all three versions are re-run on eval and
   the earlier numbers are void.
3. Keep `harness.execute()`'s signature and the `ExecResult` fields stable (the agent depends on them).
4. Keep the three versions on the same budget and the same first turn.
5. Never commit `.env` or the databases. Don't delete `cache/` (it holds paid API calls).
6. Report honestly. If a gold query fails, exclude that question and report the count. If selfcheck doesn't
   beat retry, that is a valid finding.
7. Keep it simple. Dropped on purpose: Spider, a retrieval / value-lookup tool (stretch goal only), and a
   local-model comparison.

## Work split

**A: agent and accuracy**
- Agent loop for all three versions, prompts, accuracy scorer (`src/agent.py`, `scorer.py`, `run.py`, `summarize.py`, `llm.py`, `data.py`)
- Accuracy runs on pilot and eval, error analysis
- Report: agent design, experimental setup, accuracy results
- Presentation: first half

**B: harness and safety**
- The four guardrail layers in `src/harness.py` (currently a stand-in that always opens read-only) and the attack suite
- Block and false-block tests
- **All stats and plots, for both parts** (inputs: `results/<split>/*.jsonl` and `transitions.csv`)
- Report: harness design, safety results, stats method
- Presentation: second half, plus a live attack demo

**Together:** report intro, discussion ("do the guardrails cost accuracy?"), conclusion.

## Timeline (SGT)

| When | What |
|---|---|
| Mon 13:30–17:00 | A tunes prompts on the pilot · B builds the layers and attacks |
| **Mon 17:00** | Sync: swap in B's `harness.py`, re-run the pilot, **freeze prompts** |
| Mon 17:30–21:00 | Full eval: 3 versions × 300, then `--layers all`. B: attacks + stats from A's results |
| Mon 21:00–01:00 | A: error analysis, report sections, slides · B: same for the safety part |
| Tue 05:00–07:00 | Merge report and slides, rehearse, submit (07:00–12:00 = buffer) |

## Setup notes

- **Model:** OpenAI `gpt-6-luna`. It is a reasoning model, so in `.env` leave `LLM_TEMPERATURE=` **empty**
  (it rejects 0). The code sends `max_completion_tokens` (default 4096, since the model spends part of the limit
  thinking). Every reply is cached, so re-runs are reproducible and free even though the model isn't deterministic.
- **Gold queries:** pilot question 701's gold query never finishes, so it is excluded (`GOLD_FAILED`). Eval question
  518's gold query takes ~155 s (the gold timeout is 300 s). All other 328 pilot/eval gold queries run fine.
- **Windows:** all file reads use UTF-8 explicitly; without that, Python on Windows fails to read the question file.
