# FINN: Research Analysis and Build Plan

*Prepared 13 Nov 2026. The deadline is 15 Nov 2026, so the plan below is budgeted at about 26 hours of build time.*

**How to read this.** Every claim is tagged with one of three labels:
- **[Established]**: a published paper, regulation, or official document, with a link.
- **[Reported]**: one secondary source only. Verify it before relying on it.
- **[Hypothesis]**: my own proposal or expectation, not yet tested.

---

## Revision 2 (15 Nov 2026, build day): what changed after verifying the data and building

The thesis is unchanged: SEBI-relative push ranking, deterministic results cards, and the Promise Ledger as the pull centrepiece. The means changed, based on what I could verify:

| Plan said | Built instead | Why (evidence) |
|---|---|---|
| NSE JSON API plus Integrated-Filing XBRL for results | screener.in public pages: filings with exact timestamps, standardised quarterly/annual tables, transcript links. Results cards come from the quarterly table (no LLM). | The NSE API is undocumented and was blocked in the build environment. NSE's RSS holds only about 9 items. Screener's robots.txt allows `/company/` and `/announcements/recent/`. One source covers filings, statements and transcripts. XBRL stays the next step for minute-zero accuracy. |
| FinBERT-FLS prefilter | Regex prefilter: forward-looking marker plus a number with a unit (%, ₹/$, crore, bps, ×) | FinBERT needs torch, which doesn't fit a free host. Measured: it keeps 4.4% of transcript text (10.8k of 247k characters across 4 Persistent calls). |
| Next.js PWA | One no-build page served by FastAPI | One process and one deploy, with no Node toolchain. |
| Free-text citations, checked by substring | Claims must quote the transcript verbatim (checked by code). The analysis cites input IDs (C#/E#/FACTS). Unknown IDs and numbers absent from the inputs are dropped, and the drop count is shown. | The verification is exact and cheap, and it follows the ALCE-style cited-generation idea. |
| Category-first classification | Title-first for the *type* of filing, title + summary for *content*. The model only sees what about 30 rules can't place. | Measured: 85 of 90 live filings were classified by rules. |

New judgment rules added after live testing:
- **No size disclosed:** the "About \<Company\>" boilerplate is ignored, and an undisclosed size damps the score (SEBI expects the size of material events).
- **Lenders:** NII instead of EBITDA, and no FCF or cash-conversion metrics.
- **Reappointments** count as continuity.
- **Repeat results filings are demoted** (board outcome, deck after the results).
- **CP repayments and other procedural filings are routine.**
- **Push only fresh items:** backfills are never pushed.
- **Quiet windows widen themselves.**

---

## 0. What the two PDFs actually are

They are not research papers. They are a **product and engineering brief** plus a **domain glossary**.

| Document | Content |
|---|---|
| `ENAM_AI_Engineer_Build_Challenge_Main.pdf` | Build **FINN**, a mobile-first investor agent. **Push** has two parts: a windowed digest of exchange filings, and triggered alerts on material announcements or unusual EOD price and volume moves. **Pull** is on-demand research grounded *only* in annual reports and concall transcripts. They are graded on creativity, product sense, judgment, architecture and cost efficiency, *not* completeness. "Thin-but-working beats broad-but-broken." |
| `ENAM_Build_Challenge_Reference.pdf` | 17 announcement categories (results, M&A, fund_raise, management_change, … unclassified), document types (AR, concall, investor deck, filings, screener.in), the primary-vs-secondary-data rule, and headline, balance-sheet and market terms. |

So the "research" below treats the brief's problem as the research question:

> **How do you build a filter that surfaces the few material things from an Indian-equity information firehose, plus an analyst that judges management against its own words, cheaply and without hallucinating?**

### The brief's hidden grading signals (my reading)
1. **The evaluators value "narrative vs. numbers" most.** They say it outright: "promised vs. delivered… the kind of thing we value most."
2. **Judgment about *what not to show*.** "Filtering, not aggregating"; "the routine stuff is collapsed or hidden."
3. **Generalisation.** "We may point it at a company you didn't pick", so nothing can be hard-wired.
4. **Primary-source discipline.** No outside model knowledge on the pull side, which is a *testable* constraint (see §6.3).
5. **Cost routing.** "Cheap models for bulk extraction, a stronger model only where reasoning demands it."
6. **A point of view on interaction.** "Try more than the obvious."

---

## 1. Critical analysis: where the obvious approach fails

The obvious submission is: scrape announcements → LLM summarises each → chat UI over RAG on PDFs. Here is why that is weak in late 2026.

| Obvious approach | Why it's weak | Evidence |
|---|---|---|
| "LLM summary next to every filing" | **NSE already ships this.** On 9 Nov 2026 NSE launched beta AI-assisted summaries of corporate announcements, in text and audio. Summarisation is now commodity. | [Reported] [Analytics India Mag, 9 Nov 2026](https://analyticsindiamag.com/ai-news/nse-launches-stock-discovery-platform-adds-ai-features) |
| Rank by **category** (results > dividend > AGM…) | Materiality is *instance-level and size-relative*. A ₹200 cr order is transformational for a ₹2,000 cr-revenue smallcap and noise for a ₹9 lakh cr conglomerate. A category prior can't tell them apart. | [Established] SEBI itself defines materiality *relative to company size* (Reg 30(4)(i)(c), §3 G1) |
| LLM reads results PDF → Revenue/EBITDA/PBT/PAT | LLMs are unreliable at numeric extraction from filings. In FinanceBench, GPT-4-Turbo with retrieval failed or refused **81%** of 150 sampled questions. A Oct-2026 citation benchmark finds LLMs "generally well grounded but often incorrect". And since **1 Apr 2025** Indian results are filed as **structured XBRL** ("Integrated Filing – Financial"), so the numbers are already machine-readable. | [Established] [FinanceBench, arXiv:2311.11944](https://arxiv.org/abs/2311.11944) · [ECTs-100, arXiv:2610.00969](https://arxiv.org/abs/2610.00969) · [NSE circular 02.04.2025 (mirror)](https://ca2013.com/wp-content/uploads/2025/04/NSE-Circular_02.04.2025.pdf) |
| "Pull a LinkedIn bio" by scraping LinkedIn | Proxycurl, the leading LinkedIn-data API, **shut down in July 2025** after LinkedIn sued it. Scraping LinkedIn is a ToS/legal risk. The *primary* source often already contains the profile: Reg 30 disclosures for director/KMP appointments require a "brief profile". | [Reported] [Proxycurl shutdown](https://www.startuphub.ai/ai-news/startup-news/2025/the-1-linkedin-scraping-startup-proxycurl-shuts-down) · [LODR director-change disclosure items](https://legalmantra.net/blog-detail/What-are-the-disclosures-applicable-for-Change-in-Directors-Key-Managerial-Personnel-of-Director-in-a-Listed-Entity) (verify against the SEBI master circular) |
| RAG chat "summarise the concall" | That is *summarising* management, which the brief explicitly contrasts with *analysing* them. A frontier model also "knows" large-cap Indian companies from pre-training, so a fluent answer may leak outside knowledge and violate the primary-only rule. | [Established] Look-ahead / memorisation: [Glasserman & Lin, arXiv:2309.17322](https://arxiv.org/abs/2309.17322) · [Gao, Jiang & Yan, arXiv:2512.23847](https://arxiv.org/abs/2512.23847) |
| Every alert is a push notification | Attention is the scarce resource, and it is scarcest exactly when you need it. Results season puts 15 portfolio companies into the same two weeks. | [Established] [Hirshleifer, Lim & Teoh 2009, *J. Finance*](https://ideas.repec.org/a/bla/jfinan/v64y2009i5p2289-2325.html): more same-day announcements → weaker immediate reaction and stronger drift |

---

## 2. Literature review (all links verified this session)

### 2.1 Financial document QA and numeric reasoning
| Work | What it shows | Relevance to FINN |
|---|---|---|
| [FinQA, arXiv:2109.00122](https://arxiv.org/abs/2109.00122) | Numerical reasoning over financial reports needs explicit programs, not free text | Compute ratios in code, never in the LLM |
| [TAT-QA, arXiv:2105.07624](https://arxiv.org/abs/2105.07624) | Hybrid table+text QA is much harder than text QA | Annual-report tables need a structured path |
| [FinanceBench, arXiv:2311.11944](https://arxiv.org/abs/2311.11944) | Even strong LLM+RAG fails most open-book filing questions | Motivates the XBRL-first "truth layer" |
| [FinBen, arXiv:2402.12659](https://arxiv.org/abs/2402.12659) | Holistic finance-LLM benchmark; weaknesses on forecasting and complex reasoning | Benchmark context |
| [ECTs-100 citation benchmark, arXiv:2610.00969](https://arxiv.org/abs/2610.00969) (Oct 2026) | On earnings calls LLMs are grounded but often *incorrect*, and poor at detecting *insufficient evidence* | Citations alone aren't enough; add numeric verification and an explicit "not disclosed" state |

### 2.2 Earnings calls, guidance, narrative
| Work | What it shows | Relevance |
|---|---|---|
| [ECTSum, arXiv:2210.12467](https://arxiv.org/abs/2210.12467) | Bullet summarisation of long earnings-call transcripts | Baseline for the "summary" approach FINN should go *beyond* |
| [From Facts to Insights, arXiv:2410.01039](https://arxiv.org/abs/2410.01039) | Multi-agent LLM reports on earnings calls. More agents → more insightful, but humans still preferred. LLM-as-judge correlates with experts | Supports an LLM-judge for eval, and a cautionary tale on verbosity |
| [Corporate Earnings Calls and Analyst Beliefs, arXiv:2511.15214](https://arxiv.org/abs/2511.15214) | LLM-generated *counterfactual* transcripts (numbers held fixed, narrative varied) isolate the effect of narrative. Includes a "guidance" dimension | Method idea: separate the *narrative* from the *numbers* explicitly |
| [CEO promises, *Strategic Mgmt J.* 2026](https://sms.onlinelibrary.wiley.com/doi/full/10.1002/smj.70068) | LLM extracted 74,017 CEO promises from 69k S&P 1500 calls (88% precision). Only a weak correlation (0.09) with formal guidance counts | [Reported via abstract] Promises ≠ formal guidance, so extract both |
| [Agentic Retrieval of Topics from Earnings Calls, arXiv:2507.07906](https://arxiv.org/abs/2507.07906) | LLM agent builds an evolving topic ontology across quarters | Supports tracking *what's newly talked about / dropped* |
| [MiMIC, arXiv:2504.09257](https://arxiv.org/abs/2504.09257) | **Indian** earnings-call dataset (Nifty 50 / Midcap / Smallcap) with transcripts, decks and price reactions | Only Indian-specific earnings-call dataset found. Usable for eval/backtest (CC-NC-SA) |
| [FinCall-Surprise, arXiv:2510.03965](https://arxiv.org/abs/2510.03965) | Multi-modal earnings-surprise benchmark | Context |
| [FinBERT-FLS (HF)](https://huggingface.co/yiyanghkust/finbert-fls) | Small BERT classifier: Specific-FLS / Non-specific FLS / Not-FLS | **Free, local pre-filter** for forward-looking sentences before any LLM call |

### 2.3 Text change as a signal
| Work | What it shows | Relevance |
|---|---|---|
| [Lazy Prices, Cohen, Malloy & Nguyen (NBER w25084; *J. Finance* 2020)](https://www.nber.org/papers/w25084) | Changes in 10-K/10-Q language predict returns, especially changes about the executive team, litigation and risk factors. The market ignores them at release | **Push "what changed", not "what was said"**, and track guidance that silently disappears |

### 2.4 LLMs as financial analysts and agents
| Work | Note |
|---|---|
| [Financial Statement Analysis with LLMs, arXiv:2407.17866](https://arxiv.org/abs/2407.17866) | Anonymised, standardised statements; claimed LLM beats analysts at predicting earnings direction. **Withdrawn on arXiv (v3, Feb 2025).** Cite the *anonymisation method*, not the headline result |
| [FinMem, arXiv:2311.13743](https://arxiv.org/abs/2311.13743), [FinRobot, arXiv:2405.14767](https://arxiv.org/abs/2405.14767), [TradingAgents, arXiv:2412.20138](https://arxiv.org/abs/2412.20138), [MarketSenseAI 2.0, arXiv:2502.00415](https://arxiv.org/abs/2502.00415), [FinGPT, arXiv:2306.06031](https://arxiv.org/abs/2306.06031) | Agent frameworks aimed at *trading decisions*. None targets the "investor inbox" workflow or promise-tracking. Gap |
| [Survey: The New Quant, arXiv:2510.05533](https://arxiv.org/abs/2510.05533) | Survey of LLMs in financial prediction |
| [From SEC Filings to Financial Signals, arXiv:2610.24268](https://arxiv.org/abs/2610.24268) | 13 LLMs on 46k 10-Q MD&As vs abnormal returns and analyst forecasts | Market reaction as an evaluation signal |

### 2.5 Contamination and primary-source discipline
| Work | Use |
|---|---|
| [Glasserman & Lin, arXiv:2309.17322](https://arxiv.org/abs/2309.17322) | Strip company identifiers and compare outputs. Finds a "distraction effect" stronger for large, well-known firms |
| [Gao, Jiang & Yan, arXiv:2512.23847](https://arxiv.org/abs/2512.23847) | "Lookahead Propensity": a closed-book recall probe that measures whether the model already knows the answer. Adaptable as a **contamination test** for FINN |

### 2.6 Grounding, retrieval and parsing
- [ALCE: LLMs generating text with citations, arXiv:2305.14627](https://arxiv.org/abs/2305.14627): citation precision/recall metrics.
- [RAGAS, arXiv:2309.15217](https://arxiv.org/abs/2309.15217): faithfulness and answer relevance metrics.
- [Lost in the Middle, arXiv:2307.03172](https://arxiv.org/abs/2307.03172): don't dump 300-page ARs into context blindly.
- [Anthropic: Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval): chunk-context prefixing for retrieval.
- [ColPali, arXiv:2407.01449](https://arxiv.org/abs/2407.01449): page-image retrieval for table-heavy PDFs (stretch goal).
- [Docling, arXiv:2408.09869](https://arxiv.org/abs/2408.09869) · [GitHub](https://github.com/docling-project/docling): PDF → structured text and tables, local and free.
- [GraphRAG, arXiv:2404.16130](https://arxiv.org/abs/2404.16130) / [LightRAG, arXiv:2410.05779](https://arxiv.org/abs/2410.05779): considered and **rejected** for a 2-day build (see §4).

### 2.7 Cost-efficient model use
- [FrugalGPT, arXiv:2305.05176](https://arxiv.org/abs/2305.05176): LLM cascades, i.e. cheap model first, escalate on low confidence.
- [RouteLLM, arXiv:2406.18665](https://arxiv.org/abs/2406.18665): learned routers between strong and weak models.

### 2.8 Indian market regulation and data (the domain's ground truth)
- **Reg 30(4)(i)(c) quantitative materiality** [Established, via secondary summaries; verify against the Gazette]: an event is material if its value exceeds the **lowest** of (a) **2% of turnover**, (b) **2% of net worth** (skipped if negative), (c) **5% of the 3-year average of absolute profit/loss after tax**, all from the last audited *consolidated* statements. In force from mid-July 2023. Sources: [taxguru](https://taxguru.in/?p=894918), [Taxmann](https://www.taxmann.com/post/blog/opinion-decoding-the-sebi-lodr-second-amendment-regulations/), [SEBI consultation](https://www.sebi.gov.in/sebi_data/meetingfiles/apr-2023/1681703089597_1.pdf).
- **SEBI circular SEBI/HO/CFD/CFD-PoD-1/P/CIR/2023/123 (13 Jul 2023)**: details to disclose per Schedule III event, including timelines.
- **Integrated Filing** (SEBI circular Dec 31 2024; NSE/BSE implementation from **1 Apr 2025**): financial results are submitted via an XBRL utility, and the PDF route was discontinued. [NSE circular](https://ca2013.com/wp-content/uploads/2025/04/NSE-Circular_02.04.2025.pdf) · [BSE circular](https://ca2013.com/wp-content/uploads/2025/04/BSE-Circular_02.04.2025.pdf) · [NSE XBRL info page](https://www.nseindia.com/static/companies-listing/xbrl-information). Per-company iXBRL HTML files are public under `nsearchives.nseindia.com/corporate/ixbrl/…` ([example](https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_126130_11112025183926_iXBRL_WEB.html)).
- **NSE endpoints** (undocumented, so verify in browser DevTools on day 1) [Reported]: `https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&symbol=X`, RSS `https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml`, plus Board_Meetings / Financial_Results / Corporate_action feeds. A browser User-Agent is required. [Write-up](https://dev.to/datadaemon/is-there-an-nse-india-api-for-corporate-announcements-corporate-actions-and-bulk-deals-json-2d48) · [NSE RSS list](https://www.nseindia.com/rss-feed) · [NSE terms of use](https://www.nseindia.com/nse-terms-of-use).
- **NSE official MCP server** [Reported, one blog]: EOD history plus a delayed live snapshot, no API key. [marketcalls tutorial](https://www.marketcalls.in/python/nse-mcp-python-tutorial-build-a-simple-stock-market-ai-agent-with-agno.html). If it's real, it could replace yfinance for EOD data. Optional.

---

## 3. Research gaps (opportunities)

**G1. Size-relative materiality is unexploited.** [Hypothesis] I found no paper or tool that ranks announcements using SEBI's own quantitative materiality threshold. The regulator already did the hard normative work of defining "material for *this* company", and FINN can compute it per company from fundamentals.

**G2. Numbers should never come from an LLM in India post-Apr-2025.** [Hypothesis, grounded in the Established facts above] Since results are now XBRL, a deterministic parser gives QoQ/YoY for free, with zero hallucination and zero tokens. The literature (FinanceBench etc.) mostly evaluates LLMs on PDFs, because US-style benchmarks are built that way.

**G3. Promise-tracking is extracted but rarely *closed*.** Work extracts promises and guidance (SMJ 2026, arXiv:2511.15214) or forecasts from transcripts, but I found no system that, per company and per quarter, **links each quantified forward-looking statement to the later realised number from a structured filing**, together with:
- a status (delivered / missed / pending / quietly dropped);
- a verbatim, page-cited quote.

"Quietly dropped" connects to *Lazy Prices*: disappearance of a previously repeated target is itself a signal.

**G4. "Primary-only" is asserted, never measured.** Products *say* they ground in sources. The contamination literature (arXiv:2309.17322, 2512.23847) gives methods to *test* it: anonymisation plus a closed-book probe. No investor-tool demo I know of reports a contamination metric.

**G5. Push is designed per-item, not per-attention-budget.** Distraction effects (Hirshleifer et al.) imply that the alert threshold should *tighten* on busy days, and that results-season digests should collapse more aggressively. [Hypothesis]

**G6. Cross-linking push and pull.** Existing tools keep the alert feed and the research view separate. A results alert that says *"PAT +12% YoY. Management guided 18–20% in Q1; that's the 2nd straight miss"* fuses push with pull memory. Nothing I found does this. [Hypothesis]

---

## 4. Five candidate ideas (pros and cons)

### Idea A: SEBI-calibrated Materiality Engine (push ranking)
Score each announcement:

```
score = prior(category, subtype)                       # e.g. CFO exit > independent-director exit
      × f( amount / ReqThreshold(company) )            # Reg 30(4) relative size, log-sigmoid
      × surprise(item)                                 # downgrade vs reaffirm; results vs ledger
      + λ · market_reaction(t+1 EOD)                   # abnormal return z, volume / 20d avg
      + personal_weight(user, category)                # learned from swipes
```

Items with `score < τ(day_load)` collapse into "N routine items hidden"; τ rises on busy days (G5).
- **Pros:** principled, explainable ("₹340 cr order = 3.1× this company's SEBI materiality line"), cheap (amount extraction is a tiny LLM call or a regex), novel (G1). The result generalises to any ticker.
- **Cons:** many filings carry no ₹ amount, so the formula falls back to prior × surprise. The threshold needs consolidated turnover, net worth and 3 years of PAT (from screener or XBRL). Banks need a different turnover notion (total income).

### Idea B: XBRL-first Results Card (push enrichment)
Parse the Integrated-Filing iXBRL into Revenue, EBITDA (derived), PBT and PAT for current quarter, previous quarter and same quarter last year. The standard Reg 33 format already carries the three-column comparison. The LLM writes at most one line, and every number in that line is machine-verified against the parsed table.
- **Pros:** ~100% numeric accuracy [Hypothesis], ~0 tokens, instant. This is the brief's named example done *better* than everyone using PDFs.
- **Cons:** EBITDA isn't a reported line, so it must be derived (PBT + finance cost + D&A − other income) and the definition shown. Banks, NBFCs and insurers use different taxonomies, and **EBITDA is meaningless for banks**: show NII/PPOP/PAT instead and *say why* (a product-judgment point). Some quarters may only have PDFs, so keep an LLM-on-PDF fallback.

### Idea C: Promise Ledger (pull hero: "narrative vs numbers")
For the last 4–8 concalls:
1. Use FinBERT-FLS (free, local) to keep only forward-looking sentences, which typically discards most of the transcript [Hypothesis].
2. A cheap LLM turns them into structured claims: `{metric, target/range, unit, horizon, conditionality, speaker, verbatim_quote, page}`.
3. Code resolves each claim against XBRL/AR actuals. Its status is one of **Delivered / Missed (by x pp) / Pending / Not verifiable from primary data / Quietly dropped** (repeated in ≥2 calls, then absent).
4. A strong model writes the "credibility read" only from the resolved ledger.
- **Pros:** exactly what the evaluators said they value most (G3). Highly visual (timeline of promises), auditable, and novel.
- **Cons:** transcript availability varies for small caps. Guidance is fuzzy ("mid-teens", "double-digit"), so ranges need normalisation. Concall KPIs (volumes, order book) may not exist in XBRL and must be resolved from later transcripts' own reported numbers, which is still primary.

### Idea D: "What Changed" diffing (Lazy-Prices for India)
Diff consecutive transcripts and AR sections (risk factors, contingent liabilities, related-party transactions, auditor remarks), and push semantically meaningful changes.
- **Pros:** strong research backing (Lazy Prices), differentiated.
- **Cons:** AR parsing is heavy and ARs are annual, so the demo payoff is slow. **Too big for 2 days**; do the transcript-only slice inside Idea C ("quietly dropped").

### Idea E: Interaction model: "Triage inbox + two channels"
- **Push lives where the investor already is.** A Telegram bot is free and has reliable notifications on iOS and Android with no app install. It sends a short message with a deep link into the PWA.
- **Digest = swipe triage** (→ "Act/Read", ← "Not for me: mute this subtype", ↑ "Remind at close"). Swipes update `personal_weight`, so the filter learns.
- **Pull = "Interrogate" view**, not a blank chat box: ledger timeline + cited cards, with chat as a secondary affordance anchored to a claim ("why do you say missed?").
- **Pros:** a clear point of view ("an agent you triage, not a chatbot you query"). Web Push on iOS works only for home-screen-installed PWAs (iOS ≥ 16.4) and a denied prompt is sticky ([OneSignal docs](https://documentation.onesignal.com/docs/web-push-for-ios)), so Telegram removes that friction for evaluators.
- **Cons:** two surfaces to build. Telegram may feel less "product". Mitigate with in-app inbox parity.

### Options considered and rejected
- **GraphRAG/LightRAG over ARs:** high build cost; global summaries aren't the asked-for analysis.
- **Fine-tuning a classifier:** no labelled Indian announcement dataset was found (searched), and 17 categories with exchange metadata plus rules plus a cheap LLM suffice.
- **Price-prediction agents (TradingAgents-style):** out of scope, and unverifiable in 2 days.

---

## 5. Recommended approach

### **FINN = "The analyst who remembers what management promised, and only interrupts you when it matters for *that* company."**

Build **B + A + C**, joined by a shared **truth layer** (XBRL numbers + cited quotes). Use **E** as the interaction model, with D reduced to the "quietly dropped" signal inside C.

**Why this combination:**
1. **It aims at the stated top value:** promised vs delivered (C) is the hero, not a menu item.
2. **It fuses push and pull** (G6): the results card (B) is annotated by the ledger (C), so a single alert carries analysis no summariser can produce.
3. **The judgment is explainable.** Materiality is size-relative using the regulator's own yardstick (A), which reads as domain judgment and not as a template.
4. **Cheapest-possible correctness.** Numbers come from code, the LLM only handles language, and the strong model runs only on the ledger synthesis, about one call per company per quarter. That matches the "efficiency bonus".
5. **It's honest about primary-only.** You can *show* a contamination metric (§6.3), which almost no submission will.
6. **It's thin-but-working.** Each piece degrades gracefully: no ₹ amount → prior; no XBRL → PDF fallback flagged "LLM-extracted, verify"; no transcript → "insufficient primary data" (the ECTs-100 lesson).

---

## 6. System architecture

```
                         ┌──────────────── SCHEDULER (GitHub Actions cron, free) ────────────────┐
                         │  every 15 min 09:00–18:00 IST: announcements   |  18:30 IST: EOD + alerts │
                         └───────────────────────────────────────────────────────────────────────┘
 INGEST                                   NORMALISE / TIER-0 (no LLM)            STORE (SQLite→Postgres)
 ─────────────────────────────            ───────────────────────────            ─────────────────────
 NSE announcements JSON / RSS ──┐         • dedupe by (symbol, seq_id, hash)     filings(id, symbol, ts,
 BSE announcements (bse pkg) ───┼──────►  • exchange category/subject → rules →    category, amount, score,
 yfinance EOD (.NS/.BO) ────────┤           17-class taxonomy (most resolved)      one_liner, pdf_url)
 NSE iXBRL results ─────────────┤         • regex ₹ amounts / "Cr" / "Lakh"      eod(symbol, date, o,h,l,c,v)
 screener.in → AR + concall PDFs┘         • iXBRL → results table (Arelle/lxml)  results(symbol, period, rev,
                                                                                   ebitda, pbt, pat, src)
                                                                                 claims(… quote, page, status)
 TIER-1: cheap model (bulk, cached forever by doc hash; filings are immutable)
 ─────────────────────────────────────────────────────────────────────────────
 • ambiguous category + subtype (e.g. "CFO resignation" vs "independent director term end")
 • amount + counterparty extraction, one-line "why it matters" (≤ 20 words, JSON schema)
 • FLS sentences (pre-filtered by FinBERT-FLS) → structured guidance claims
 • management change: pull "brief profile" from the filing itself; else web-search bio (cited link)

 TIER-2: strong model (rare: per company per quarter, or on user pull)
 ─────────────────────────────────────────────────────────────────────
 • Ledger synthesis: credibility read, bull/bear, from resolved claims + XBRL table ONLY
 • Anonymised prompts ("Company A", products kept), citations required per sentence

 VERIFIERS (code)
 ────────────────
 • numeric check: every number in generated text ∈ source numbers ∪ computed(QoQ, YoY, margins)
 • quote check: every cited quote is a substring (fuzzy ≥ 0.95) of the cited page
 • fail → regenerate once → else show the raw table / quote only (never unverified prose)

 SERVE                                      CLIENT
 ─────                                      ──────
 FastAPI (Render/Fly/Railway free) or       Next.js PWA (mobile-first): Today digest (swipe triage),
 static JSON on Vercel + edge functions     Alerts, Company → Ledger timeline, Results card,
                                            settings (thresholds: vol ×, ±%, categories)
                                            Telegram bot: push + deep links
```

### 6.1 Model routing (cost)

| Tier | Job | Candidate models | Notes |
|---|---|---|---|
| T0 | rules, regex, XBRL, FinBERT-FLS | none, or local CPU | Expect the large majority of items to end here [Hypothesis; measure it] |
| T1 | classify ambiguous, extract amounts/claims, one-liners | **Claude Haiku 5.5** (`claude-haiku-5-5`, $0.10/$0.50 per M tokens in/out), or a free-tier Gemini Flash-Lite / Groq-hosted open model | Use structured outputs (JSON schema). Use the **Batch API (50% off)** for the backfill. Free-tier quotas for Gemini in Nov 2026 conflict across sources, so check [Google's rate-limit page](https://ai.google.dev/gemini-api/docs/rate-limits) yourself |
| T2 | ledger synthesis, narrative vs numbers, bull/bear | **Claude Opus 5.5** (`claude-opus-5-5`, $4/$20) at `medium`/`low` effort, or Sonnet 5.5 ($2/$10) | Use **Citations** (`citations: {enabled: true}` on PDF document blocks returns page-level `page_location`). Use **prompt caching** on the per-company document prefix so repeat pulls are cheap |

An ablation worth running (and putting in the writeup): **cascade (T1→T2) vs "one strong model at low effort"**. Newer frontier models at low effort can match older models at high effort, and one model keeps one cache namespace. Report the cost per *completed* card, not per call.

### 6.2 Alerts (configurable, the brief's explicit ask)
- `vol_today / mean(vol, 20d) ≥ k` (default k = 2)
- `|ret_today| ≥ x%` (default 5%), plus a **market-adjusted** variant: `ret − β·ret_Nifty`. A 4% drop on a −3% Nifty day isn't news [Hypothesis: this cuts false alerts on macro days].
- `z = (ret − μ_60d)/σ_60d ≥ z*` for volatility-aware thresholds (a smallcap moving 5% is not the same as an index heavyweight moving 5%).
- **Category alerts:** the user picks categories and subtypes. Material-only by default (score ≥ τ).
- **Daily attention budget:** at most N pushes per day; overflow rolls into the digest (G5).

### 6.3 Primary-only enforcement and measurement (G4)
1. Retrieval corpus = only the AR and concall PDFs for that ticker, with no web tool on the pull path.
2. **Anonymise** company name and ticker in T2 prompts. Product and segment names stay, since they are needed for meaning.
3. **Contamination probe:** for 20 ledger questions per demo company, ask T2 the question **with no documents**. Count the answers that are specific and correct. That's the "model already knows" rate. Then show that FINN's grounded answers cite a page for 100% of claims, and that named vs anonymised outputs agree. The method is adapted from arXiv:2309.17322 and arXiv:2512.23847.
4. Expose a **"Sources" drawer** on every card: PDF name, page, quote.

---

## 7. Implementation roadmap (fits the 15 Nov deadline)

> Budget ≈ 26 focused hours. **Cut line:** if you fall behind, drop the items marked ✂ and keep every phase demo-able.

### Phase 0: Setup and verification (≈2 h, tonight)
- [ ] Pick a **portfolio of 15–20 stocks** for *demo contrast*:
  - ≥1 bank and ≥1 NBFC, to show "EBITDA not meaningful" judgment;
  - 2–3 smallcaps with frequent order-win filings, where relative materiality shines;
  - 1 with promoter pledging;
  - 3 companies that give explicit numeric guidance on calls (check one transcript each first);
  - recent tickers renamed or demerged, as a generalisation edge case.
- [ ] Pick 3–5 ad-hoc research companies **outside** the portfolio.
- [ ] In browser DevTools, confirm the NSE announcement JSON, the RSS feed and one iXBRL file for your companies' latest quarter. My automated probe of NSE was blocked in this session, so these endpoints are **unverified** by me.
- [ ] Repo: `backend/` (Python 3.11, uv), `web/` (Next.js), `.github/workflows/`.
- Links: [yfinance](https://github.com/ranaroussi/yfinance) · [NseIndiaApi](https://github.com/BennyThadikaran/NseIndiaApi) ([docs](https://bennythadikaran.github.io/NseIndiaApi)) · [BseIndiaApi docs](https://bennythadikaran.github.io/BseIndiaApi/usage.html) ([PyPI `bse`](https://pypi.org/project/bse)) · [jugaad-data](https://github.com/jugaad-py/jugaad-data)

### Phase 1: Ingestion and storage (≈4 h)
- [ ] `ingest_announcements(symbols, from, to)`: NSE JSON primary, RSS fallback, BSE fallback. Cache raw JSON and PDFs by hash. Sequential requests, browser UA, polite polling (≥ 5 min; the RSS ttl is 5 min).
- [ ] `ingest_eod(symbols)`: yfinance daily for 1 y, Nifty 50 (`^NSEI`) for market adjustment.
- [ ] `ingest_results(symbol)`: locate the iXBRL for the latest 5 quarters and parse it with lxml or [Arelle](https://github.com/Arelle/Arelle). Map tags → {revenue_from_ops, other_income, finance_costs, d&a, pbt, tax, pat}. Unit tests against 3 hand-checked filings.
- [ ] `ingest_fundamentals(symbol)`: screener.in company page → links to ARs and concall transcripts; download, then parse with [Docling](https://github.com/docling-project/docling) or [PyMuPDF](https://github.com/pymupdf/PyMuPDF) **with page numbers kept**. Respect screener's terms and rate-limit yourself. References: [sfinance](https://sfinance.readthedocs.io/en/latest/readme.html).
- [ ] Also compute the **Reg 30 threshold** per company: min(2% turnover, 2% net worth if > 0, 5% × mean(|PAT| last 3 FY)).

### Phase 2: Materiality engine and digest (≈4 h)
- [ ] Tier-0 classifier: map exchange subject/description → 17 categories with keyword rules, and log the residual rate.
- [ ] Tier-1 call for the residuals plus subtype, amount and a one-liner (JSON schema, temperature-free structured outputs). Cache by doc hash.
- [ ] Score as in Idea A. Category priors start from the reference doc ordering; write them as a YAML that the user can see.
- [ ] Management change: extract the "brief profile" from the filing PDF. If absent, run a web search on name + previous company and show a **cited** 2-line bio. The brief explicitly allows this on the push side.
- [ ] Alerts per §6.2, plus the Telegram bot ([Bot API](https://core.telegram.org/bots/api)).
- Links: [Anthropic structured outputs and Batch docs](https://platform.claude.com/docs) · [FrugalGPT](https://arxiv.org/abs/2305.05176)

### Phase 3: Results card (≈3 h)
- [ ] Card shows the four metrics × {Q, Q-1, Q-4} with Δ% QoQ / YoY and margins, plus the EBITDA definition tooltip. Banks get NII / PPOP / PAT.
- [ ] One generated line, run through the numeric verifier.
- [ ] **Ledger hook:** if a resolved claim exists for that metric, add "vs guidance: ✓ / ✗ (−4 pp)".

### Phase 4: Promise Ledger (≈5 h, the hero)
- [ ] For the 3–5 research companies: last 4 concalls → sentences → FinBERT-FLS filter → T1 claim extraction (schema from Idea C) with page and quote.
- [ ] Normalise ranges ("mid-teens" → 13–17%, flagged as an interpretation), horizons (FY27, "next 2 quarters") and conditionality ("subject to demand").
- [ ] Resolver in code: map metric → XBRL actual or a later-call reported KPI → status. "Quietly dropped" = repeated ≥2 calls, then absent.
- [ ] T2 synthesis (anonymised, cited): a 5-bullet credibility read and a tight bull/bear, *only* from the ledger, the XBRL table and the cited quotes.
- [ ] ✂ Balance-sheet and cash-quality tiles from the AR (CFO/PAT conversion, D/E, working-capital days), computed in code.
- Links: [FinBERT-FLS](https://huggingface.co/yiyanghkust/finbert-fls) · [ALCE](https://arxiv.org/abs/2305.14627) · [arXiv:2511.15214](https://arxiv.org/abs/2511.15214) · [ECTs-100](https://arxiv.org/abs/2610.00969)

### Phase 5: Mobile front end (≈5 h)
- [ ] Next.js PWA ([Next.js PWA guide](https://nextjs.org/docs/app/guides/progressive-web-apps)) deployed on Vercel. Three tabs: **Today** (swipe-triage digest with a time-window picker, default 24 h), **Alerts** (threshold settings), **Companies** (Results card, Ledger timeline, Sources drawer).
- [ ] Ledger timeline: a horizontal quarter axis with promise chips (green / red / grey / struck-through for dropped). Tapping a chip shows the quote, page and resolution maths.
- [ ] Swipe feedback → `personal_weight` (a simple per-category logistic update; ✂ to a static mute list).
- [ ] Any-ticker search box → runs the pipeline live (the generalisation proof), with a progress state.
- Links: [Web push on iOS requirements](https://documentation.onesignal.com/docs/web-push-for-ios) · [GitHub Actions schedule](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)

### Phase 6: Mini-evaluation, writeup and submission (≈3 h)
- [ ] Run §8's quick evals and put the table in the README.
- [ ] Covering note: what was built, 3 key decisions (XBRL-first, SEBI-relative materiality, promise ledger), what was left out and why, and next steps.
- [ ] Export the AI build history, including this session.
- [ ] Send to the address and subject line given in the brief.

---

## 8. Evaluation strategy

### 8.1 Push ranking (Idea A)
- **Gold set:** all announcements for the portfolio over the last ~14 days (likely a few hundred items). Label materiality 0–3 yourself, and get a second labeler on 50 items if possible; report Cohen's κ.
- **Weak, independent label:** the next-day |market-adjusted return| and volume ratio. This avoids your own labelling bias, though it is noisy and confounded.
- **Baselines:**
  - B0 chronological;
  - B1 category prior only (the reference-doc taxonomy);
  - B2 zero-shot LLM "rate importance 0–3" (one T1 call per item);
  - B3 the strong model zero-shot.
- **Ours:** the full score. **Ablations:** −relative size, −surprise, −market reaction, −day-load τ.
- **Metrics:** nDCG@5/10, Recall@k of level-≥2 items, **collapse precision** (share of hidden items that are truly routine; must be ≥ 0.95, because hiding a material item is the costly error), pushes per day, cost per 100 items.
- **Expected** [Hypothesis]: ours ≥ B2 on nDCG at <10% of B2's cost. The biggest gain over B1 should come in `press_release` / order wins and `M&A`, where size matters most.

### 8.2 Results card (Idea B)
- 20–30 company-quarters, with values checked by hand against the filing.
- Compare XBRL-parse against LLM-on-PDF (T1 and T2) on exact-match accuracy per metric, latency and cost.
- **Expected** [Hypothesis]: XBRL ≈ 100% on Revenue, PBT and PAT. EBITDA mismatches come only from definition choice, so document the formula.

### 8.3 Promise Ledger (Idea C)
- Hand-annotate guidance claims in 3 companies × 4 calls (~1–2 h). Metrics:
  - **claim extraction** P/R/F1 (match on metric + target + horizon);
  - **resolution accuracy** (status correct);
  - **citation validity** (automatic substring check);
  - **"insufficient data" calibration** (share of unresolvable claims correctly marked not-verifiable instead of guessed).
- **Ablations:** −FinBERT-FLS prefilter (cost ↑, recall Δ?), T1 vs T2 for extraction, named vs anonymised.
- **Contamination metric** (§6.3): closed-book correct-specific rate vs grounded citation rate.

### 8.4 Cost and latency
- Tokens and ₹ per day for the full portfolio, cache hit rate, filing-to-push latency (p50/p95).
- Strong-model-only baseline vs the cascade vs strong-model-at-low-effort.

### 8.5 Product (cheap and convincing)
- 3–5 people, two tasks each:
  - "Which portfolio company had something that matters in the last 24 h, and why?"
  - "Did company X deliver on its margin guidance?"
- Time each task in FINN vs the NSE website plus PDFs. Report the median time saved. Small n, so present it as qualitative.

---

## 9. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| NSE blocks or changes undocumented endpoints | Push feed dies during the demo | RSS + BSE fallbacks; cache everything; ship the demo with a pre-ingested snapshot plus live refresh |
| iXBRL tag names differ by company type (bank, NBFC, insurer) or by standalone vs consolidated | Wrong numbers | Explicit taxonomy maps per category; prefer consolidated; show "standalone" badge; unit tests |
| Concall transcripts missing for small caps | Ledger empty | Pick ledger-demo companies that have transcripts; show the "insufficient primary data" state honestly |
| Fuzzy guidance ("strong double-digit") | Over-claiming misses | Mark it as "interpretation"; treat qualitative claims separately and never score them as missed |
| LLM-generated prose with wrong numbers | Credibility loss | Numeric verifier; fall back to the table |
| LinkedIn/ToS | Legal risk | Filing "brief profile" first; cited web search; no LinkedIn scraping |
| Free-tier quotas | Pipeline stalls | Cache by hash (filings are immutable); use the batch backfill; the T0 tier handles most items |
| Scope creep in 2 days | "Broad-but-broken" | The cut line in §7; demo the 3 hero flows end-to-end before adding anything else |
| Overstated claims in the writeup | Trust | Report §8 numbers with n, and label hypotheses as hypotheses |

---

## 10. Expected outcomes (all hypotheses until §8 runs)
- Push: most incoming filings are auto-collapsed as routine, with collapse precision ≥ 0.95, and ≤ 5 pushes per day per 20-stock portfolio outside results season.
- Results cards: deterministic and near-exact on Revenue, PBT and PAT, with an LLM spend of about 0.
- Ledger: per company, a timeline of 10–30 quantified claims with status and quotes. This is the one view that shows "analysing, not summarising".
- Total LLM cost for the demo portfolio of the order of cents per day (T0/T1 dominant). Measure and report it.

---

## 11. Beyond the deadline (where to take it)
1. Full *Lazy Prices* diffing of AR sections (RPTs, contingent liabilities, auditor remarks), pushed as "what changed".
2. Learn materiality weights from realised market reactions across all NSE filings (weak supervision), and calibrate per sector.
3. A cross-company promise graph: supplier and customer guidance consistency, and peers guiding differently on the same cycle.
4. Voice morning brief (≤ 60 s) generated from the top-3 digest items.
5. Evaluate on [MiMIC](https://arxiv.org/abs/2504.09257) (Indian earnings calls), e.g. whether ledger "miss streaks" precede negative call reactions.

---

### Appendix: the claims behind the recommendation
- **Established, with links:**
  - FinanceBench failure rates;
  - Integrated Filing XBRL from Apr 2025;
  - Reg 30(4) quantitative threshold (via secondary legal summaries; confirm in the Gazette);
  - Lazy Prices;
  - distraction effects;
  - look-ahead and anonymisation methods;
  - FinBERT-FLS;
  - Proxycurl shutdown;
  - the NSE AI-summary launch (single news source).
- **My hypotheses:** every numeric expectation in §8 and §10, the score formula, "quietly dropped" as a signal, day-load thresholding, and the claim that no existing tool closes the promise→XBRL loop. That last one is based on my searches this session, not an exhaustive review.
- **Not verified by me:** NSE API response shapes (my live probe was blocked), the exact iXBRL tag names, the official NSE MCP server, and current Gemini free-tier quotas.
