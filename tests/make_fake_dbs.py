"""Build EMPTY copies of the 11 BIRD databases from the CREATE TABLE statements in the question
file. Useful for testing the pipeline (and for B to develop the harness) before the real
download finishes. Every query returns zero rows, so accuracy numbers on these are meaningless.

  python tests/make_fake_dbs.py            -> data/fake_databases/<db_id>/<db_id>.sqlite
  DB_ROOT=data/fake_databases python -m src.run --split pilot --limit 5
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
out_root = ROOT / "data" / "fake_databases"

schemas = {}
for line in open(ROOT / "data" / "mini_dev_prompt.jsonl", encoding="utf-8"):
    r = json.loads(line)
    schemas.setdefault(r["db_id"], r["schema"])

for db_id, schema in schemas.items():
    p = out_root / db_id / f"{db_id}.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    conn = sqlite3.connect(p)
    for stmt in re.findall(r"CREATE TABLE.*?\n\);", schema, flags=re.S):
        stmt = re.sub(r"--[^\n]*", "", stmt)                   # drop the example-value comments
        stmt = re.sub(r",\s*\)\s*;\s*$", "\n);", stmt)          # trailing comma left behind
        stmt = re.sub(r",\s*FOREIGN KEY[^\n]*", "", stmt)       # FKs not needed for testing
        try:
            conn.execute(stmt)
        except sqlite3.Error as e:
            print(f"[warn] {db_id}: {e}\n{stmt[:200]}", file=sys.stderr)
    conn.commit()
    n = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    conn.close()
    print(f"{db_id}: {n} tables")
