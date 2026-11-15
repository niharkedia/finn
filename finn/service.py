"""Jobs (poll filings, end-of-day scan, push) and the read models the API serves."""
import copy
import hashlib
import html
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Literal

import requests
from pydantic import BaseModel

from . import llm, sources, store, triage
from .config import APP_URL, DEFAULT_SETTINGS, POLL_SECONDS, PORTFOLIO, RESEARCH_PICKS

IST = timezone(timedelta(hours=5, minutes=30))
_jobs = threading.Lock()


class Label(BaseModel):
    id: str
    category: Literal[triage.CATEGORIES]
    material: bool
    why: str


class Labels(BaseModel):
    labels: list[Label]


class Person(BaseModel):
    name: str
    role: str
    change: Literal["appointed", "resigned", "retired", "re-designated", "other"]
    effective: str | None
    background: str | None
    reason: str | None


class People(BaseModel):
    people: list[Person]


LABEL = ("You triage Indian stock-exchange filings for a fund manager. For each line (id | title | summary) choose one "
         f"category from: {', '.join(triage.CATEGORIES)}. material = could plausibly move the stock. "
         "why = at most 12 words, from the text only.")
PERSON = ("From this exchange filing about a management change, list each person whose role changes. background: "
          "the brief profile the filing gives (SEBI requires one for appointments), max 40 words, from the text only; "
          "null if absent. Never add facts that are not in the filing.")


def now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def settings() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS) | (store.get("settings", "user") or {})


def save_settings(changes: dict) -> dict:
    clean = {k: type(DEFAULT_SETTINGS[k])(v) for k, v in changes.items() if k in DEFAULT_SETTINGS}  # "0.6" -> 0.6
    return store.put("settings", "user", settings() | clean)


def feedback(category: str, more: bool) -> dict:
    """"Less / more like this": nudge the category's weight, bounded so one tap never hides a category for good."""
    s = settings()
    s["weights"][category] = round(min(max(s["weights"].get(category, 1.0) * (1.25 if more else 0.8), 0.3), 2.0), 2)
    return save_settings(s)


def telegram(text: str) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=15, json={
        "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    return r.ok


def alert(key: str, symbol: str, ts: str, kind: str, title: str, body: str, severity: float):
    """Record an alert once; push it if the day's push budget allows."""
    if not store.run("INSERT OR IGNORE INTO alerts (id, symbol, ts, kind, title, body, severity) VALUES (?,?,?,?,?,?,?)",
                     (key, symbol, ts, kind, title, body, severity)):
        return
    day_ago = (datetime.now(IST) - timedelta(hours=24)).isoformat()
    if ts < day_ago:  # backfilled or stale news is recorded, never pushed
        return
    pushed = store.rows("SELECT COUNT(*) AS n FROM alerts WHERE sent = 1 AND ts >= ?", (day_ago,))[0]["n"]
    link = f'\n<a href="{APP_URL}#alerts">Open FINN</a>' if APP_URL else ""
    if pushed < settings()["max_push"] and telegram(f"<b>{symbol}</b> · {html.escape(title)}\n{html.escape(body)}{link}"):
        store.run("UPDATE alerts SET sent = 1 WHERE id = ?", (key,))


def _people(f: dict) -> list[dict]:
    try:
        pages = sources.pdf_text(f["url"])
        found = llm.ask("fast", PERSON, "\n".join(pages[:6])[:15000], People) if pages else None
    except Exception as e:  # enrichment is optional; the filing still goes through
        print(f"people {f['symbol']}: {e!r}")
        return []
    people = {}
    for p in found.people if found else []:  # one entry per person, keeping their top-management role if any
        if p.name not in people or re.search(triage.CXO, p.role, re.I):
            people[p.name] = p.model_dump()
    return list(people.values())


def _new_filings(symbol: str, usd_inr: float) -> list[dict]:
    co = sources.company(symbol)
    out = []
    for f in sources.filings(co["id"]):
        f |= {"id": hashlib.sha1(f["url"].encode()).hexdigest()[:16], "symbol": symbol, "name": co["name"]}
        if store.rows("SELECT 1 FROM filings WHERE id = ?", (f["id"],)):
            continue
        judged = triage.assess(f, co, usd_inr)
        if judged.get("card", {}).get("pending"):  # fresh results: the cached tables may predate them
            co = sources.company(symbol, max_age=0)
            judged = triage.assess(f, co, usd_inr)
        if judged["subtype"] in triage.SIZED and judged["amount_cr"] is None:  # size not in the summary: read the filing
            judged = triage.assess(f, co, usd_inr, " ".join(sources.pdf_text(f["url"])[:2]))
        out.append(f | judged)
    return out


def poll(symbols: list[str] = PORTFOLIO) -> list[dict]:
    """Fetch new filings, judge them (rules first, cheap model only for what rules miss), store, and push."""
    usd_inr = store.get("fx", "USDINR") or 88.0
    new = []
    for symbol in symbols:
        try:
            new += _new_filings(symbol, usd_inr)
        except Exception as e:  # one broken page must not stop the portfolio
            print(f"poll {symbol}: {e!r}")
    unknown = {f["id"]: f for f in new if not f["ruled"]}
    try:  # labels only enrich: a model outage must not lose this round's filings
        labels = unknown and llm.ask("fast", LABEL, "\n".join(f"{i} | {f['title']} | {f['summary']}" for i, f in unknown.items()), Labels)
    except Exception as e:
        print(f"labels: {e!r}")
        labels = None
    for lab in labels.labels if labels else []:
        if f := unknown.get(lab.id):
            f.update(category=lab.category, subtype="model", why=f["why"] + [lab.why],
                     base=triage.CATEGORY_BASE[lab.category] * (1.0 if lab.material else 0.5))
    s = settings()
    for f in sorted(new, key=lambda f: f["ts"]):
        if (card := f.get("card")) and store.rows("SELECT 1 FROM filings WHERE symbol = ? AND json_extract(data, '$.card.period') = ?",
                                                  (f["symbol"], card["period"])):  # board outcome, deck... after the results
            del f["card"]
            f.update(base=0.3, why=[f"Follow-up to the {card['period']} results already surfaced"])
        if f["category"] == "management_change" and f["base"] >= 0.5 and (people := _people(f)):
            f["people"] = people
            if f["subtype"] != "division" and any(re.search(triage.CXO, p["role"], re.I) for p in people):
                f["base"] = max(f["base"], 0.85)
        store.run("INSERT OR IGNORE INTO filings VALUES (?, ?, ?, ?)", (f["id"], f["symbol"], f["ts"], json.dumps(f)))
        if triage.score(f, s["weights"]) >= s["push_min"] and {f["category"], f["subtype"]} & set(s["watch"]):
            body = (triage.card_text(f["card"]) if f.get("card") else "") or f["summary"] or "; ".join(f["why"])
            alert(f["id"], f["symbol"], f["ts"], "filing", f["title"], body, triage.score(f, s["weights"]))
    store.put("job", "poll", now())
    return new


def end_of_day():
    """Price/volume alerts on the last session, and the market's reaction to the past fortnight's filings."""
    px = sources.prices(PORTFOLIO)
    if "NIFTY" not in px:
        raise RuntimeError("no benchmark prices from Yahoo Finance")
    market = px["NIFTY"]["Close"].pct_change()
    if "USDINR" in px:
        store.put("fx", "USDINR", float(px["USDINR"]["Close"].iloc[-1]))
    for a in triage.price_alerts(px, settings()):
        body = f"{a['move']:+.1f}% ({a['excess']:+.1f}% vs Nifty, {a['z']:+.1f}σ) · volume {a['vol_x']:.1f}× 20-day avg"
        severity = min(1.0, max(abs(a["z"]) / 4, a["vol_x"] / 6))
        alert(f"px:{a['symbol']}:{a['date']}", a["symbol"], f"{a['date']}T15:30:00+05:30", "price", "Unusual move", body, severity)
    since = (datetime.now(IST) - timedelta(days=14)).isoformat()
    for row in store.rows("SELECT id, symbol, ts, data FROM filings WHERE ts >= ?", (since,)):
        if row["symbol"] in px and (r := triage.reaction(px[row["symbol"]], market, row["ts"])):
            store.run("UPDATE filings SET data = ? WHERE id = ?", (json.dumps(json.loads(row["data"]) | {"reaction": r}), row["id"]))
    store.put("job", "eod", now())


def _market_open(t: datetime) -> bool:
    return t.weekday() < 5 and 9 <= t.hour < 16  # yfinance's last bar is partial during the session


def run_jobs(rescan_prices: bool = False):
    with _jobs:  # the scheduler and a manual refresh must not overlap
        poll()
        if not _market_open(datetime.now(IST)) and (rescan_prices or store.get("job", "eod", max_age=6 * 3600) is None):
            end_of_day()


def scheduler():
    while True:
        try:
            run_jobs()
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_SECONDS)


def digest(hours: int) -> dict:
    """Filings in the window, ranked by materiality; anything under the routine line is collapsed."""
    s, since = settings(), (datetime.now(IST) - timedelta(hours=hours)).isoformat(timespec="seconds")
    items = []
    for row in store.rows("SELECT data FROM filings WHERE ts >= ? ORDER BY ts DESC", (since,)):
        f = json.loads(row["data"])
        if f.get("card", {}).get("pending") and (co := store.get("company", f["symbol"])):
            f["card"] = triage.results_card(co, f["ts"])  # tables may have caught up since the filing
        f["score"] = triage.score(f, s["weights"])
        if triage.reacted(f):
            r = f["reaction"]
            f["why"].append(f"Market reacted: {r['excess']:+.1f}% vs Nifty ({r['z']:+.1f}σ), volume {r['vol_x']:.1f}× on {r['date']}")
        items.append(f)
    items.sort(key=lambda f: -f["score"])  # stable: newest first among equals
    material = [f for f in items if f["score"] >= s["routine_below"]]
    return {"hours": hours, "material": material, "routine": items[len(material):], "updated": store.get("job", "poll")}


def alerts(days: int) -> list[dict]:
    since = (datetime.now(IST) - timedelta(days=days)).isoformat()
    return store.rows("SELECT * FROM alerts WHERE ts >= ? ORDER BY ts DESC, severity DESC", (since,))


def status() -> dict:
    names = {r["key"]: r["name"] for r in store.rows("SELECT key, json_extract(value, '$.name') AS name FROM kv WHERE ns = 'company'")}
    return {"portfolio": [{"symbol": s, "name": names.get(s, s)} for s in PORTFOLIO],
            "picks": [{"symbol": s, "name": names.get(s, s)} for s in RESEARCH_PICKS],
            "llm": llm.MODELS["deep"] if llm.available() else "", "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
            "last_poll": store.get("job", "poll"), "last_eod": store.get("job", "eod")}
