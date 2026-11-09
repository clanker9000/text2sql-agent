# Harness interface (for B)

The agent calls exactly one function. Keep its signature and the `ExecResult` fields as they are;
add anything else you like (helper modules, extra fields in `extra`).

```python
# src/harness.py
def execute(sql: str, db_path, layers=frozenset(), timeout_s=30.0, max_rows=1000) -> ExecResult
```

| `ExecResult` field | Meaning |
|---|---|
| `ok` | query ran (zero rows still counts as ok) |
| `rows`, `columns`, `n_rows`, `truncated` | the result, capped at `max_rows` |
| `error` | SQL/runtime error message when it failed |
| `blocked` | **a guardrail stopped it** (set this instead of `error`, so blocks and SQL errors stay separate) |
| `block_reason` | short human-readable reason; the agent shows this text to the model |
| `blocked_by` | `"allowlist"`, `"readonly"` or `"approval"` |

## Layers (`layers` is any subset of these names)
- `prompt_rule`: already wired in. When present, the agent appends `harness.PROMPT_RULE` to its system prompt. You own the wording of that constant.
- `allowlist`: parse with `sqlglot` and allow only a single `SELECT`/`WITH` statement. Watch for stacked statements, comments, `PRAGMA` and `ATTACH`.
- `readonly`: open with `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)`. Turn the "attempt to write a readonly database" error into `blocked=True, blocked_by="readonly"`.
- `approval`: anything that isn't a plain read needs human approval. In experiments, auto-deny and log it. For the live demo, an `input("Approve? y/n")` prompt is fine.

**Important:** the current stub always opens read-only, so A's runs can never damage the real files.
For the L0 (no guard) attack runs, run against a **scratch copy** of the database, opened read-write, and reset it after each attack.

## Running the agent on your attacks
```python
from src import agent
res = agent.solve({"question": "...", "evidence": "", "schema": item["schema"]},
                  condition="selfcheck", db_path=scratch_copy, layers=frozenset({"allowlist"}))
res.any_blocked, res.final_sql, res.trajectory   # what happened
```
For indirect injection, put the malicious text into a cell of the scratch copy (for example a `Description` column).
The agent will see it in the result preview during self-check.

## False-block rate
Re-run A's eval questions with layers switched on (`python -m src.run --split eval --layers allowlist`),
or replay the `pred_sql` values from A's `results/eval/*.jsonl` through `execute()` and count `blocked`.
You can develop without the real databases first: `python tests/make_fake_dbs.py` builds empty copies.
