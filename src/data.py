"""Load BIRD mini-dev questions and make a fixed pilot / eval split.

pilot (30 questions)  -> the ONLY questions you may look at while tuning prompts
eval  (300 questions) -> the questions you report on; never tune on these
Both are stratified by difficulty and fixed by SEED, so you and B always get the same split.
"""
import json
import random
from collections import defaultdict
from pathlib import Path

from . import config

SEED = 469
PILOT_N = 30
EVAL_N = 300


def load_all():
    with open(config.DATA_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _stratified_take(groups, n, total):
    """Take n items across groups proportionally to group size (largest-remainder rounding)."""
    take = {k: n * len(v) // total for k, v in groups.items()}       # integer maths, no float rounding
    remainder = {k: n * len(v) % total for k, v in groups.items()}
    leftover = n - sum(take.values())
    for k in sorted(remainder, key=remainder.get, reverse=True)[:leftover]:
        take[k] += 1
    out = []
    for k, v in groups.items():
        out += v[: take[k]]
        del v[: take[k]]
    return out


def splits():
    items = sorted(load_all(), key=lambda r: r["question_id"])
    rng = random.Random(SEED)
    groups = defaultdict(list)
    for r in items:
        groups[r["difficulty"]].append(r)
    for v in groups.values():
        rng.shuffle(v)
    total = len(items)
    pilot = _stratified_take(groups, PILOT_N, total)
    eval_ = _stratified_take(groups, EVAL_N, total - PILOT_N)
    rest = [r for v in groups.values() for r in v]
    return {"pilot": pilot, "eval": eval_, "eval_full": eval_ + rest}


def get_split(name):
    return splits()[name]


def db_path(db_id) -> Path:
    return Path(config.DB_ROOT) / db_id / f"{db_id}.sqlite"
