"""One function, chat(messages) -> LLMReply, for any OpenAI-compatible API.

Every call is cached on disk (keyed by model + messages + temperature), so:
  * re-running an experiment costs nothing,
  * the first attempt of `retry` and `selfcheck` reuses the `oneshot` call (identical prompt),
    which makes the three conditions properly paired and saves ~1/3 of the cost.
Cached replies keep their original token counts and latency, so reported numbers stay honest.
"""
import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass

from . import config


@dataclass
class LLMReply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    cached: bool = False


class _Cache:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
        self.lock = threading.Lock()

    def get(self, k):
        with self.lock:
            row = self.conn.execute("SELECT v FROM c WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, k, v):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO c VALUES (?,?)", (k, json.dumps(v)))
            self.conn.commit()


_cache = _Cache(config.CACHE_DB)
_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY or "none")
    return _client


def _call_api(messages):
    kwargs = dict(model=config.LLM_MODEL, messages=messages, max_tokens=config.LLM_MAX_TOKENS)
    if config.LLM_TEMPERATURE is not None:
        kwargs["temperature"] = config.LLM_TEMPERATURE
    delay = 2
    for attempt in range(6):
        try:
            t0 = time.time()
            r = _get_client().chat.completions.create(**kwargs)
            u = r.usage
            return LLMReply(
                text=r.choices[0].message.content or "",
                prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                latency_s=time.time() - t0,
            )
        except Exception as e:  # rate limits, timeouts, 5xx -> back off and retry
            if attempt == 5:
                raise
            print(f"[llm] {type(e).__name__}: {str(e)[:120]} -> retry in {delay}s")
            time.sleep(delay)
            delay *= 2


def chat(messages) -> LLMReply:
    key = hashlib.sha256(
        json.dumps([config.LLM_MODEL, config.LLM_TEMPERATURE, messages], sort_keys=True).encode()
    ).hexdigest()
    hit = _cache.get(key)
    if hit:
        return LLMReply(**hit, cached=True)
    reply = _mock(messages) if config.LLM_MODEL == "mock" else _call_api(messages)
    _cache.put(key, {k: v for k, v in reply.__dict__.items() if k != "cached"})
    return reply


# ---------------------------------------------------------------------------
# Mock model: lets you test the whole pipeline with no API key.
# First attempt is deliberately broken for ~1/3 of questions; after error feedback it returns
# the gold SQL; self-check always says OK.
# ---------------------------------------------------------------------------
_gold = None


def _mock(messages):
    global _gold
    if _gold is None:
        from .data import load_all
        _gold = {r["question"].strip(): r for r in load_all()}
    first_user = next(m["content"] for m in messages if m["role"] == "user")
    q = re.search(r"Question: (.*)", first_user).group(1).strip()
    item = _gold[q]
    last = messages[-1]["content"]
    n_user = sum(m["role"] == "user" for m in messages)
    if n_user == 1:
        sql = item["SQL"]
        if item["question_id"] % 3 == 0:
            sql = sql.replace("SELECT", "SELEC", 1)
        text = f"```sql\n{sql}\n```"
    elif "ran successfully" in last:
        text = "OK"
    else:
        text = f"```sql\n{item['SQL']}\n```"
    return LLMReply(text=text, prompt_tokens=len(str(messages)) // 4,
                    completion_tokens=len(text) // 4, latency_s=0.0)
