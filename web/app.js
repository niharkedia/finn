"use strict";
const view = document.getElementById("view");
const state = { hours: 24 };

const LABEL = {
  results: "Results", "M&A": "M&A", fund_raise: "Fund raise", management_change: "Management", litigation: "Legal",
  insider_trading: "Insider trade", earnings_call: "Earnings call", investor_meetings: "Investor meet",
  credit_rating: "Credit rating", dividend: "Dividend", bonus_split: "Bonus / split", capex: "Capex",
  press_release: "News", postal_ballot: "Postal ballot", agm_egm: "AGM / EGM", pledging: "Pledge",
  unclassified: "Routine", order_win: "Order win",
};
const SUBTYPE = { order_win: "Order win", clarification: "Clarification", continuity: "Reappointment",
                  cxo: "Top-management change", division: "Divisional head", deck: "Results deck", intimation: "Board-meeting notice" };
const STATUS = { delivered: "Delivered", beat: "Beat", missed: "Missed", pending: "Pending",
                 "long-dated": "Long-dated", unverified: "Unverified" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const href = (u) => (/^https?:\/\//.test(u || "") ? esc(u) : "#");
const ext = (u, text) => `<a href="${href(u)}" target="_blank" rel="noopener">${text}</a>`;
const num = (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-IN"));
const cr = (v) => (v == null ? "–" : `₹${num(v)} cr`);
const pct = (v, unit = "%") => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit}`);
const month = (d) => new Date(d).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
const ago = (ts) => {
  const m = (Date.now() - new Date(ts)) / 6e4;
  return m < 60 ? `${Math.max(1, Math.round(m))}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
};
// BSE titles lead with boilerplate ("Announcement under Regulation 30 (LODR)-"); keep the informative tail.
const tidy = (t) => t.replace(/^.*?\b(?:regulation|reg\.?)\s*30\b[^-–:]*[-–:]\s*/i, "").replace(/_/g, " ");
const kind = (f) => SUBTYPE[f.subtype] || LABEL[f.category] || f.category;

async function api(path, options = {}) {
  const r = await fetch(`/api/${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const put = (path, body) => api(path, { method: "PUT", body: JSON.stringify(body) });

function toast(message) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.classList.add("on");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("on"), 2500);
}

/* ---------- Today: the digest ---------- */

const WINDOWS = [[24, "24h"], [72, "3 days"], [168, "7 days"], [720, "30 days"]];

async function today() {
  let d = await api(`digest?hours=${state.hours}`), note = "";
  if (!state.chosen && !d.material.length) {  // first visit to a quiet window: widen it rather than show nothing
    for (const [h, label] of WINDOWS.slice(1)) {
      const wider = await api(`digest?hours=${h}`);
      if (wider.material.length) {
        [d, note, state.hours] = [wider, `Nothing material in the last 24h, so here are the last ${label}.`, h];
        break;
      }
    }
  }
  state.chosen = true;
  const total = d.material.length + d.routine.length;
  view.innerHTML = `
    <div class="seg">${WINDOWS.map(([h, l]) => `<button data-hours="${h}" class="${h === state.hours ? "on" : ""}">${l}</button>`).join("")}</div>
    ${note ? `<p class="note">${note}</p>` : ""}
    <p class="lede"><b>${d.material.length}</b> of ${total} filings need your attention${total ? "" : ", a quiet window"}.</p>
    ${d.material.map(card).join("")}
    ${d.routine.length ? `<details class="routine"><summary>${d.routine.length} routine filings hidden</summary>
      ${d.routine.map(line).join("")}</details>` : ""}`;
}

const card = (f) => `
  <article class="card" style="--s:${f.score}">
    <div class="meta"><a class="sym" href="#research/${esc(f.symbol)}">${esc(f.symbol)}</a>
      <span>${esc(kind(f))}</span><time>${ago(f.ts)}</time></div>
    <h3>${esc(f.summary || tidy(f.title))}</h3>
    ${f.summary ? `<p class="sub">${esc(tidy(f.title))}</p>` : ""}
    ${f.card ? results(f.card) : ""}
    ${(f.people || []).map(person).join("")}
    ${f.why.length ? `<ul class="why">${f.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    <div class="actions">${ext(f.url, "Filing ↗")}<span class="score" title="Materiality score">${f.score.toFixed(2)}</span>
      <button data-less="${esc(f.category)}">Less like this</button></div>
  </article>`;

const line = (f) => `<a class="line" href="${href(f.url)}" target="_blank" rel="noopener">
  <b>${esc(f.symbol)}</b><span>${esc(f.summary || tidy(f.title))}</span><time>${ago(f.ts)}</time></a>`;

const delta = (v) => `<td class="${v == null ? "" : v >= 0 ? "up" : "down"}">${pct(v)}</td>`;
const results = (c) => (c.pending
  ? `<p class="note">${esc(c.period)} numbers are not tabulated yet, so open the filing.</p>`
  : `<table class="res"><thead><tr><th>${esc(c.period)}</th><th>₹ cr</th><th>QoQ</th><th>YoY</th></tr></thead><tbody>
      ${c.metrics.map((m) => `<tr><td>${esc(m.name)}</td><td>${num(m.value)}</td>${delta(m.qoq)}${delta(m.yoy)}</tr>`).join("")}
     </tbody></table>
     <p class="note">${c.margin ? `${esc(c.margin.name)} ${c.margin.value}% (${pct(c.margin.yoy_pp, "pp")} YoY). ` : ""}${esc(c.note)}</p>`);

const person = (p) => `<div class="person"><b>${esc(p.name)}</b>, ${esc(p.role)}<span class="pill">${esc(p.change)}</span>
  ${p.background ? `<p>${esc(p.background)}</p>`
    : `<p class="note">The filing gives no profile. ${ext(`https://www.google.com/search?q=${encodeURIComponent(`${p.name} ${p.role} LinkedIn`)}`, "Search ↗")}</p>`}</div>`;

/* ---------- Alerts: thresholds the investor sets ---------- */

async function alerts() {
  const [list, s] = await Promise.all([api("alerts?days=14"), api("settings")]);
  view.innerHTML = `
    <form class="rule" data-form="thresholds">Alert me when a stock moves
      <input name="move_pct" type="number" step="0.5" min="0.5" value="${s.move_pct}">% in a day, or trades
      <input name="vol_mult" type="number" step="0.5" min="1" value="${s.vol_mult}">× its 20-day volume.
      <button>Save and rescan</button></form>
    ${list.map((a) => `<article class="alert ${a.kind}" style="--s:${a.severity}">
        <div class="meta"><a class="sym" href="#research/${esc(a.symbol)}">${esc(a.symbol)}</a>
          <span>${a.kind === "price" ? "Price / volume" : "Filing"}</span><time>${ago(a.ts)}</time></div>
        <h3>${esc(a.body)}</h3>${a.kind === "price" ? "" : `<p class="sub">${esc(tidy(a.title))}</p>`}</article>`).join("")
      || `<p class="empty">No alerts in the last 14 days at these thresholds.</p>`}`;
}

/* ---------- Research: any NSE ticker, grounded in reported numbers and the company's own calls ---------- */

async function research(symbol) {
  if (!symbol) {
    const s = await api("status");
    const chip = (c) => `<a class="chip" href="#research/${esc(c.symbol)}">${esc(c.symbol)}<small>${esc(c.name === c.symbol ? "" : c.name)}</small></a>`;
    view.innerHTML = `
      <form class="search" data-form="search"><input name="q" placeholder="Any NSE ticker, e.g. INFY" autocomplete="off" required>
        <button>Open</button></form>
      <h2>Portfolio</h2><div class="chips">${s.portfolio.map(chip).join("")}</div>
      <h2>Research picks</h2><div class="chips">${s.picks.map(chip).join("")}</div>`;
    return;
  }
  view.innerHTML = `<p class="empty">Loading ${esc(symbol)}…</p>`;
  const c = await api(`company/${encodeURIComponent(symbol)}`);
  const r = c.ratios;
  view.innerHTML = `
    <h1>${esc(c.name)}</h1>
    <p class="sub">${esc(c.symbol)} · ${c.consolidated ? "consolidated" : "standalone"} · ₹${num(r["Current Price"])} ·
      m-cap ${cr(r["Market Cap"])} · P/E ${r["Stock P/E"] ?? "–"} · ROCE ${r.ROCE ?? "–"}%</p>
    <h2>Promise ledger</h2>${ledger(c)}
    ${c.results ? `<h2>Latest quarter</h2><div class="card">${results(c.results)}</div>` : ""}
    <h2>Trajectory</h2><div class="card">${spark(c.trend)}
      <p class="note">${Object.entries(c.trend.cagr).map(([k, v]) => `${esc(k)} CAGR ${pct(v)}`).join(" · ")}</p></div>
    <h2>Balance sheet and cash</h2><div class="card">${c.health.map(health).join("") || `<p class="note">Not reported.</p>`}</div>`;
}

function spark(t) {
  const n = t.revenue.length;
  const revenue = t.revenue.filter((v) => v != null), margin = t.margin.filter((v) => v != null);
  if (!revenue.length) return "";
  const W = 300, H = 96, w = W / n, top = Math.max(...revenue), lo = Math.min(...margin), hi = Math.max(...margin);
  const bars = t.revenue.map((v, i) => (v == null ? "" : `<rect x="${i * w + 2}" y="${H - (v / top) * (H - 36)}" width="${w - 4}" height="${(v / top) * (H - 36)}" rx="2"/>`)).join("");
  const line = t.margin.map((v, i) => (v == null ? "" : `${i * w + w / 2},${6 + (1 - (v - lo) / (hi - lo || 1)) * 24}`)).filter(Boolean).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="Quarterly revenue and operating margin">${bars}<polyline points="${line}"/></svg>
    <p class="note">Revenue (bars)${margin.length ? " and operating margin (line)" : ""}, ${esc(t.periods[0])} to ${esc(t.periods[n - 1])}.
      ${margin.length ? `Latest margin ${margin[margin.length - 1]}%.` : ""}</p>`;
}

const value = (v, unit) => (unit === "₹ cr" ? cr(v) : unit === "x" ? `${v}×` : unit === "%" ? `${v}%` : `${v} ${unit}`);
function health(h) {
  const trend = h.then == null || h.now === h.then ? "" : (h.now > h.then) === (h.good === "up") ? "up" : "down";
  return `<div class="kv"><span>${esc(h.label)}</span><b class="${trend}">${value(h.now, h.unit)}</b>
    <small>${esc(h.period)}${h.then == null ? "" : `, vs ${value(h.then, h.unit)} in ${esc(h.then_period)}`}</small></div>`;
}

const unit = (u) => (u.trim() === "%" ? "%" : ` ${u}`);
const target = (x) => (x.low != null && x.high != null && x.low !== x.high ? `${x.low}–${x.high}${unit(x.unit)}`
  : x.low != null ? `≥ ${x.low}${unit(x.unit)}` : x.high != null ? `≤ ${x.high}${unit(x.unit)}` : "");

function ledger(c) {
  const L = c.ledger;
  const button = `<button class="primary" data-ledger="${esc(c.symbol)}">${L ? "Rebuild from the latest calls" : "Check management's promises"}</button>`;
  if (!L) {
    return `<div class="card"><p>Reads the last four earnings-call transcripts and pulls out every quantified promise management made.
      It then checks each one against the reported numbers or what management said on later calls.</p>${button}</div>`;
  }
  const a = L.analysis, s = L.stats;
  const evidence = (id) => (L.evidence[id] ? `<blockquote class="ev"><span class="ref">${id}</span> ${esc(L.evidence[id].text)}
    <small>${month(L.evidence[id].call)} call, p${L.evidence[id].page}</small></blockquote>` : "");
  const claim = (x, call) => `<details class="claim"><summary><span class="st ${x.status}">${STATUS[x.status]}</span>
      ${esc(x.metric)} ${esc(target(x))} <small>${esc(x.period_label || x.period.replace("_", " "))}</small>
      ${x.dropped ? `<span class="pill">not repeated in the latest call</span>` : ""}</summary>
    <blockquote>“${esc(x.quote)}” ${ext(`${call.url}#page=${x.page}`, `p${x.page} ↗`)}</blockquote>
    ${x.actual ? `<p>Actual: <b>${esc(x.actual)}</b> <small>(settled by ${esc(x.settled_by)})</small></p>` : ""}
    ${(x.evidence || []).map(evidence).join("")}</details>`;
  const points = (k, title) => (a && a[k].length ? `<h3>${title}</h3><ul class="points">${a[k].map((p) =>
    `<li>${esc(p.text)} ${p.refs.map((r) => `<span class="ref">${esc(r)}</span>`).join("")}</li>`).join("")}</ul>` : "");
  const counts = Object.keys(STATUS).map((k) => [k, L.claims.filter((x) => x.status === k).length]).filter(([, n]) => n);
  return `<div class="card">
    ${a?.verdict ? `<p class="verdict">${esc(a.verdict)}</p>` : ""}
    <p class="note">Calls read: ${L.calls.map((call) => ext(call.url, month(call.date))).join(" · ")}.
      ${L.claims.length} quantified promises; ${Math.round((100 * s.chars_to_llm) / (s.transcript_chars || 1))}% of transcript text sent to the model.</p>
    <div class="tally">${counts.map(([k, n]) => `<span class="st ${k}">${n} ${STATUS[k]}</span>`).join("")}</div>
    ${L.claims.length ? L.calls.map((call) => `<h3>${month(call.date)} call</h3>
      ${L.claims.filter((x) => x.call === call.date).map((x) => claim(x, call)).join("") || `<p class="note">No quantified guidance on this call.</p>`}`).join("") : ""}
    ${L.raw.length ? `<h3>Guidance-like sentences (unverified)</h3><p class="note">${s.llm ? "The model found no quantified promises."
      : "Add a free GROQ_API_KEY to extract and check promises. Until then, the regex prefilter's picks:"}</p>
      ${L.raw.map((x) => `<blockquote>${esc(x.text)} <small>p${x.page}</small></blockquote>`).join("")}` : ""}
    ${points("credibility", "Promised vs. delivered")}${points("bull", "Bull case")}${points("bear", "Bear case")}
    ${a?.removed ? `<p class="note">${a.removed} model statement(s) were dropped because they cited unknown sources or numbers absent from the inputs.</p>` : ""}
    ${button}<p class="note">Built ${esc(L.built)}</p></div>`;
}

/* ---------- Settings ---------- */

async function settings() {
  const [s, st] = await Promise.all([api("settings"), api("status")]);
  const learned = Object.entries(s.weights);
  view.innerHTML = `
    <form class="settings" data-form="settings">
      <h2>Push me about</h2>
      <div class="chips">${Object.keys(LABEL).filter((k) => k !== "unclassified").map((k) =>
        `<label class="chip"><input type="checkbox" name="watch" value="${esc(k)}" ${s.watch.includes(k) ? "checked" : ""}>${LABEL[k]}</label>`).join("")}</div>
      <h2>Filtering</h2>
      <label>Push when materiality is at least <input name="push_min" type="number" step="0.05" min="0" max="1" value="${s.push_min}"></label>
      <label>Collapse as routine below <input name="routine_below" type="number" step="0.05" min="0" max="1" value="${s.routine_below}"></label>
      <label>Maximum pushes per day <input name="max_push" type="number" min="0" value="${s.max_push}"></label>
      <button class="primary">Save</button>
    </form>
    <h2>Learned from "less like this"</h2>
    <div class="card">${learned.map(([k, w]) => `<div class="kv"><span>${esc(LABEL[k] || k)}</span><b>× ${w}</b></div>`).join("")
      || `<p class="note">Nothing yet. Tap "Less like this" on a card.</p>`}
      ${learned.length ? `<button data-reset>Reset</button>` : ""}</div>
    <h2>System</h2>
    <div class="card">
      <div class="kv"><span>Model</span><b>${st.llm ? esc(st.llm) : "off: add GROQ_API_KEY"}</b></div>
      <div class="kv"><span>Telegram push</span><b>${st.telegram ? "on" : "off"}</b></div>
      <div class="kv"><span>Last filings poll</span><b>${st.last_poll ? `${ago(st.last_poll)} ago` : "never"}</b></div>
      <div class="kv"><span>Last end-of-day scan</span><b>${st.last_eod ? `${ago(st.last_eod)} ago` : "never"}</b></div>
    </div>`;
}

/* ---------- Wiring ---------- */

const views = { today, alerts, research, settings };

async function route() {
  const [tab, arg] = location.hash.slice(1).split("/");
  const name = views[tab] ? tab : "today";
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.hash === `#${name}`));
  try {
    await views[name](arg && decodeURIComponent(arg).toUpperCase());
  } catch (err) {
    view.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
  }
}

async function showStatus(s) {
  s = s || (await api("status"));
  document.getElementById("status").textContent =
    `${s.portfolio.length} stocks · ${s.last_poll ? `updated ${ago(s.last_poll)} ago` : "first fetch running…"}${s.llm ? "" : " · model off"}`;
}

async function busy(button, label, work) {
  const text = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    await work();
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
    button.textContent = text;
  }
}

view.addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target, data = new FormData(form), button = form.querySelector("button");
  if (form.dataset.form === "search") location.hash = `#research/${data.get("q").trim().toUpperCase()}`;
  if (form.dataset.form === "thresholds") {
    await busy(button, "Rescanning…", async () => {
      await put("settings", { move_pct: +data.get("move_pct"), vol_mult: +data.get("vol_mult") });
      await post("refresh?prices=true");
      await alerts();
    });
  }
  if (form.dataset.form === "settings") {
    await busy(button, "Saving…", async () => {
      await put("settings", { watch: data.getAll("watch"), push_min: +data.get("push_min"),
                              routine_below: +data.get("routine_below"), max_push: +data.get("max_push") });
      toast("Saved");
    });
  }
});

view.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.hours) {
    [state.hours, state.chosen] = [+b.dataset.hours, true];
    await route();
  } else if (b.dataset.less) {
    await busy(b, "…", async () => {
      await post("feedback", { category: b.dataset.less, more: false });
      toast(`Fewer ${LABEL[b.dataset.less] || b.dataset.less} filings from now on`);
      await route();
    });
  } else if (b.dataset.ledger) {
    await busy(b, "Reading four earnings calls (a minute or two)…", async () => {
      await post(`company/${encodeURIComponent(b.dataset.ledger)}/ledger`);
      await route();
    });
  } else if ("reset" in b.dataset) {
    await put("settings", { weights: {} });
    await route();
  }
});

document.getElementById("refresh").addEventListener("click", (e) =>
  busy(e.currentTarget, "…", async () => showStatus(await post("refresh")).then(route)));

window.addEventListener("hashchange", route);
route();
showStatus();
setInterval(showStatus, 60000);
