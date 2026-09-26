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
function previewFor(doc, page) {
  return { docId: doc.doc_id, page, version: null,
           quotes: (doc.cited_pages || {})[String(page)] || [] };
}

// ------------------------------------------------------------------ render
function render() {
  const scrollY = window.scrollY;
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
    <section class="panel preview">${t ? renderAnswer(t) + `<div class="preview-pane">${renderPreview(t)}</div>` : '<h2>Document preview</h2><div class="empty">Ask a question or pick a demo question.</div>'}</section>
    <aside class="right">${t ? renderRight(t) : renderRightEmpty()}</aside>
  </div>`;
  bind();
  if (t && state.preview) loadPreviewBody(t);
  window.scrollTo(0, scrollY);          // a re-render must never move the page
}

function rerenderPreview() {
  // Page navigation replaces only the preview body: the rest of the page, and the
  // operator's scroll position, stay exactly where they were.
  const t = activeTurn(), box = document.querySelector(".preview-pane");
  if (!t || !box) return render();
  const y = window.scrollY;
  box.innerHTML = renderPreview(t);
  bindPreview(t);
  loadPreviewBody(t);
  document.querySelectorAll(".doc").forEach((el) =>
    el.classList.toggle("active", el.dataset.doc === state.preview.docId));
  window.scrollTo(0, y);
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
  return `<div class="tabs"><span class="tab-title">Page preview</span><span class="spacer"></span>
    <span class="nav">${esc(p.docId)} p.<b>${p.page}</b>
      <button data-page="-1" aria-label="Previous page">&lsaquo;</button><button data-page="1" aria-label="Next page">&rsaquo;</button>
      <a href="/api/documents/${encodeURIComponent(p.docId)}/pdf#page=${p.page}" target="_blank" rel="noopener">Open PDF</a></span></div>
    <div class="viewer" id="viewer"><p class="note">Loading page...</p></div>`;
}

function loadPreviewBody(t) {
  const p = state.preview, box = document.getElementById("viewer");
  if (!box) return;
  const base = `/api/documents/${encodeURIComponent(p.docId)}/pages/${p.page}`;
  const qs = p.quotes.map((q) => "q=" + encodeURIComponent(q.slice(0, 200))).join("&");
  const img = new Image();
  img.alt = `${p.docId} page ${p.page}`;
  img.onload = () => {
    box.innerHTML = `<p class="note">${p.quotes.length ? "Passages cited in the answer are highlighted." : "Page as published."}</p>`;
    box.appendChild(img);
  };
  img.onerror = () => { box.innerHTML = '<p class="note">Page image unavailable - the PDF is not in the local library.</p>'; };
  const qq = (qs ? qs + "&" : "") + "question=" + encodeURIComponent(t.question);
  img.src = `${base}.png?${qq}`;
}

function reflectedText(v) {
  return v === true ? "Yes - reflected in the current document"
       : v === false ? "No - not yet reflected in the current document" : "Not checked";
}
function approverText(c) {
  return c.approver ? `${esc(c.approver.name)} (${esc(c.approver.role)})` : "&mdash;";
}

function renderRight(t) {
  const v = t.view;
  const eff = v.changes.filter((c) => c.effective && c.topical_scope === "answer_relevant");
  const approval = eff.length ? eff.map((c) => `
      <dl class="kv"><dt>Change notice</dt><dd><b>${esc(c.comm_id)}</b></dd>
        <dt>Channel</dt><dd>${esc(c.channel_label)}</dd>
        <dt>Decision</dt><dd>${esc(c.decision_state)}${c.decision_date ? " on " + esc(c.decision_date) : ""}</dd>
        <dt>Approver</dt><dd>${approverText(c)}</dd>
        <dt>Incorporation</dt><dd>${reflectedText(c.reflected_in_current_document)}</dd></dl>
      <h3 class="subhead">Change description</h3><p class="desc">${esc(c.summary)}</p>`).join("<hr>")
    : `<p class="muted">No approved change alters this guidance.</p>`;
  const escalation = v.escalation
    ? `<p>${esc(v.escalation)}</p>` : `<p class="muted">No escalation needed: the documentation is current for this question.</p>`;
  const done = state.escalated[t.id];
  return `
    <section class="panel ${eff.length ? "alert" : ""}"><h2>Approval evidence</h2><div class="body">${approval}
      ${eff.length ? `<a class="link-evidence" href="#/evidence/${esc(t.id)}">View approval evidence records &rarr;</a>` : ""}
    </div></section>
    <section class="panel"><h2>Escalation</h2><div class="body">${escalation}
      ${v.escalation ? `<button class="btn btn-secondary" id="escalate" ${done ? "disabled" : ""}>${done ? "Escalation noted" : "Escalate to document owner"}</button>
      <div class="escalate-note">${done ? "Demo only: no message was sent and nothing was stored." : "Demo button - it does not send anything."}</div>` : ""}
    </div></section>
    <section class="panel"><h2>Records examined</h2><div class="body">
      ${v.changes.length ? `<ul class="refused">${v.changes.map((c) => `<li><b>${esc(c.comm_id)}</b> ${c.effective ? '<span class="pill eff">alters guidance</span>' : `<span class="pill ref">${esc(c.classification.replaceAll("_", " "))}</span>`}</li>`).join("")}</ul>
      <a href="#/evidence/${esc(t.id)}">All records &rarr;</a>` : '<p class="muted">No later communications for these documents.</p>'}
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
  </div>`;
}
function recordCard(c) {
  const log = c.log.map((m) =>
    `<div class="logline ${m.is_this_record ? "this" : ""}">${esc(m.date)}  ${esc(m.channel)}  ${esc(m.comm_id)}
${esc(m.author)}
${esc(m.subject)}
${esc(m.body)}</div>`).join("");
  return `<article class="record ${c.effective ? "effective" : ""}">
    <div class="rbody"><div>
      <dl class="kv"><dt>Change notice</dt><dd class="rid">${esc(c.comm_id)}</dd>
        <dt>Channel</dt><dd>${esc(c.channel_label)}</dd>
        <dt>Decision</dt><dd>${esc(c.decision_state)}${c.decision_date ? " on " + esc(c.decision_date) : ""}</dd>
        <dt>Approver</dt><dd>${approverText(c)}</dd>
        <dt>Incorporation</dt><dd>${reflectedText(c.reflected_in_current_document)}</dd></dl>
      <h3 class="subhead">Change description</h3><p class="desc">${esc(c.summary)}</p>
    </div><div><h3 class="subhead">Approval log</h3><pre class="log">${log}</pre></div></div>
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
    state.preview = previewFor(d, firstPage(d)); rerenderPreview();
  });
  document.querySelectorAll("[data-cite-doc]").forEach((el) => el.onclick = () => {
    const d = t.view.documents.find((x) => x.doc_id === el.dataset.citeDoc);
    if (d) { state.preview = previewFor(d, Number(el.dataset.citePage)); rerenderPreview(); }
  });
  bindPreview(t);
  const esc_ = $("#escalate"); if (esc_) esc_.onclick = () => { state.escalated[t.id] = true; render(); };
}

function bindPreview(t) {
  document.querySelectorAll("[data-page]").forEach((b) => b.onclick = () => {
    const d = t.view.documents.find((x) => x.doc_id === state.preview.docId);
    const page = Math.max(1, state.preview.page + Number(b.dataset.page));
    state.preview = previewFor(d, page); rerenderPreview();
  });
}

window.addEventListener("hashchange", () => { render(); if (location.hash.startsWith("#/evidence/")) window.scrollTo(0, 0); });
loadConfig().then(render);
