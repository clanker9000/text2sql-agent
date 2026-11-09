"""Execution accuracy (EX), the official BIRD metric: the predicted query is correct if it returns
the same SET of rows as the gold query (column order inside a row matters, row order doesn't).

This runs on its own read-only connection, independent of the guardrail harness, so the
score never depends on what B's layers do.
"""
import sqlite3
import threading
import time

_gold_cache = {}
_lock = threading.Lock()


def _run(sql, db_path, timeout_s):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    deadline = time.time() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10_000)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def gold_rows(item, db_path, timeout_s=120):
    qid = item["question_id"]
    with _lock:
        if qid in _gold_cache:
            return _gold_cache[qid]
    rows = _run(item["SQL"], db_path, timeout_s)
    with _lock:
        _gold_cache[qid] = rows
    return rows


def score(item, pred_sql, db_path, timeout_s=60):
    """Returns (correct: bool, error: str | None)."""
    try:
        gold = gold_rows(item, db_path)
    except Exception as e:
        return False, f"GOLD_FAILED: {e}"
    try:
        pred = _run(pred_sql, db_path, timeout_s)
    except Exception as e:
        return False, "timeout" if "interrupted" in str(e) else str(e)
    return set(pred) == set(gold), None
