"""All settings come from environment variables (or a .env file in the repo root)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# --- LLM (any OpenAI-compatible endpoint) ---
LLM_MODEL = os.getenv("LLM_MODEL", "mock")          # "mock" = fake model for testing, no API calls
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None    # None = api.openai.com
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
_temp = os.getenv("LLM_TEMPERATURE", "0")
LLM_TEMPERATURE = float(_temp) if _temp != "" else None   # set to empty for models that reject temperature
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# --- Data ---
DATA_FILE = ROOT / "data" / "mini_dev_prompt.jsonl"
DB_ROOT = Path(os.getenv("DB_ROOT", ROOT / "data" / "dev_databases"))

# --- Agent ---
MAX_LLM_CALLS = int(os.getenv("MAX_LLM_CALLS", "4"))     # same budget for retry & selfcheck: 1 first try + 3 more
OBS_ROWS = 10                                            # rows shown to the model after execution

# --- Paths ---
CACHE_DB = ROOT / "cache" / "llm_cache.sqlite"
RESULTS_DIR = ROOT / "results"
