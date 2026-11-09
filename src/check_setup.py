"""Run this first: python -m src.check_setup
Checks the question file, the 11 database files, the gold queries and one real LLM call."""
from . import config, data, llm, scorer

ok = True
items = data.load_all()
print(f"[ok] {len(items)} questions loaded")
s = data.splits()
print(f"[ok] split sizes: pilot={len(s['pilot'])} eval={len(s['eval'])}")

for db_id in sorted({r["db_id"] for r in items}):
    p = data.db_path(db_id)
    if p.exists():
        print(f"[ok] {db_id}: {p.stat().st_size / 1e6:.0f} MB")
    else:
        ok = False
        print(f"[MISSING] {p}")

if ok:
    first = s["pilot"][0]
    rows = scorer.gold_rows(first, data.db_path(first["db_id"]))
    print(f"[ok] gold query for qid {first['question_id']} returned {len(rows)} rows")

print(f"\nmodel = {config.LLM_MODEL}  base_url = {config.LLM_BASE_URL or 'api.openai.com'}")
if config.LLM_MODEL != "mock":
    r = llm._call_api([{"role": "user", "content": "Reply with the single word: pong"}])
    print(f"[ok] LLM replied {r.text.strip()!r} in {r.latency_s:.1f}s ({r.prompt_tokens}+{r.completion_tokens} tokens)")
print("\nAll good." if ok else "\nFix the MISSING items above (see README, step 2).")
