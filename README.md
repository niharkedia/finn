# FINN: an investor's filter for Indian equities

FINN watches a portfolio's exchange filings and prices and pushes only what matters, sized against each company's own scale. On demand, it checks management's earnings-call promises against the numbers the company later reported.

**Live:** https://finn-silk.vercel.app (best on a phone) · **Code:** https://github.com/niharkedia/finn

**Point of view:** an investor doesn't need another feed or another chatbot. They need an inbox triaged by an analyst who is strict about scale and has a long memory. So FINN is built around three questions:
- **Today:** what needs my attention?
- **Alerts:** tell me when my thresholds are crossed.
- **Research:** can I trust what management says?

## Run it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "GROQ_API_KEY=..." > .env      # optional: free open-weight models; everything else works without a key
.venv/bin/uvicorn finn.api:app      # open http://localhost:8000 on a phone-sized window
```

On start, a background thread fetches the portfolio's latest filings. Off market hours, it also runs the end-of-day price scan. After that it polls every 15 minutes. With Docker, `docker build -t finn . && docker run -p 8000:8000 -e GROQ_API_KEY finn` runs it on any container host. The live copy runs on Vercel's free Hobby plan: `app.py` is Vercel's FastAPI entrypoint, `vercel.json` bundles the starter database, and because Vercel pauses idle instances, the first visit after a quiet 15 minutes triggers a refresh right after the page is served. To host it free on Render instead, push the repository to GitHub, create a Blueprint from it in Render (it reads `render.yaml`), and paste the Groq key when asked. A fresh host starts from `seed/finn.db`, a snapshot with recent filings and five built ledgers, so the app never opens empty after its host sleeps.

The model steps are guidance extraction, the credibility analysis, labels for filings the rules can't place, and profiles of new executives. Any one of these settings turns them on:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Open-weight `openai/gpt-oss-120b` on Groq's free tier: low reasoning effort for bulk extraction, medium for judgment |
| `ANTHROPIC_API_KEY` | Claude instead: Haiku 5.5 for bulk extraction, Opus 5.5 for judgment |
| `FINN_LLM_URL` (+ `FINN_LLM_KEY`) | Any other OpenAI-compatible server, such as a local Ollama at `http://localhost:11434/v1`; pick models with `FINN_MODEL_FAST` and `FINN_MODEL_DEEP` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Real push notifications (works on any phone, no app install needed) |
| `FINN_APP_URL` | Public URL, so pushes deep-link into the app |
| `FINN_PORTFOLIO` | Comma-separated NSE symbols (default: 18 stocks across sectors and sizes, including two lenders) |

## What it does

**Push: Today (digest).** Today lists every filing in a window you pick (24h, 3, 7 or 30 days), ranked by materiality. Routine paperwork is collapsed behind one line. If the default 24h window is quiet, it widens itself and says so rather than showing an empty screen. Every card says *why* it ranks where it does, for example:
- "₹909 cr = 3.5× its SEBI materiality line (₹256 cr)"
- "PAT −23% YoY"
- "Market reacted: −2.3% vs Nifty (−1.5σ), volume 3.3×"

Two filing types get special treatment:
- **Results** get a card: Revenue, EBITDA, PBT and PAT vs. last quarter and the same quarter last year. Lenders get net interest income (NII) instead of EBITDA, which means nothing for a bank.
- **Management changes** carry the person's profile from the filing itself, since SEBI requires one for appointments.

"Less like this" re-weights a category immediately.

**Push: Alerts.** You set the thresholds in one sentence: "a stock moves 5% or trades 2× its 20-day volume". Moves are also reported market-adjusted (beta × Nifty removed) and in σ, so a −4% day in a −3% market reads as the non-event it is. Material filings in the categories you watch become alerts too. A daily push budget keeps attention scarce, and stale or backfilled items are recorded but never pushed.

**Pull: Research (any NSE ticker).** Research builds a profile from reported numbers:
- the latest quarter
- a 12-quarter trajectory
- 3- and 5-year CAGRs
- debt/equity, cash conversion, free cash flow, working-capital days and ROCE, each vs. three years ago

Lenders skip the metrics that don't apply to them.

**The Promise Ledger** is the centrepiece. FINN reads the last four earnings-call transcripts, extracts every *quantified* promise management made, and settles each one:
- **Delivered / Beat / Missed:** decided by code from the reported numbers when they can decide it, e.g. "≥20% FY26 revenue growth" vs. the actual +23.5%.
- **Settled by a later call:** otherwise, a strong model judges the claim from what management said on later calls, and must cite those sentences.
- **Pending / Long-dated:** the period hasn't ended, or no period was stated.
- **Not repeated in the latest call:** a target guided on twice that quietly disappeared.

The analysis then gives a one-line credibility verdict and bull and bear points, each citing claim or evidence IDs.

## How the judgment works

1. **What a filing is.** About 30 regex rules over BSE's fairly regular titles. The *type* of filing (results, transcript, ballot, routine paperwork) is decided from the title first, and the *content* from title + summary. This stops "transcript of the call on financial results" from being read as results. Only filings no rule covers go to the cheap model, in one batched call.
2. **How big it is for this company.** SEBI's own materiality test (LODR Reg 30(4)(i)(c)) is the lowest of:
   - 2% of turnover
   - 2% of net worth
   - 5% of the 3-year average |PAT|

   FINN computes that line per company and scales order wins, deals, fund raises, capex and litigation by `amount / line`. The same ₹500 cr order is noise for Reliance and transformational for a small cap. When the summary has no amount, FINN reads the filing PDF, skipping the "About <Company>" boilerplate. When the filing discloses no size, it says so and damps the score.
3. **Results rank by surprise**, using the size of the PAT change, and repeat results filings (board outcome, deck) are demoted.
4. **The market's verdict.** After the close, each recent filing gets its first full session's market-adjusted move and volume, and a notable reaction raises its score.
5. **Your feedback** multiplies category weights (bounded at ×0.3 to ×2).

## Architecture

```
finn/sources.py   screener.in company pages (filings, statements, transcript links) · filing PDFs · Yahoo EOD
finn/triage.py    push judgment: rules, SEBI materiality line, results card, price alerts, market reaction
finn/research.py  pull: fundamentals + Promise Ledger (prefilter -> extract -> settle -> analyse -> verify)
finn/llm.py       model calls (Claude, or any OpenAI-compatible server): structured output, two tiers, permanent cache
finn/service.py   jobs (poll, end of day, push) and read models · finn/store.py SQLite · finn/api.py FastAPI
web/              one-page mobile app, no build step (vanilla JS + CSS, light/dark)
seed/finn.db      the snapshot a fresh host starts from: recent filings, caches and five built ledgers
```

**Model routing and cost:**
- **Rules first.** Most work never reaches a model.
- **Cheap tier for bulk extraction.** gpt-oss-120b at low reasoning effort (or Claude Haiku 5.5) reads the filtered transcript sentences and labels the leftover filings.
- **Strong tier for judgment.** gpt-oss-120b at medium effort (or Claude Opus 5.5) makes one call per company ledger. On a free tier the scarce resource is tokens per minute, not money, so the tiers differ in effort rather than model size (see Measured).
- **Strict structured output.** Replies are constrained to a JSON schema where the server supports it, and validated either way; on a rate limit, FINN waits as long as the server asks.
- **Code for every number.**
- **Cache forever.** Filings never change, so every model answer is cached by prompt hash, and a second view costs nothing.

**Grounding:**
- Extracted promises must quote the transcript verbatim (checked by code).
- The analysis sees an anonymised company ("the Company"), so it can't lean on what it already "knows".
- Every point must cite input IDs.
- Points with unknown IDs, or with numbers absent from the inputs, are dropped, and the UI says how many were dropped.

## Measured so far (this build, 15 Nov 2026)

- **Filtering:** the 18-stock portfolio's latest 90 filings came in, and the rules classified 86 (96%), leaving 4 for the model. Over the last 7 days, 10 of 31 filings were judged material and 21 were collapsed.
- **Token economy:** the prefilter kept 10.8k of 247k transcript characters (4.4%) across Persistent's last four calls.
- **Examples:**
  - TATAPOWER's ₹11,871 cr pumped-storage capex scored 50× its materiality line.
  - L&T's order with no disclosed size was correctly damped.
  - HDFC Bank's reappointment of an executive director was read as continuity, not a CXO change.

**Live on open-weight models (Groq free tier):**
- **Persistent's ledger** read four calls and kept 17 quantified promises, each with a verbatim quote, for about 11k tokens and $0. Its verdict: "Too early to judge; the next pending target is the FY27 Q4 run-rate of $500 m."
- **KPIT:** code settled a quarter's −1% revenue guidance against the reported +8.8%, so it shows as beat.
- **Executive profiles:** Tata Power's incoming-CEO card reads "Former President – Renewables of Tata Power; … CEO of TPDDL; over three decades in power", taken from the filing itself.
- **Model choice, measured on KPIT's four calls.** gpt-oss-20b at medium effort found 4 promises in 50 s. gpt-oss-120b at low effort found 18 in 12 s, and the 7 of those whose quote had no forward-looking cue were past facts, which code now drops. So both tiers run 120b and differ in reasoning effort.

**Known weak spot:** the free model's analysis can over-read, for example setting rupee revenue against a dollar target. The verifier catches invented numbers and IDs, not every bad inference. The Claude path is unchanged but untested here, since no Anthropic key was available.

**Next measurement:** hand-label one week of filings 0–3 and compare FINN's ranking (nDCG@10, recall of material items, precision of what gets collapsed) against chronological order, category-only priors, and screener's own "Important" tab.

## Decisions and trade-offs

- **The data comes from screener.in's public pages.** The robots.txt allows `/company/` and `/announcements/recent/`. They give BSE filings with exact timestamps, standardised statements and transcript links from one source. The trade-off is that only the 5 latest filings per company are visible per poll, so FINN stores history and polls every 15 minutes. NSE's JSON API was not used: it is undocumented, and it was blocked in the build environment.
- **Results numbers come from screener's tables of the filed results, not from an LLM reading the PDF.** LLMs are unreliable at numeric extraction from filings: on FinanceBench, GPT-4-Turbo with retrieval failed or refused 81% of sampled questions. If a filing lands before the tables catch up, the card says "pending" and fills in on its own.
- **A regex prefilter, not a FinBERT classifier.** It needs no torch, so it fits a free host, and on a free model tier the prefilter is about focus and rate limits, not dollars.
- **No LinkedIn scraping.** The profile comes from the filing, with a search link as the fallback.

## Deliberately left out

- the business snapshot and segment mix
- annual-report section diffing ("what changed in the risk factors")
- web push, since Telegram is more reliable across phones
- per-user accounts
- intraday prices

## Next

1. **Exchange-native results:** parse the Integrated-Filing XBRL so cards are exact the minute results land.
2. **Learned materiality weights** from realised market reactions across all filings.
3. **AR diffing:** contingent liabilities, related-party transactions and auditor remarks.
4. **A cross-company promise graph:** peers guiding differently on the same cycle.
