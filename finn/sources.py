"""Fetchers: screener.in company pages (financials, filings, concalls), filing PDFs, end-of-day prices."""
import io
import threading
import time

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from . import store

SCREENER = "https://www.screener.in"
HTTP = requests.Session()
HTTP.headers["User-Agent"] = "FINN/0.1 (research prototype)"
_pace = threading.Lock()


def fetch(url: str) -> requests.Response:
    """Polite GET: one request at a time with a short gap, backing off on HTTP 429."""
    for attempt in range(4):
        with _pace:
            r = HTTP.get(url, timeout=30)
            time.sleep(0.5)
        if r.status_code != 429:
            break
        time.sleep(10 * (attempt + 1))
    r.raise_for_status()
    return r


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _table(section) -> dict:
    """A screener data-table as {"periods": ["Sep 2025", ...], "rows": {"Sales": [floats aligned to periods]}}."""
    table = section.select_one("table.data-table") if section else None
    if not table:
        return {"periods": [], "rows": {}}
    rows = {}
    for tr in table.select("tbody tr"):
        label, *cells = tr.select("td") or [None]
        values = [_num(td.get_text()) for td in cells]
        if any(v is not None for v in values):
            rows[next(label.stripped_strings, "").rstrip(" +")] = values
    return {"periods": [th.get_text(strip=True) for th in table.select("thead th")[1:]], "rows": rows}


def company(symbol: str, max_age: float = 6 * 3600) -> dict:
    """Parsed company page, cached for `max_age` seconds (a stale copy is served if screener is unreachable)."""
    return store.memo("company", symbol, lambda: _company_page(symbol), max_age)


def _company_page(symbol: str) -> dict:
    """Parse a company page: consolidated numbers when screener has them, else standalone."""
    for view in ("consolidated/", ""):
        soup = BeautifulSoup(fetch(f"{SCREENER}/company/{symbol}/{view}").text, "html.parser")
        if soup.select_one("section#quarters tbody td"):
            break
    section = {s["id"]: s for s in soup.select("section[id]")}
    ratios = {}
    for li in soup.select("#top-ratios li"):
        if (name := li.select_one(".name")) and (value := li.select_one(".number")):
            ratios[name.get_text(strip=True)] = _num(value.get_text())
    return {
        "symbol": symbol,
        "name": soup.h1.get_text(strip=True),
        "id": soup.select_one("[data-company-id]")["data-company-id"],
        "consolidated": bool(view),
        "ratios": ratios,
        "quarters": _table(section.get("quarters")),
        "annual": _table(section.get("profit-loss")),
        "balance": _table(section.get("balance-sheet")),
        "cashflow": _table(section.get("cash-flow")),
        "ratio_table": _table(section.get("ratios")),
        "concalls": [
            {"month": li.div.get_text(strip=True), "url": a["href"]}
            for li in soup.select("div.concalls li")
            if (a := li.select_one('a[title="Raw Transcript"]'))
        ],
    }


def filings(company_id: str) -> list[dict]:
    """The five latest exchange filings (BSE feed via screener): a 4 KB fragment, cheap enough to poll."""
    soup = BeautifulSoup(fetch(f"{SCREENER}/announcements/recent/{company_id}/").text, "html.parser")
    out = []
    for li in soup.select("li"):
        if li.time and li.a:
            note = li.time.parent.get_text(" ", strip=True)  # "9 Nov - one-line summary"
            out.append({"ts": li.time["datetime"], "title": next(li.a.stripped_strings, ""), "url": li.a["href"],
                        "summary": note.split(" - ", 1)[1] if " - " in note else ""})
    return out


def pdf_text(url: str) -> list[str]:
    """Text of each page of a filing or transcript PDF ([] if not a text PDF). Cached forever: filings never change."""
    return store.memo("pdf", url, lambda: _pdf_text(url))


def _pdf_text(url: str, max_pages: int = 60) -> list[str]:
    data = fetch(url).content  # network errors propagate (and are not cached); bad documents are cached as []
    try:
        return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages[:max_pages]]
    except Exception:
        return []


def prices(symbols: list[str], period: str = "1y") -> dict:
    """Daily Close/Volume frames per NSE symbol, plus NIFTY (benchmark) and USDINR (to size USD amounts)."""
    import yfinance as yf  # heavy import, needed only by the end-of-day job

    tickers = {f"{s}.NS": s for s in symbols} | {"^NSEI": "NIFTY", "INR=X": "USDINR"}
    df = yf.download(list(tickers), period=period, auto_adjust=True, progress=False, group_by="ticker")
    if df is None or df.empty:
        return {}
    found = set(df.columns.get_level_values(0))
    return {name: df[t][["Close", "Volume"]].dropna(subset=["Close"]) for t, name in tickers.items() if t in found}
