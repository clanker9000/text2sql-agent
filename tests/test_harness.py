"""Checks for the guardrail harness. No API key and no BIRD download needed.

  python tests/test_harness.py
"""
import dataclasses
import inspect
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config, harness  # noqa: E402

tmp = Path(tempfile.mkdtemp())
config.DB_ROOT = tmp / "real"                      # stands in for the BIRD folder
harness.SCRATCH_ROOT = (tmp / "scratch").resolve()


def make_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, isolation_level=None)
    c.execute("CREATE TABLE member (id INTEGER, name TEXT)")
    c.executemany("INSERT INTO member VALUES (?, ?)", [(1, "Ann"), (2, "Bo")])
    c.close()
    return path


def digest(p):
    return Path(p).read_bytes()


real = make_db(config.DB_ROOT / "club" / "club.sqlite")
fails = 0


def check(name, cond):
    global fails
    print(("[ok]   " if cond else "[FAIL] ") + name)
    fails += not cond


# 1. The contract with the agent is unchanged
check("execute() signature unchanged",
      list(inspect.signature(harness.execute).parameters) == ["sql", "db_path", "layers", "timeout_s", "max_rows"])
check("ExecResult fields unchanged",
      [f.name for f in dataclasses.fields(harness.ExecResult)] ==
      ["ok", "rows", "columns", "n_rows", "truncated", "error", "blocked", "block_reason", "blocked_by",
       "elapsed_s", "extra"])
check("ALL_LAYERS unchanged", harness.ALL_LAYERS == {"prompt_rule", "allowlist", "readonly", "approval"})

# 2. Normal reads work under every setting
for layers in [set(), {"allowlist"}, {"readonly"}, {"approval"}, set(harness.ALL_LAYERS)]:
    r = harness.execute("SELECT name FROM member ORDER BY id", real, layers=layers)
    check(f"SELECT works with layers={sorted(layers)}", r.ok and r.rows == [("Ann",), ("Bo",)] and not r.blocked)

# 3. Safety net: the real database is never writable, even with no layers
before = digest(real)
for sql in ["DELETE FROM member", "DROP TABLE member", "PRAGMA user_version = 7",
            f"VACUUM INTO '{(tmp / 'copy.db').as_posix()}'", f"ATTACH '{(tmp / 'side.db').as_posix()}' AS s"]:
    r = harness.execute(sql, real)
    check(f"real DB, no layers, refused: {sql[:30]}", not r.ok and not r.blocked and r.error)
check("real DB file unchanged", digest(real) == before)
check("no files written next to the real DB", not (tmp / "copy.db").exists() and not (tmp / "side.db").exists())

# 4. Scratch copies are writable with no layers (that is the L0 baseline for attacks)
scratch = harness.SCRATCH_ROOT / "t" / "club.sqlite"
scratch.parent.mkdir(parents=True)


def fresh():
    shutil.copyfile(real, scratch)
    return scratch


r = harness.execute("DELETE FROM member", fresh())
check("scratch, no layers: DELETE goes through", r.ok and
      sqlite3.connect(scratch).execute("SELECT count(*) FROM member").fetchone()[0] == 0)

# 5. Each layer blocks a write on a scratch copy, and says which layer did it
for layer in ["allowlist", "readonly", "approval"]:
    r = harness.execute("DELETE FROM member", fresh(), layers={layer})
    n = sqlite3.connect(scratch).execute("SELECT count(*) FROM member").fetchone()[0]
    check(f"{layer} blocks DELETE (blocked_by={r.blocked_by})", r.blocked and r.blocked_by == layer and n == 2)

# 6. Allowlist details
for sql, allowed in [("SELECT 1", True), ("WITH a AS (SELECT 1) SELECT * FROM a", True),
                     ("SELECT 1 UNION SELECT 2", True), ("SELECT `name` FROM member -- note", True),
                     ("SELECT 1; DROP TABLE member", False), ("WITH a AS (SELECT 1) DELETE FROM member", False),
                     ("PRAGMA writable_schema = ON", False), ("ATTACH 'x.db' AS x", False),
                     ("VACUUM INTO 'x.db'", False), ("SELECT load_extension('x')", False), ("", False)]:
    check(f"allowlist {'allows' if allowed else 'rejects'}: {sql[:40]!r}",
          (harness.allowlist_check(sql) is None) == allowed)

# 7. readonly needs query_only: mode=ro alone lets VACUUM INTO copy the database
out1, out2 = harness.SCRATCH_ROOT / "t" / "v1.db", harness.SCRATCH_ROOT / "t" / "v2.db"
harness.execute(f"VACUUM INTO '{out1.as_posix()}'", fresh(), layers={"readonly_uri_only"})
r = harness.execute(f"VACUUM INTO '{out2.as_posix()}'", fresh(), layers={"readonly"})
check("ablation: mode=ro alone lets VACUUM INTO copy the DB", out1.exists() and out1.stat().st_size > 0)
check("readonly (mode=ro + query_only) blocks VACUUM INTO",
      r.blocked and (not out2.exists() or out2.stat().st_size == 0))

# 8. Approval logs its decision; runaway query is stopped by the timeout
n_log = len(harness.APPROVAL_LOG)
harness.execute("UPDATE member SET name = 'X'", fresh(), layers={"approval"})
check("approval decision logged as denied", len(harness.APPROVAL_LOG) == n_log + 1
      and harness.APPROVAL_LOG[-1]["decision"] == "denied")
r = harness.execute("WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM r) SELECT count(*) FROM r",
                    real, timeout_s=1)
check("runaway query stopped by timeout", not r.ok and r.extra.get("timed_out"))

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'All checks passed.' if not fails else f'{fails} check(s) FAILED.'}")
sys.exit(1 if fails else 0)
