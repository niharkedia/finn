"""Defaults; deployment-specific values come from environment variables (locally, also from a .env file)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").is_file() else []:  # local secrets, git-ignored
    name, sep, value = line.partition("=")
    if sep and not name.lstrip().startswith("#"):
        os.environ.setdefault(name.strip().removeprefix("export "), value.strip().strip("\"'"))

DB_PATH = Path(os.getenv("FINN_DB", ROOT / "data" / "finn.db"))
POLL_SECONDS = int(os.getenv("FINN_POLL_SECONDS", "900"))
APP_URL = os.getenv("FINN_APP_URL", "")  # public URL, used for deep links in Telegram pushes

# Mixed sectors and sizes. Two lenders are included on purpose: EBITDA means nothing for them.
PORTFOLIO = os.getenv(
    "FINN_PORTFOLIO",
    "RELIANCE,HDFCBANK,BAJFINANCE,TCS,KPITTECH,LT,BEL,HAL,SUNPHARMA,"
    "MARUTI,TITAN,DIXON,POLYCAB,TATAPOWER,ETERNAL,DEEPAKNTR,IRCTC,ADANIPORTS",
).split(",")
RESEARCH_PICKS = ["PERSISTENT", "COFORGE", "ASTRAL", "CGPOWER"]  # outside the portfolio, for on-demand research

# Models: Claude when ANTHROPIC_API_KEY is set. Otherwise open-weight models on any OpenAI-compatible server: Groq's
# free tier when GROQ_API_KEY is set, or FINN_LLM_URL (+ FINN_LLM_KEY) for OpenRouter, a local Ollama, and so on.
CLAUDE = bool(os.getenv("ANTHROPIC_API_KEY"))
LLM_KEY = os.getenv("FINN_LLM_KEY") or os.getenv("GROQ_API_KEY", "")
LLM_URL = (os.getenv("FINN_LLM_URL") or ("https://api.groq.com/openai/v1" if os.getenv("GROQ_API_KEY") else "")).rstrip("/")
# On Groq both tiers use gpt-oss-120b (bulk at low reasoning effort): in a side-by-side on KPIT's calls, gpt-oss-20b
# read past results as promises, while 120b was more accurate and faster. Both are free, so route on effort, not size.
MODELS = {"fast": os.getenv("FINN_MODEL_FAST", "claude-haiku-5-5" if CLAUDE else "openai/gpt-oss-120b"),  # bulk extraction
          "deep": os.getenv("FINN_MODEL_DEEP", "claude-opus-5-5" if CLAUDE else "openai/gpt-oss-120b")}  # judgment

DEFAULT_SETTINGS = {
    "move_pct": 5.0,       # price alert when |daily move| >= this ...
    "vol_mult": 2.0,       # ... or volume >= this multiple of its 20-day average
    "push_min": 0.6,       # filings scoring >= this, in a watched category, are pushed
    "routine_below": 0.4,  # filings scoring < this are collapsed as routine
    "max_push": 8,         # daily push budget: attention is the scarce resource
    "watch": ["results", "M&A", "management_change", "fund_raise", "credit_rating", "litigation", "pledging", "order_win"],
    "weights": {},         # per-category multipliers learned from "less / more like this"
}
