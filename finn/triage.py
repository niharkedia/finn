"""Push-side judgment: what a filing is, how big it is for *this* company, and whether the market agreed."""
import re
from datetime import date, datetime, timedelta

CATEGORIES = ("results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading", "earnings_call",
              "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex", "press_release",
              "postal_ballot", "agm_egm", "pledging", "unclassified")

CXO = r"\b(?:chief|ceo|cfo|coo|cto|managing director|md|whole[- ]?time director|executive director|chair(?:man|person))\b"
CHANGE = r"(?:resign|appoint|cessation|retire|superannuat|steps? down|re-?designat|change in (?:directorate|management|key managerial))"

# (regex, category, subtype, base score). First match wins, so procedural paperwork goes first. The first TYPE_RULES
# describe the kind of filing and are tried on the title alone before everything is tried on title + summary.
RULES = [(re.compile(rx, re.I), cat, sub, base) for rx, cat, sub, base in [
    (r"newspaper|trading window|certificate|loss of share|duplicate share|reg(?:ulation)?\.? ?74|shareholding pattern|"
     r"investor complaints|brsr|business responsibility|secretarial|\bauditors?\b|registrar|registered office|"
     r"corporate office|book closure|annual report|monitoring agency|esop|esos|esps|employee stock|repayment|redemption|"
     r"redeemed|payment of interest|interest payment", "unclassified", "routine", 0.05),
    (r"postal.ballot", "postal_ballot", "ballot", 0.15),
    (r"general meeting|\bagm\b|\begm\b|voting results?|scrutini", "agm_egm", "meeting", 0.12),
    (r"board meeting intimation|intimation of (?:the )?board meeting|prior intimation", "results", "intimation", 0.25),
    (r"investor presentation|earnings presentation|results presentation|shareholders'? letter", "results", "deck", 0.4),
    (r"(?:un)?audited (?:standalone |consolidated |\(.{0,30}\) )*financial results?|financial results? (?:for|of) the (?:quarter|half|year|period)|"
     r"^results? for the|\b(?:q[1-4]|h[12])\b[^|]{0,40}\bresults\b|integrated filing.{0,3}financ", "results", "results", 0.9),
    (r"transcript|conference call|earnings call|audio recording|con-?call", "earnings_call", "call", 0.3),
    (r"analyst|investors? meet|institutional investor", "investor_meetings", "meet", 0.12),
    (r"credit rating|\brating", "credit_rating", "rating", 0.45),
    (r"pledg|encumbrance|reg(?:ulation)?\.? ?31\b", "pledging", "pledge", 0.65),
    (r"insider trading|\bpit\b|\bsast\b|reg(?:ulation)?\.? ?(?:7|10|29)\b", "insider_trading", "insider", 0.4),
    (r"buy-?back|preferential|\bqip\b|qualified institutional|rights issue|raising of funds|fund ?rais|warrants?\b", "fund_raise", "equity", 0.7),
    (r"debenture|commercial paper|\bncds?\b|\bbonds?\b", "fund_raise", "debt", 0.3),
    (r"acqui|merger|amalgamation|demerger|scheme of arrangement|joint venture|\bjv\b|\bstake\b|disinvest|divest", "M&A", "deal", 0.75),
    (r"re-?appoint|continuation", "management_change", "continuity", 0.3),
    (rf"(?=.*{CHANGE}).*\b(?:ceo|chief executive officer|head) of (?:the |its )?(?:[\w&-]+ ){{1,4}}"
     r"(?:complex|division|unit|plant|vertical|region|zone)\b", "management_change", "division", 0.5),
    (rf"(?=.*{CHANGE})(?=.*{CXO})", "management_change", "cxo", 0.85),
    (rf"{CHANGE}|director", "management_change", "board", 0.5),
    (r"award.of.order|receipt.of.order|letter of (?:award|intent)|\bwins?\b.*\border|\borders? (?:worth|win|from|valued|received|for)\b|"
     r"\bbag(?:s|ged|ging)?\b.*\b(?:order|contract)|\bsecure[sd]?\b.*\b(?:order|contract)", "press_release", "order_win", 0.55),
    (r"litigation|dispute|penalt|show cause|demand notice|tax demand|\bnclt\b|insolvency|\bsearch\b|regulatory action|adjudicat|fines? (?:levied|imposed)|levied",
     "litigation", "legal", 0.6),
    (r"capacity|capex|new plant|commission(?:ing|ed)|commercial production|expansion", "capex", "capex", 0.6),
    (r"dividend", "dividend", "dividend", 0.3),
    (r"bonus|split|sub-?division", "bonus_split", "split", 0.5),
    (r"clarification|spurt|price movement|rumou?r", "press_release", "clarification", 0.5),
    (r"press release|media release", "press_release", "news", 0.3),
]]
TYPE_RULES = 8
CATEGORY_BASE = {cat: max(b for _, c, _, b in RULES if c == cat) for _, cat, _, _ in RULES}
SIZED = {"order_win", "deal", "equity", "debt", "capex", "legal"}  # subtypes where the money amount decides materiality

_AMOUNT = re.compile(r"(?P<cur>₹|rs\.?|inr|usd|us\$|\$)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
                     r"(?P<unit>lakh crores?|lakh cr\b|crores?|cr\b|lakhs?|lacs?|mn\b|million|bn\b|billion)", re.I)
_RUPEES = {"lakh crore": 1e12, "lakh cr": 1e12, "crore": 1e7, "cr": 1e7, "lakh": 1e5, "lac": 1e5,
           "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def classify(f: dict) -> dict:
    for text, rules in ((f["title"], RULES[:TYPE_RULES]), (f"{f['title']} | {f['summary']}", RULES)):
        for rx, cat, sub, base in rules:
            if rx.search(text):
                return {"category": cat, "subtype": sub, "base": base, "ruled": True}
    return {"category": "unclassified", "subtype": "other", "base": 0.2, "ruled": False}


def amount_cr(text: str, usd_inr: float) -> float | None:
    """Largest money amount mentioned, in ₹ crore. Bare lakhs/millions without a currency are counts, not money."""
    best, text = None, re.split(r"\bAbout [A-Z][^:]{2,60}:", text)[0]  # drop "About <Company>: a USD 32 billion..." boilerplate
    for m in _AMOUNT.finditer(text):
        unit, cur = m["unit"].lower().rstrip("s"), (m["cur"] or "").lower()
        if not cur and unit not in ("crore", "cr", "lakh crore", "lakh cr"):
            continue
        value = float(m["num"].replace(",", "")) * _RUPEES[unit] * (usd_inr if cur in ("usd", "us$", "$") else 1) / 1e7
        best = max(best or 0.0, value)
    return best


def row(table: dict, *names: str) -> list | None:
    """First of `names` present in a parsed table (screener labels differ for lenders)."""
    return next((table["rows"][n] for n in names if n in table["rows"]), None)


def growth(cur: float | None, base: float | None) -> float | None:
    return round((cur / base - 1) * 100, 1) if cur is not None and base and base > 0 else None


def materiality_line(co: dict) -> float | None:
    """SEBI LODR Reg 30(4)(i)(c), in ₹ crore: the lowest of 2% of turnover, 2% of net worth (if positive)
    and 5% of the 3-year average absolute PAT, from the last audited (consolidated) annual numbers."""
    pl, bs = co["annual"], co["balance"]
    years = [i for i, p in enumerate(pl["periods"]) if p != "TTM"]
    if not years:
        return None
    last, out = years[-1], []
    if sales := row(pl, "Sales", "Revenue"):
        out.append(0.02 * (sales[last] or 0))
    if (pat := row(pl, "Net Profit")) and len(years) >= 3:
        out.append(0.05 * sum(abs(pat[i] or 0) for i in years[-3:]) / 3)
    eq, res = row(bs, "Equity Capital"), row(bs, "Reserves")
    if eq and res and pl["periods"][last] in bs["periods"]:
        j = bs["periods"].index(pl["periods"][last])
        out.append(0.02 * ((eq[j] or 0) + (res[j] or 0)))
    return min((x for x in out if x > 0), default=None)


def _reported_quarter(ts: str) -> str:
    """The quarter a results filing made at `ts` reports: the last quarter-end before it, e.g. 'Sep 2026'."""
    d = datetime.fromisoformat(ts).date()
    month = (d.month - 1) // 3 * 3
    return (date(d.year - 1, 12, 1) if month == 0 else date(d.year, month, 1)).strftime("%b %Y")


def results_card(co: dict, ts: str | None = None) -> dict | None:
    """Revenue / EBITDA / PBT / PAT for the reported quarter vs. last quarter and the same quarter last year."""
    q = co["quarters"]
    want = _reported_quarter(ts) if ts else (q["periods"][-1] if q["periods"] else None)
    if want not in q["periods"]:
        return {"period": want, "pending": True} if want else None
    i, rows = q["periods"].index(want), q["rows"]
    lender = "Financing Profit" in rows
    if lender:  # banks/NBFCs: EBITDA means nothing; net interest income = interest earned - interest expended
        second = ("NII", [r - x if None not in (r, x) else None for r, x in zip(rows.get("Revenue", []), rows.get("Interest", []))])
    else:
        second = ("EBITDA", rows.get("Operating Profit"))
    lines = [("Revenue", row(q, "Sales", "Revenue")), second, ("PBT", rows.get("Profit before tax")), ("PAT", rows.get("Net Profit"))]
    margin = None if lender else rows.get("OPM %")
    return {
        "period": want,
        "metrics": [{"name": name, "value": v[i], "qoq": growth(v[i], v[i - 1]) if i >= 1 else None,
                     "yoy": growth(v[i], v[i - 4]) if i >= 4 else None} for name, v in lines if v and v[i] is not None],
        "margin": {"name": "EBITDA margin", "value": margin[i],
                   "yoy_pp": round(margin[i] - margin[i - 4], 1) if i >= 4 and margin[i - 4] is not None else None}
        if margin and margin[i] is not None else None,
        "note": "Lender: EBITDA is not meaningful; NII = interest earned − interest expended." if lender
        else "EBITDA = operating profit before other income.",
    }


def card_text(card: dict) -> str:
    return " · ".join(f"{m['name']} ₹{m['value']:,.0f} cr" + (f" ({m['yoy']:+.0f}% YoY)" if m["yoy"] is not None else "")
                      for m in card.get("metrics", []))


def assess(f: dict, co: dict, usd_inr: float, text: str | None = None) -> dict:
    """Classify a filing, then rescale its base score by size relative to the company's materiality line.
    `text` (e.g. the filing PDF) is searched for the amount instead of the title and summary."""
    out = classify(f)
    out["why"], out["amount_cr"] = [], amount_cr(text or f"{f['title']} {f['summary']}", usd_inr)
    line = materiality_line(co)
    if out["subtype"] in SIZED and out["amount_cr"] and line:
        r = out["amount_cr"] / line
        out["base"] *= 0.5 + 1 / (1 + r ** -2)  # x0.5 when tiny, x1 at the line, ~x1.5 when several times larger
        size = f"₹{out['amount_cr']:,.0f} cr" if out["amount_cr"] >= 1 else f"₹{out['amount_cr'] * 100:,.0f} lakh"
        out["why"].append(f"{size} {f'= {r:.1f}× its' if r >= 0.1 else 'is far below its'} SEBI materiality line (₹{line:,.0f} cr)")
    elif out["subtype"] in SIZED and text is not None:  # SEBI wants the size of material events; silence suggests small
        out["base"] *= 0.75
        out["why"].append("Size not disclosed in the filing")
    if out["subtype"] == "results" and (card := results_card(co, f["ts"])):
        out["card"] = card
        pat = next((m for m in card.get("metrics", []) if m["name"] == "PAT"), None)
        if pat and pat["yoy"] is not None:  # rank results by how much they move, not just that they exist
            out["base"] = 0.7 + 0.3 * min(abs(pat["yoy"]) / 30, 1)
            out["why"].append(f"PAT {pat['yoy']:+.0f}% YoY")
    return out


def score(f: dict, weights: dict) -> float:
    """Final 0-1 materiality: base x the user's learned category weight, plus a bump if the market reacted."""
    return round(min(f["base"] * weights.get(f["category"], 1.0) + (0.15 if reacted(f) else 0), 1.0), 3)


def reacted(f: dict) -> bool:
    return bool((r := f.get("reaction")) and (abs(r["z"]) >= 2 or r["vol_x"] >= 2))


def _excess(d, market):
    """Daily returns and market-adjusted returns (beta x Nifty removed)."""
    r = d["Close"].pct_change()
    m = market.reindex(r.index)
    beta = r.tail(250).cov(m.tail(250)) / m.tail(250).var()
    return r, r - beta * m


def price_alerts(px: dict, s: dict) -> list[dict]:
    """Last session's moves that cross the user's thresholds, also expressed vs. Nifty and in sigma units."""
    market, out = px["NIFTY"]["Close"].pct_change(), []
    for sym, d in px.items():
        if sym in ("NIFTY", "USDINR") or len(d) < 80:
            continue
        r, ex = _excess(d, market)
        move, vol_x = r.iloc[-1] * 100, d["Volume"].iloc[-1] / d["Volume"].iloc[-21:-1].mean()
        if abs(move) >= s["move_pct"] or vol_x >= s["vol_mult"]:
            out.append({"symbol": sym, "date": d.index[-1].date().isoformat(), "move": round(move, 1),
                        "excess": round(ex.iloc[-1] * 100, 1), "z": round(ex.iloc[-1] / ex.iloc[-61:-1].std(), 1),
                        "vol_x": round(vol_x, 1)})
    return out


def reaction(d, market, ts: str) -> dict | None:
    """The market's verdict on a filing: adjusted move and volume on its first full session."""
    t = datetime.fromisoformat(ts)
    day = t.date() + timedelta(days=1) if (t.hour, t.minute) >= (15, 30) else t.date()
    i = int(d.index.searchsorted(datetime.combine(day, datetime.min.time())))
    if i >= len(d) or i < 61:
        return None
    _, ex = _excess(d, market)
    return {"date": d.index[i].date().isoformat(), "excess": round(ex.iloc[i] * 100, 1),
            "z": round(ex.iloc[i] / ex.iloc[i - 60:i].std(), 1),
            "vol_x": round(d["Volume"].iloc[i] / d["Volume"].iloc[i - 20:i].mean(), 1)}
