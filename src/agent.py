"""The Text-to-SQL agent: three versions with the same LLM-call budget.

  oneshot   : write SQL once. Executed only so we can log it; no feedback.
  retry     : execute -> if it errors (or is blocked), show the error and ask for a fix. Repeat.
  selfcheck : retry, PLUS after a successful run show the model the result rows and ask it to
              check whether they really answer the question ("OK" or a corrected query).

retry and selfcheck both get MAX_LLM_CALLS calls in total (default 4 = first try + 3 more).
The first turn is IDENTICAL across all three versions, so the first attempt is shared (cached).

Final answer = the last query that executed successfully (falls back to the last query written).
"""
import re
import time
from dataclasses import dataclass, field, asdict

from . import config, harness, llm

CONDITIONS = ("oneshot", "retry", "selfcheck")

SYSTEM_PROMPT = (
    "You are an expert data analyst who writes SQLite queries.\n"
    "Answer the user's question with ONE SQLite SELECT query over the given schema.\n"
    "- Use only tables and columns that exist in the schema; quote names with spaces using backticks.\n"
    "- Use the external knowledge hints: they define terms and formulas used in the question.\n"
    "- Return only the columns the question asks for, nothing extra.\n"
    "Reply with the final query in a single ```sql code block."
)

FIRST_TURN = (
    "Database schema:\n{schema}\n\n"
    "External knowledge: {evidence}\n\n"
    "Question: {question}\n\n"
    "Write the SQLite query."
)

ERROR_FEEDBACK = (
    "The query failed with this error:\n{error}\n\n"
    "Fix the query. Reply with the corrected query in a single ```sql code block."
)

BLOCKED_FEEDBACK = (
    "The query was blocked by the database safety layer: {reason}\n\n"
    "Only read-only SELECT queries are allowed. Reply with a query in a single ```sql code block."
)

SELFCHECK_PROMPT = (
    "The query ran successfully and returned {n_rows} row(s){trunc}. Columns: {columns}\n"
    "First rows:\n{preview}\n{warnings}\n"
    "Check carefully whether this result correctly answers the question: the right columns "
    "(only what was asked), filters and exact value spellings, joins, aggregation, and handling "
    "of NULLs and duplicates.\n"
    "If it is correct, reply with exactly: OK\n"
    "Otherwise reply with the corrected query in a single ```sql code block."
)


@dataclass
class AgentResult:
    final_sql: str
    n_llm_calls: int = 0
    n_exec: int = 0
    n_retries: int = 0             # LLM calls after the first one
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_latency_s: float = 0.0     # sum of original (uncached) LLM latencies
    wall_s: float = 0.0
    any_blocked: bool = False
    final_exec_ok: bool = False
    stop_reason: str = ""
    trajectory: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def extract_sql(text: str) -> str:
    blocks = re.findall(r"```(?:sql|sqlite)?\s*\n?(.*?)```", text, flags=re.S | re.I)
    if blocks:
        return blocks[-1].strip()
    m = re.search(r"\b(WITH|SELECT)\b.*", text, flags=re.S | re.I)
    return (m.group(0) if m else text).strip()


def _preview(res, n=config.OBS_ROWS, width=60):
    lines = []
    for row in (res.rows or [])[:n]:
        lines.append(" | ".join(str(v)[:width] for v in row))
    return "\n".join(lines) if lines else "(no rows)"


def _warnings(res):
    w = []
    if res.n_rows == 0:
        w.append("Warning: the result is EMPTY.")
    elif res.rows and all(all(v is None for v in row) for row in res.rows[: config.OBS_ROWS]):
        w.append("Warning: the shown rows contain only NULLs.")
    return ("\n".join(w) + "\n") if w else ""


def _obs(res):
    """Short version of an execution result for the trajectory log."""
    return {"ok": res.ok, "n_rows": res.n_rows, "error": res.error, "blocked": res.blocked,
            "block_reason": res.block_reason, "blocked_by": res.blocked_by,
            "preview": (res.rows or [])[:3]}


def solve(item: dict, condition: str, db_path, layers=frozenset()) -> AgentResult:
    """Run one question. `item` needs keys: question, evidence, schema."""
    assert condition in CONDITIONS, condition
    t0 = time.time()
    system = SYSTEM_PROMPT + ("\n\n" + harness.PROMPT_RULE if "prompt_rule" in layers else "")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": FIRST_TURN.format(
            schema=item["schema"], evidence=item.get("evidence") or "(none)", question=item["question"])},
    ]
    out = AgentResult(final_sql="")
    budget = 1 if condition == "oneshot" else config.MAX_LLM_CALLS
    last_ok_sql, last_sql = None, ""

    while True:
        reply = llm.chat(messages)
        out.n_llm_calls += 1
        out.prompt_tokens += reply.prompt_tokens
        out.completion_tokens += reply.completion_tokens
        out.llm_latency_s += reply.latency_s
        messages.append({"role": "assistant", "content": reply.text})
        step = {"turn": out.n_llm_calls, "reply": reply.text}

        # Self-check said the previous result is fine -> done.
        if out.n_llm_calls > 1 and reply.text.strip().upper().rstrip(".") == "OK":
            step["action"] = "accept"
            out.trajectory.append(step)
            out.stop_reason = "selfcheck_ok"
            break

        sql = extract_sql(reply.text)
        last_sql = sql
        res = harness.execute(sql, db_path, layers=layers)
        out.n_exec += 1
        step.update(action="execute", sql=sql, obs=_obs(res))
        out.trajectory.append(step)
        out.any_blocked |= res.blocked
        if res.ok:
            last_ok_sql = sql

        if condition == "oneshot":
            out.stop_reason = "oneshot"
            break
        if out.n_llm_calls >= budget:
            out.stop_reason = "budget"
            break

        if res.blocked:
            feedback = BLOCKED_FEEDBACK.format(reason=res.block_reason)
        elif not res.ok:
            feedback = ERROR_FEEDBACK.format(error=res.error)
        elif condition == "selfcheck":
            feedback = SELFCHECK_PROMPT.format(
                n_rows=res.n_rows, trunc=" (truncated)" if res.truncated else "",
                columns=", ".join(res.columns or []), preview=_preview(res), warnings=_warnings(res))
        else:  # retry + success -> done
            out.stop_reason = "exec_ok"
            break
        messages.append({"role": "user", "content": feedback})

    out.final_sql = last_ok_sql if last_ok_sql is not None else last_sql
    out.final_exec_ok = last_ok_sql is not None
    out.n_retries = out.n_llm_calls - 1
    out.wall_s = time.time() - t0
    return out
