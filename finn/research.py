"""Pull side: fundamentals from reported numbers, and the Promise Ledger -- management's quantified guidance on
earnings calls checked against what the reported numbers (or later calls) show. Numbers come from code; the
LLM reads language, and every claim it makes must cite an input id."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from . import llm, sources, store, triage

FORWARD = re.compile(r"\b(?:expect|guid|target|aim|aspir|plans? to|will\b|would\b|should\b|outlook|anticipat|projected|"
                     r"estimat|commit|intend|confident|going forward|look(?:ing)? (?:at|to|for)|envisag|run[- ]rate|"
                     r"next (?:year|quarter|fiscal|few)|coming (?:year|quarter)|h[12]\b|second half|medium[- ]term|"
                     r"long[- ]term|by (?:march|the end|fy))", re.I)
# A quantity worth checking has a unit: "18%", "₹500 crore", "$50 million", "200 bps", "2x", "double-digit".
QUANT = re.compile(r"\d(?:[\d,.]*\d)?\s*(?:%|per ?cent|bps|basis points|x\b|times\b|crores?|cr\b|lakh|million|billion|mn\b|bn\b)|"
                   r"(?:₹|rs\.?|inr|usd|\$|€|eur)\s*\d|double[- ]digit|single[- ]digit|\bteens\b", re.I)
TURN = re.compile(r"^[ \t]*([A-Z][A-Za-z.'’ ]{2,40}):", re.M)  # "K. Krithivasan:" at the start of a line
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
DATE = re.compile(rf"\b(?:({MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)|(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS}),?\s+(20\d\d))", re.I)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
ROWS = {"revenue_growth": ("Sales", "Revenue"), "revenue": ("Sales", "Revenue"), "pat_growth": ("Net Profit",),
        "pat": ("Net Profit",), "ebitda": ("Operating Profit", "Financing Profit"),
        "ebitda_margin": ("OPM %", "Financing Margin %"), "debt": ("Borrowings", "Borrowing")}


class Claim(BaseModel):
    metric: str
    kind: Literal["revenue_growth", "pat_growth", "ebitda_margin", "revenue", "ebitda", "pat", "debt", "other"]
    low: float | None
    high: float | None
    unit: str
    reported_basis: bool
    period: Literal["quarter", "full_year", "multi_year", "open"]
    period_end: str | None
    quote: str
    page: int


class Claims(BaseModel):
    claims: list[Claim]


class Resolution(BaseModel):
    claim: str
    status: Literal["delivered", "beat", "missed", "unverifiable"]
    actual: str
    evidence: list[str]


class Point(BaseModel):
    text: str
    refs: list[str]


class Analysis(BaseModel):
    verdict: str
    resolutions: list[Resolution]
    credibility: list[Point]
    bull: list[Point]
    bear: list[Point]


EXTRACT = """You read excerpts of an Indian listed company's earnings-call transcript and extract MANAGEMENT's
quantified forward-looking statements: guidance, targets, margin bands, growth, capex and debt plans.
- Use only the excerpts. Skip analysts' questions, statements with no number or numeric band, and historical facts:
  results already achieved ("grew 24% this quarter") are not promises.
- metric: a short plain-English name ("Revenue growth", "EBITDA margin", "Net debt to EBITDA").
- unit: with scale and currency as stated ("USD bn", "USD mn", "INR cr", "%", "x"); "$" is USD, "Rs" or "₹" is INR.
- low/high bound the target in its unit: "at least 20%" -> low 20; "below 2x" -> high 2; "18-20%" -> 18, 20;
  "about 20%" -> 19, 21; "double-digit" -> low 10.
- kind: revenue_growth / pat_growth are year-on-year % growth; ebitda_margin is a %; revenue, ebitda, pat, debt are
  amounts; everything else (order inflow, volumes, capex, store count, ROCE...) is other.
- reported_basis: true only if the target can be checked against reported consolidated INR statements (false for
  constant-currency or USD growth, segment-only or non-GAAP metrics).
- period/period_end: the period the target is for. Indian fiscal years end in March (FY27 = Apr 2026-Mar 2027,
  period_end "2027-03"). Resolve "this year" or "next quarter" using the call date. multi_year or open when no
  single period is stated.
- quote: the sentence copied verbatim, without the [p#] tag; page: its p number."""

ANALYSE = """You judge management credibility for a listed Indian company, called "the Company".
Use ONLY the inputs: FACTS (reported financials), CLAIMS (management's own guidance; where the reported numbers
settle a claim, code has already set its status) and EVIDENCE (excerpts of later earnings calls).
Never use outside knowledge of the company, its industry or the market.
- resolutions: one per CLAIM whose status is "unverified": decide from EVIDENCE only, cite evidence ids, and use
  "unverifiable" when the evidence does not settle it.
- verdict: one line on whether management's words track its numbers. If nothing has fallen due yet (claims pending or
  long-dated), say it is too early to judge and name what falls due next: an unexpired target is not a miss.
- credibility: 2-4 points on promised vs. delivered (patterns, slippage, quietly changed targets).
- bull and bear: up to 3 points each.
Each point cites ids (C#, E#, or FACTS) in refs, and every number in it must appear in the cited inputs."""


def sentences(pages: list[str], forward: bool) -> list[dict]:
    """Quantified sentences (only forward-looking ones if `forward`), tagged with page and speaker.
    Questions and the moderator are skipped: guidance is what management says, not what analysts ask."""
    out, speaker = [], ""
    for page_no, page in enumerate(pages, 1):
        start = 0
        for turn in [*TURN.finditer(page), None]:
            if not speaker.lower().startswith("moderator"):
                for s in re.split(r"(?<=[.!?])\s+", " ".join(page[start:turn.start() if turn else None].split())):
                    if 25 < len(s) < 600 and not s.endswith("?") and QUANT.search(s) and (not forward or FORWARD.search(s)):
                        out.append({"page": page_no, "speaker": speaker, "text": s})
            if turn:
                speaker, start = turn[1].strip(), turn.end()
    return out


def call_date(pages: list[str], label: str) -> date:
    """The call's date: the latest past date on the first two pages (call or cover-letter date), else screener's month."""
    found = []
    for m in DATE.finditer(" ".join(pages[:2])):
        month, day, year = (m[1], m[2], m[3]) if m[1] else (m[5], m[4], m[6])
        try:
            found.append(datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date())
        except ValueError:
            pass
    return max((d for d in found if d <= date.today()), default=datetime.strptime(label, "%b %Y").date())


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _ym(period: str) -> str:
    return datetime.strptime(period, "%b %Y").strftime("%Y-%m")


def _fmt(kind: str, v: float) -> str:
    return f"{v:+.1f}% YoY" if kind.endswith("growth") else f"{v:.1f}%" if kind == "ebitda_margin" else f"₹{v:,.0f} cr"


def _calls(co: dict, n: int = 4) -> list[dict]:
    """The latest `n` distinct earnings calls with machine-readable transcripts, oldest first."""
    calls = []
    for cc in co["concalls"][: n + 3]:
        try:
            pages = sources.pdf_text(cc["url"])
            if not "".join(pages).strip():  # scanned or empty transcript
                continue
            day = call_date(pages, cc["month"]).isoformat()
        except Exception:  # dead link, a host that refuses us, an odd month label: skip that call
            continue
        if all(c["date"][:7] != day[:7] for c in calls):
            calls.append({"date": day, "url": cc["url"], "pages": len(pages), "chars": sum(map(len, pages)),
                          "forward": sentences(pages, True), "facts": sentences(pages, False)})
        if len(calls) == n:
            break
    return sorted(calls, key=lambda c: c["date"])


def _extract(call: dict) -> list[dict]:
    lines = "\n".join(f"[p{s['page']}] {s['speaker']}: {s['text']}" for s in call["forward"])
    found = llm.ask("fast", EXTRACT, f"Call date: {call['date']}\n\n{lines}", Claims) if lines else None
    source = _norm(lines)  # a claim survives only if its quote is really in the transcript, and looks ahead
    return [c.model_dump() | {"call": call["date"]} for c in (found.claims if found else [])
            if len(q := _norm(c.quote)) >= 20 and q[:60] in source and FORWARD.search(c.quote)]


def settle(c: dict, co: dict) -> tuple[str, float | None, str | None]:
    """(status, actual, period label) for a claim, decided by code wherever reported numbers can decide it."""
    c["period_end"] = (c["period_end"] or "")[:7] or None  # models sometimes give a full date: keep YYYY-MM
    if c["period"] in ("multi_year", "open") or not c["period_end"]:
        return "long-dated", None, None
    try:
        label = datetime.strptime(c["period_end"], "%Y-%m").strftime("%b %Y")
    except ValueError:
        return "unverified", None, None
    table = co["balance"] if c["kind"] == "debt" else co["quarters" if c["period"] == "quarter" else "annual"]
    reported = [p for p in table["periods"] if p != "TTM"]
    if reported and c["period_end"] > _ym(reported[-1]):
        return "pending", None, label
    series = triage.row(table, *ROWS.get(c["kind"], ()))
    in_crore = c["kind"] not in ("revenue", "pat", "ebitda", "debt") or "cr" in c["unit"].lower()
    if not (c["reported_basis"] and series and in_crore and label in table["periods"]):
        return "unverified", None, label
    i = table["periods"].index(label)
    if c["kind"].endswith("_growth"):
        j = i - (4 if c["period"] == "quarter" else 1)
        actual = triage.growth(series[i], series[j]) if j >= 0 else None
    else:
        actual = series[i]
    if actual is None:
        return "unverified", None, label
    tol = 0.25 if "%" in c["unit"] else 0.01 * abs(c["low"] or c["high"] or 0)
    more_is_better = c["kind"] != "debt"
    if c["low"] is not None and actual < c["low"] - tol:
        return ("missed" if more_is_better else "beat"), actual, label
    if c["high"] is not None and actual > c["high"] + tol:
        return ("beat" if more_is_better else "missed"), actual, label
    return "delivered", actual, label


def _topic(c: dict) -> str:
    return c["kind"] if c["kind"] != "other" else " ".join(re.findall(r"[a-z]+", c["metric"].lower())[:3])


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower())) - {"growth", "will", "this", "that", "with", "year", "quarter"}


def _evidence(claims: list[dict], calls: list[dict]) -> dict:
    """Up to three later-call sentences sharing each unsettled claim's keywords; ids E1, E2, ..."""
    ids = {}
    for c in claims:
        if c["status"] != "unverified" or not (words := _words(c["metric"])):
            continue
        later = [(len(words & _words(s["text"])), call["date"], s) for call in calls if call["date"] > c["call"] for s in call["facts"]]
        for hits, day, s in sorted(later, key=lambda x: -x[0])[:3]:
            if hits >= min(2, len(words)):
                c.setdefault("evidence", []).append(ids.setdefault((day, s["page"], s["text"]), f"E{len(ids) + 1}"))
    return {eid: {"call": day, "page": page, "text": text} for (day, page, text), eid in ids.items()}


def _facts(co: dict) -> str:
    lines = []
    for title, table in (("Quarter", co["quarters"]), ("Year", co["annual"])):
        rev, margin, pat = (triage.row(table, *n) for n in (("Sales", "Revenue"), ("OPM %",), ("Net Profit",)))
        lines.append(f"{title}: revenue ₹cr | operating margin % | PAT ₹cr")
        for i, p in list(enumerate(table["periods"]))[-8 if title == "Quarter" else -5:]:
            lines.append(f"{p}: " + " | ".join(str(v[i]) if v and v[i] is not None else "-" for v in (rev, margin, pat)))
    return "\n".join(lines)


def _analyse(co: dict, claims: list[dict], evidence: dict) -> dict | None:
    """One strong-model call; anything it says that cites unknown ids or unsupported numbers is dropped."""
    names = sorted({co["name"], re.sub(r"\s+(?:ltd|limited)\.?$", "", co["name"], flags=re.I), co["symbol"]}, key=len, reverse=True)

    def anon(text: str) -> str:  # hide the company's identity so the model cannot lean on what it already "knows"
        for n in names:
            text = re.sub(rf"\b{re.escape(n)}\b", "the Company", text, flags=re.I)
        return text

    claim_lines = [f"[{c['id']}] {c['call'][:7]} call, p{c['page']}: \"{anon(c['quote'])}\" -> {c['metric']}; "
                   f"target {c['low']}-{c['high']} {c['unit']}; {c['period']} ending {c['period_end']}; status {c['status']}"
                   + (f" (actual {c['actual']})" if c.get("actual") else "") for c in claims]
    evidence_lines = [f"[{eid}] {e['call'][:7]} call, p{e['page']}: {anon(e['text'])}" for eid, e in evidence.items()]
    facts = _facts(co)
    context = "\n".join([facts, *claim_lines, *evidence_lines])
    out = llm.ask("deep", ANALYSE, f"FACTS\n{facts}\n\nCLAIMS\n" + "\n".join(claim_lines)
                  + "\n\nEVIDENCE\n" + ("\n".join(evidence_lines) or "(none)"), Analysis)
    if not out:
        return None
    known = {c["id"] for c in claims} | set(evidence) | {"FACTS"}
    exact = {round(float(n.replace(",", "")), 1) for n in NUMBER.findall(context)}
    rounded = {round(x) for x in exact}

    def supported(text: str) -> bool:  # "20.9" must appear as such; "21" may round from it; small counts are exempt
        numbers = [float(n.replace(",", "")) for n in NUMBER.findall(text)]
        return all(x <= 12 or round(x, 1) in exact or (x.is_integer() and x in rounded) for x in numbers)

    by_id = {c["id"]: c for c in claims}
    for r in out.resolutions:
        c = by_id.get(r.claim)
        if c and c["status"] == "unverified" and r.status != "unverifiable" and r.evidence and set(r.evidence) <= set(evidence):
            c.update(status=r.status, actual=r.actual, evidence=r.evidence, settled_by="later call")
    points = {k: [p.model_dump() for p in getattr(out, k) if set(p.refs) <= known and supported(p.text)]
              for k in ("credibility", "bull", "bear")}
    removed = sum(len(getattr(out, k)) - len(v) for k, v in points.items())
    return {"verdict": out.verdict if supported(out.verdict) else None, **points, "removed": removed}


def build_ledger(symbol: str) -> dict:
    co = sources.company(symbol)
    calls = _calls(co)
    with ThreadPoolExecutor(4) as pool:  # one cheap-model call per transcript, in parallel
        for call, found in zip(calls, pool.map(_extract, calls)):
            call["claims"] = found
    claims = [c for call in calls for c in call["claims"]]
    for n, c in enumerate(claims, 1):
        c["id"] = f"C{n}"
        c["status"], actual, c["period_label"] = settle(c, co)
        if actual is not None:
            c.update(actual=_fmt(c["kind"], actual), settled_by="reported numbers")
    if len(calls) >= 3:  # topics guided on in two earlier calls but not in the latest one
        seen = [{_topic(c) for c in call["claims"]} for call in calls]
        dropped = {t for t in set().union(*seen[:-1]) if sum(t in s for s in seen[:-1]) >= 2} - seen[-1]
        for c in claims:
            c["dropped"] = _topic(c) in dropped
    evidence = _evidence(claims, calls)
    sent = sum(len(s["text"]) for call in calls for s in call["forward"])
    return store.put("ledger", symbol, {
        "built": datetime.now().isoformat(timespec="minutes"),
        "calls": [{"date": c["date"], "url": c["url"], "pages": c["pages"], "guidance_sentences": len(c["forward"])} for c in calls],
        "claims": claims,
        "evidence": evidence,
        "analysis": _analyse(co, claims, evidence) if claims else None,
        "raw": [] if claims else [s | {"call": c["date"]} for c in calls[-1:] for s in c["forward"][:12]],
        "stats": {"transcript_chars": sum(c["chars"] for c in calls), "chars_to_llm": sent, "llm": llm.available()},
    })


def trend(co: dict) -> dict:
    q, a = co["quarters"], co["annual"]
    years = [i for i, p in enumerate(a["periods"]) if p != "TTM"]

    def cagr(names: tuple, n: int) -> float | None:
        v = triage.row(a, *names)
        if v and len(years) > n and (end := v[years[-1]]) and (start := v[years[-1 - n]]) and end > 0 and start > 0:
            return round(((end / start) ** (1 / n) - 1) * 100, 1)

    return {"periods": q["periods"][-12:],
            "revenue": (triage.row(q, "Sales", "Revenue") or [])[-12:],
            "margin": (triage.row(q, "OPM %") or [])[-12:],  # lenders: screener's "financing margin" is not a margin
            "pat": (triage.row(q, "Net Profit") or [])[-12:],
            "cagr": {f"{label} {n}y": cagr(names, n) for label, names in (("Revenue", ("Sales", "Revenue")), ("PAT", ("Net Profit",))) for n in (3, 5)}}


def health(co: dict) -> list[dict]:
    """Balance-sheet and cash-quality checks: latest reported value vs. three periods earlier."""
    b, cf, r, out = co["balance"], co["cashflow"], co["ratio_table"], []
    lender = "Financing Profit" in co["quarters"]["rows"]  # a lender's operating cash flow is its loan book and deposits

    def add(label: str, values: list | None, periods: list, unit: str, good: str):
        pts = [(p, v) for p, v in zip(periods, values or []) if v is not None and p != "TTM"]
        if pts:
            out.append({"label": label, "unit": unit, "good": good, "period": pts[-1][0], "now": pts[-1][1],
                        "then_period": pts[-4][0] if len(pts) >= 4 else None, "then": pts[-4][1] if len(pts) >= 4 else None})

    eq, res, debt = triage.row(b, "Equity Capital"), triage.row(b, "Reserves"), triage.row(b, "Borrowings")
    if eq and res and debt and "Deposits" not in b["rows"]:  # deposit-takers run on leverage: D/E says nothing
        add("Debt / equity", [round(d / (e + x), 2) if None not in (d, e, x) and e + x > 0 else None
                              for d, e, x in zip(debt, eq, res)], b["periods"], "x", "down")
    if not lender:
        add("Cash conversion (CFO / EBITDA)", triage.row(cf, "CFO/EBITDA"), cf["periods"], "%", "up")
        add("Free cash flow", triage.row(cf, "Free Cash Flow"), cf["periods"], "₹ cr", "up")
    add("Working-capital days", triage.row(r, "Working Capital Days"), r["periods"], "days", "down")
    add("ROCE" if "ROCE %" in r["rows"] else "ROE", triage.row(r, "ROCE %", "ROE %"), r["periods"], "%", "up")
    return out


def snapshot(symbol: str) -> dict:
    co = sources.company(symbol)
    return {"symbol": symbol, "name": co["name"], "consolidated": co["consolidated"], "ratios": co["ratios"],
            "results": triage.results_card(co), "trend": trend(co), "health": health(co),
            "concalls": len(co["concalls"]), "ledger": store.get("ledger", symbol)}
