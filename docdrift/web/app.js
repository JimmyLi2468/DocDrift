/* DocDrift operator demo page.
 *
 * Conversation history lives only in this browser tab (the `state.turns` array). It is
 * never written to localStorage or sessionStorage; reloading the page clears it. The
 * backend stores a turn only when its audit setting (DOCDRIFT_AUDIT_ENABLED) is on,
 * which is shown in the header.
 */
"use strict";

const FALLBACK_QUESTIONS = [
  "Drive M4 trips with fault 5091 after operating for ten minutes.",
  "What regular maintenance does the manual specify for softstarter S2?",
  "What tightening torque do the main terminals of contactor K2 need?",
];

const state = {
  sessionId: (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)),
  config: null,
  mode: null,          // null = backend default
  turns: [],           // {id, question, mode, view, askedAt}
  active: null,        // turn id
  preview: null,       // {docId, page, version, tab, quotes}
  busy: false,
  escalated: {},
};

// ------------------------------------------------------------------ helpers
const $ = (sel) => document.querySelector(sel);
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function statusClass(s) {
  return s === "Verified Current" ? "vc" : s === "Potential Approved Update" ? "pau" : "ie";
}
function activeTurn() { return state.turns.find((t) => t.id === state.active) || null; }
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

// ------------------------------------------------------------------ data
async function loadConfig() {
  try { state.config = await api("/api/config"); }
  catch (e) { state.config = { demo_questions: FALLBACK_QUESTIONS, audit_enabled: false,
                               governance_mode: "strict", stack: { stack: "unknown" } }; }
}

async function ask(question) {
  question = (question || "").trim();
  if (!question || state.busy) return;
  state.busy = true; render();
  try {
    const body = { question, session_id: state.sessionId };
    if (state.mode) body.mode = state.mode;
    const view = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
                                         body: JSON.stringify(body) });
    const turn = { id: view.turn_id, question, mode: view.mode, view, askedAt: new Date() };
    state.turns.unshift(turn);
    selectTurn(turn.id);
    $("#q").value = "";
  } catch (e) {
    alert("DocDrift could not answer: " + e.message);
  } finally {
    state.busy = false; render();
  }
}

function selectTurn(id) {
  state.active = id;
  const t = activeTurn();
  const first = t && t.view.guidance.flatMap((g) => g.citations)[0];
  const doc = t && (first ? t.view.documents.find((d) => d.doc_id === first.doc_id) : t.view.documents[0]);
  state.preview = doc ? previewFor(doc, first ? first.page : firstPage(doc)) : null;
  render();
}
function firstPage(doc) {
  const cited = Object.keys(doc.cited_pages || {}).map(Number);
  return cited[0] || doc.change_pages[0] || doc.compare_pages[0] || 1;
}
function previewFor(doc, page, tab) {
  return { docId: doc.doc_id, page, version: null, tab: tab || "page",
           quotes: (doc.cited_pages || {})[String(page)] || [] };
}

// ------------------------------------------------------------------ render
function render() {
  renderMeta();
  const route = location.hash.match(/^#\/evidence\/([\w-]+)/);
  if (route) return renderEvidencePage(route[1]);
  const t = activeTurn();
  $("#app").innerHTML = `
  <div class="layout">
    <section class="panel history-head"><h2>Conversation history</h2>
      <div class="body">This browser tab only. Reload clears it.</div></section>
    <section class="panel ask">
      <div class="ask-row">
        <textarea id="q" placeholder="Describe the issue, e.g. the equipment tag and what it does..." ${state.busy ? "disabled" : ""}></textarea>
        <button class="btn btn-primary" id="send" ${state.busy ? "disabled" : ""}>${state.busy ? "Checking..." : "Send"}</button>
      </div>
      <div class="demo"><span class="demo-label">Demo questions</span>
        ${demoQuestions().map((q, i) => `<button data-demo="${i}">${esc(q)}</button>`).join("")}
        <span class="mode">Governance mode ${modeToggle()}</span>
      </div>
    </section>
    <section class="panel history">${renderHistory()}</section>
    <section class="panel docs"><h2>Relevant documents</h2>${t ? renderDocs(t) : '<div class="empty">Documents for the selected question appear here.</div>'}</section>
    <section class="panel preview">${t ? renderAnswer(t) + renderPreview(t) : '<h2>Document preview</h2><div class="empty">Ask a question or pick a demo question.</div>'}</section>
    <aside class="right">${t ? renderRight(t) : renderRightEmpty()}</aside>
  </div>`;
  bind();
  if (t && state.preview) loadPreviewBody(t);
}

function demoQuestions() {
  const qs = (state.config && state.config.demo_questions) || [];
  return (qs.length >= 3 ? qs : FALLBACK_QUESTIONS).slice(0, 3);
}
function modeToggle() {
  const current = state.mode || (state.config && state.config.governance_mode) || "strict";
  return `<span class="seg">${["strict", "flexible"].map((m) =>
    `<button data-mode="${m}" class="${m === current ? "active" : ""}">${m}</button>`).join("")}</span>`;
}

function renderMeta() {
  const c = state.config || {};
  const s = c.stack || {};
  $("#meta").innerHTML = [
    `<span class="chip">Stack: ${esc(s.stack)}</span>`,
    `<span class="chip">LLM: ${esc(s.llm_active || s.llm)}</span>`,
    `<span class="chip ${c.audit_enabled ? "on" : ""}">Conversation audit: ${c.audit_enabled ? "ON - turns are stored" : "off - nothing stored"}</span>`,
    `<span class="chip">Photo OCR: ${c.operator_ocr ? "on" : "off"}</span>`,
  ].join("");
}

function renderHistory() {
  if (!state.turns.length) return '<div class="empty">No questions yet.</div>';
  return `<ol>${state.turns.map((t) => `
    <li><button data-turn="${esc(t.id)}" class="${t.id === state.active ? "active" : ""}">
      <span class="q">${esc(t.question)}</span>
      <span class="s">${esc(t.view.status)} &middot; ${esc(t.mode)} &middot; ${t.askedAt.toLocaleTimeString()}</span>
    </button></li>`).join("")}</ol>`;
}

function renderDocs(t) {
  const docs = t.view.documents;
  if (!docs.length) return '<div class="empty">No applicable documents.</div>';
  const shown = docs.filter((d) => d.role !== "searched");
  const rest = docs.filter((d) => d.role === "searched");
  const card = (d) => {
    const p = state.preview;
    const active = p && p.docId === d.doc_id;
    const cited = Object.keys(d.cited_pages);
    return `<div class="doc ${active ? "active" : ""}" data-doc="${esc(d.doc_id)}">
      <div class="id">${esc(d.doc_id)} &middot; rev ${esc(d.version)}</div>
      <div class="t">${esc(d.title)}</div>
      <div>${d.provenance === "abb_public_pdf" ? '<span class="tag abb">ABB publication</span>' : '<span class="tag syn">placeholder</span>'}
        ${d.role === "cited" ? '<span class="tag cited">cited</span>' : ""}
        ${d.role === "targeted_by_change" ? '<span class="tag change">change record</span>' : ""}</div>
      <div class="m">Effective ${esc(d.effective)}${cited.length ? ` &middot; cited p.${cited.map(esc).join(", ")}` : ""}</div>
      ${d.previous_version ? `<div class="m">Previous rev ${esc(d.previous_version)} (${esc(d.previous_effective)}) <span class="tag syn">synthetic</span></div>` : ""}
    </div>`;
  };
  return shown.map(card).join("") +
    (rest.length ? `<details class="more"><summary>${rest.length} more searched, not cited</summary>${rest.map(card).join("")}</details>` : "");
}

function renderAnswer(t) {
  const v = t.view;
  const steps = v.guidance.map((g) => `<li>${esc(g.text)}${g.citations.map((c) =>
    `<button class="cite" data-cite-doc="${esc(c.doc_id)}" data-cite-page="${c.page}">${esc(c.label)}</button>`).join("")}</li>`).join("");
  return `<div class="status"><span class="badge ${statusClass(v.status)}">${esc(v.status)}</span>
      <div class="eq">${esc(v.equipment_summary)}<small>Equipment confidence ${Number(v.equipment_confidence).toFixed(2)} &middot; mode ${esc(v.mode)}</small></div></div>
    ${v.clarification_needed ? `<div class="clarify">${esc(v.clarification_needed)}</div>` : ""}
    ${steps ? `<div class="guidance"><h3>Guidance from the current documentation</h3><ol>${steps}</ol></div>` : ""}`;
}

function renderPreview(t) {
  const p = state.preview;
  if (!p) return '<div class="empty">No document to preview.</div>';
  const doc = t.view.documents.find((d) => d.doc_id === p.docId);
  const canCompare = doc && doc.compare_pages.includes(p.page);
  const tabs = [["page", "Page"], ["text", "Extracted text"]];
  if (doc && doc.compare_pages.length) tabs.push(["compare", "Compare with previous revision"]);
  return `<div class="tabs">${tabs.map(([k, l]) =>
      `<button data-tab="${k}" class="${p.tab === k ? "active" : ""}">${l}</button>`).join("")}
    <span class="spacer"></span>
    <span class="nav">${esc(p.docId)} p.<b>${p.page}</b>
      <button data-page="-1">&lsaquo;</button><button data-page="1">&rsaquo;</button>
      <a href="/api/documents/${encodeURIComponent(p.docId)}/pdf#page=${p.page}" target="_blank" rel="noopener">Open PDF</a></span></div>
    <div class="viewer" id="viewer">${p.tab === "compare" && !canCompare
      ? `<p class="note">The previous revision covers p.${doc.compare_pages.join(", ")} of this document.</p>` : '<p class="note">Loading...</p>'}</div>`;
}

async function loadPreviewBody(t) {
  const p = state.preview, box = $("#viewer");
  if (!box) return;
  const base = `/api/documents/${encodeURIComponent(p.docId)}/pages/${p.page}`;
  try {
    if (p.tab === "page") {
      const qs = p.quotes.map((q) => "q=" + encodeURIComponent(q.slice(0, 160))).join("&");
      box.innerHTML = `<p class="note">${p.quotes.length ? "Cited passages are highlighted." : "Page as published."}</p>
        <img alt="${esc(p.docId)} page ${p.page}" src="${base}.png${qs ? "?" + qs : ""}">`;
      box.querySelector("img").onerror = () => { box.innerHTML = '<p class="note">Page image unavailable - the PDF is not in the local library.</p>'; };
    } else if (p.tab === "text") {
      const r = await api(`${base}/text`);
      box.innerHTML = `<p class="note">Rev ${esc(r.version)} &middot; ${esc(r.provenance)}</p><pre>${esc(r.text || "(no text layer on this page)")}</pre>`;
    } else {
      const doc = t.view.documents.find((d) => d.doc_id === p.docId);
      if (!doc.compare_pages.includes(p.page)) return;
      const r = await api(`${base}/compare`);
      const diff = r.diff.map((d) => d.op === "same" ? esc(d.text)
        : d.op === "removed" ? `<del>${esc(d.text)}</del>` : `<ins>${esc(d.text)}</ins>`).join(" ");
      box.innerHTML = `<div class="diffhead"><b>Rev ${esc(r.previous_version)}</b> (${esc(r.previous_effective)},
        <span class="tag syn">synthetic reconstruction - not an ABB publication</span>) &rarr; <b>rev ${esc(r.current_version)}</b> (ABB publication)
        <ul>${r.revision_history.map(([rev, d, what]) => `<li>Rev ${esc(rev)} ${esc(d)}: ${esc(what)}</li>`).join("")}</ul></div>
        <div class="diff">${diff || "(current text not indexed)"}</div>
        <p class="note"><del>struck</del> = only in the previous revision; <ins>green</ins> = added in the current revision.</p>`;
    }
  } catch (e) {
    box.innerHTML = `<p class="note">${esc(e.message)}</p>`;
  }
}

function renderRight(t) {
  const v = t.view;
  const eff = v.changes.filter((c) => c.effective && c.topical_scope === "answer_relevant");
  const refused = v.changes.filter((c) => !c.effective);
  const approval = v.approval_evidence.length
    ? `<ul class="evidence-list">${v.approval_evidence.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`
    : `<p class="muted">No approved change alters this guidance.</p>`;
  const esc_ = v.escalation
    ? `<p>${esc(v.escalation)}</p>` : `<p class="muted">No escalation needed: the documentation is current for this question.</p>`;
  const done = state.escalated[t.id];
  return `
    <section class="panel ${eff.length ? "alert" : ""}"><h2>Approval evidence</h2><div class="body">
      ${v.pending_change ? `<p><b>${esc(v.pending_change.split(":")[0])}</b></p>` : ""}${approval}
      ${v.has_unincorporated_approved_change ? `<a class="link-evidence" href="#/evidence/${esc(t.id)}">View approval evidence records &rarr;</a>` : ""}
    </div></section>
    <section class="panel"><h2>Escalation</h2><div class="body">${esc_}
      ${v.escalation ? `<button class="btn btn-secondary" id="escalate" ${done ? "disabled" : ""}>${done ? "Escalation noted" : "Escalate to document owner"}</button>
      <div class="escalate-note">${done ? "Demo only: no message was sent and nothing was stored." : "Demo button - it does not send anything."}</div>` : ""}
    </div></section>
    ${v.other_open_changes.length ? `<section class="panel"><h2>Other approved changes on this asset</h2><div class="body"><ul class="refused">${v.other_open_changes.map((o) => `<li>${esc(o)}</li>`).join("")}</ul></div></section>` : ""}
    <section class="panel"><h2>Records examined</h2><div class="body">
      ${v.changes.length ? `<ul class="refused">${v.changes.map((c) => `<li><b>${esc(c.comm_id)}</b> ${c.effective ? '<span class="pill eff">alters guidance</span>' : `<span class="pill ref">${esc(c.classification.replaceAll("_", " "))}</span>`}</li>`).join("")}</ul>
      ${refused.length ? `<a href="#/evidence/${esc(t.id)}">All records and reasons &rarr;</a>` : ""}` : '<p class="muted">No later communications for these documents.</p>'}
    </div></section>`;
}
function renderRightEmpty() {
  return `<section class="panel"><h2>Approval evidence</h2><div class="body muted">Shown when a change record bears on the answer.</div></section>
    <section class="panel"><h2>Escalation</h2><div class="body muted">Shown when the controlled document is behind an approved change.</div></section>`;
}

// ------------------------------------------------------------------ evidence page
function renderEvidencePage(turnId) {
  const t = state.turns.find((x) => x.id === turnId);
  if (!t) {
    $("#app").innerHTML = `<div class="evpage"><a class="back" href="#/">&larr; Back</a>
      <p>This conversation is no longer in the tab's memory (the page was reloaded). Ask the question again.</p></div>`;
    return;
  }
  const v = t.view;
  const order = (c) => (c.effective ? 0 : c.decision_state === "APPROVED" ? 1 : 2);
  const recs = [...v.changes].sort((a, b) => order(a) - order(b));
  $("#app").innerHTML = `<div class="evpage">
    <a class="back" href="#/">&larr; Back to the answer</a>
    <h1>Approval evidence records</h1>
    <div class="sub">${esc(v.question)} &middot; ${esc(v.equipment_summary)} &middot; governance mode <b>${esc(v.mode)}</b> &middot;
      <span class="badge ${statusClass(v.status)}">${esc(v.status)}</span></div>
    ${recs.map(recordCard).join("")}
    <p class="muted">A record alters guidance only if all nine conditions hold. Conditions shown as &ndash; were not evaluated because an earlier one failed.</p>
  </div>`;
  window.scrollTo(0, 0);
}
function recordCard(c) {
  const person = (p) => p ? `${esc(p.name)} (${esc(p.role)})` : "&mdash;";
  return `<article class="record ${c.effective ? "effective" : ""}">
    <header><span class="rid">${esc(c.comm_id)}</span>
      <span class="tag">${esc(c.channel.replaceAll("_", " "))}</span><span class="muted">${esc(c.date)}</span>
      <span class="pill">${esc(c.decision_state)}</span><span class="pill">authority ${esc(c.authority_state)}</span>
      ${c.effective ? '<span class="pill eff">alters guidance - not yet in the document</span>' : `<span class="pill ref">${esc(c.classification.replaceAll("_", " "))}</span>`}
    </header>
    <div class="rbody"><div>
      <p><b>${esc(c.subject)}</b></p><blockquote>${esc(c.body)}</blockquote>
      <dl class="kv"><dt>Author</dt><dd>${person(c.author)}</dd><dt>Approver</dt><dd>${person(c.approver)}</dd>
        <dt>Decision date</dt><dd>${esc(c.decision_date || "—")}</dd><dt>Formal record</dt><dd>${esc(c.formal_record || "none")}</dd>
        <dt>Change</dt><dd>${esc(c.change_ref || "—")}</dd><dt>Scope</dt><dd>${esc(c.scope || "—")}</dd>
        <dt>Affects</dt><dd>${c.affects.map((a) => `${esc(a.doc_id)} p.${a.sections.map(esc).join(", ")}`).join("; ") || "—"}</dd>
        <dt>Thread</dt><dd>${c.thread.map(esc).join(" &rarr; ") || "—"}</dd>
        ${c.invalidated_by.length ? `<dt>Invalidated by</dt><dd>${c.invalidated_by.map(esc).join(", ")}</dd>` : ""}
        ${c.incorporation ? `<dt>Incorporation</dt><dd>${esc(c.incorporation.reason)}</dd>` : ""}</dl>
    </div><div><table class="cond">${c.conditions.map((k) => `<tr>
        <td class="${k.skipped ? "skip" : k.passed ? "ok" : "no"}">${k.skipped ? "&ndash;" : k.passed ? "&#10003;" : "&#10007;"}</td>
        <td><b>${esc(k.label)}</b><br><span class="muted">${esc(k.detail)}</span></td></tr>`).join("")}</table></div></div>
  </article>`;
}

// ------------------------------------------------------------------ events
function bind() {
  const q = $("#q");
  if (q) q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q.value); } });
  const send = $("#send"); if (send) send.onclick = () => ask($("#q").value);
  document.querySelectorAll("[data-demo]").forEach((b) => b.onclick = () => ask(demoQuestions()[Number(b.dataset.demo)]));
  document.querySelectorAll("[data-mode]").forEach((b) => b.onclick = () => { state.mode = b.dataset.mode; render(); });
  document.querySelectorAll("[data-turn]").forEach((b) => b.onclick = () => selectTurn(b.dataset.turn));
  const t = activeTurn();
  document.querySelectorAll("[data-doc]").forEach((el) => el.onclick = () => {
    const d = t.view.documents.find((x) => x.doc_id === el.dataset.doc);
    state.preview = previewFor(d, firstPage(d)); render();
  });
  document.querySelectorAll("[data-cite-doc]").forEach((el) => el.onclick = () => {
    const d = t.view.documents.find((x) => x.doc_id === el.dataset.citeDoc);
    if (d) { state.preview = previewFor(d, Number(el.dataset.citePage)); render(); }
  });
  document.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => {
    state.preview.tab = b.dataset.tab;
    const d = t.view.documents.find((x) => x.doc_id === state.preview.docId);
    if (b.dataset.tab === "compare" && d && !d.compare_pages.includes(state.preview.page)) {
      state.preview = previewFor(d, d.compare_pages[0], "compare");
    }
    render();
  });
  document.querySelectorAll("[data-page]").forEach((b) => b.onclick = () => {
    const d = t.view.documents.find((x) => x.doc_id === state.preview.docId);
    const page = Math.max(1, state.preview.page + Number(b.dataset.page));
    state.preview = previewFor(d, page, state.preview.tab); render();
  });
  const esc_ = $("#escalate"); if (esc_) esc_.onclick = () => { state.escalated[t.id] = true; render(); };
}

window.addEventListener("hashchange", render);
loadConfig().then(render);
