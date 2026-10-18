const SERVER = "http://127.0.0.1:8099";

const $ = (id) => document.getElementById(id);
let tabId = null;

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function send(msg) {
  return new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
}

async function checkServer() {
  try {
    const r = await fetch(`${SERVER}/health`, { method: "GET" });
    const j = await r.json();
    if (j.status === "ok") {
      $("serverDot").textContent = "● server connected";
      $("serverDot").style.color = "#059669";
      $("hint").style.display = "none";
      return true;
    }
  } catch (_) { /* not running */ }
  $("serverDot").textContent = "● server offline";
  $("serverDot").style.color = "#dc2626";
  $("hint").style.display = "block";
  return false;
}

function setCapturing(on, count) {
  $("capDot").className = "dot " + (on ? "live" : "idle");
  $("capText").textContent = on ? "Capturing…" : "Idle — ready to capture.";
  $("capCount").textContent = on && count ? `(${count} requests)` : "";
  $("startBtn").style.display = on ? "none" : "inline-block";
  $("completeBtn").disabled = !on;
  $("cancelBtn").style.display = on ? "inline-block" : "none";
}

let lastReport = null;

function renderResults(data) {
  lastReport = data;
  const s = data.stats || {};
  $("summary").style.display = "block";
  $("reportRow").style.display = "flex";
  $("summary").innerHTML =
    `Target <b>${data.target || "?"}</b> — ${s.findings} findings, ` +
    `<span style="color:${s.likely_vulnerable ? "#dc2626" : "#059669"}">` +
    `${s.likely_vulnerable} likely vulnerable</span> ` +
    `<span class="muted">(${s.vectors_scanned} vectors scanned)</span>`;

  const box = $("results");
  box.innerHTML = "";
  for (const f of data.findings || []) {
    const div = document.createElement("div");
    div.className = "finding" + (f.likely_vulnerable ? " vuln" : "");
    const badge = f.likely_vulnerable
      ? `<span class="badge vuln">LIKELY VULN</span>`
      : `<span class="badge safe">${f.type === "Unknown" ? "unknown" : "suspected"}</span>`;
    const label = f.subtype || f.exploit_type || f.type || "?";
    div.innerHTML =
      `<div class="top"><span class="tag"><b>${f.type}</b> · ${label} ` +
      `<span class="muted">(click for detail)</span></span>${badge}</div>` +
      `<div class="ep">${f.method} ${f.url} <span class="muted">[${f.location}/${f.name}]</span></div>` +
      (f.indicators && f.indicators.length
        ? `<div class="muted" style="margin-top:4px;">${esc(f.indicators[0])}</div>` : "") +
      `<div class="detail" style="display:none;"></div>`;
    const detail = div.querySelector(".detail");
    div.onclick = () => {
      if (detail.style.display === "none") { detail.innerHTML = detailHtml(f); detail.style.display = "block"; }
      else detail.style.display = "none";
    };
    box.appendChild(div);
  }
  if (!(data.findings || []).length) {
    box.innerHTML = `<div class="muted">No deserialization-related vectors found.</div>`;
  }
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function detailHtml(f) {
  let h = `<div style="margin-top:6px; border-top:1px dashed #e5e7eb; padding-top:6px;">`;
  h += `<div class="muted">Severity: ${esc(f.severity)} · ${esc(f.confirmation_status)} · probe=${esc(f.suggested_probe)}</div>`;
  if (f.notes) h += `<div class="muted" style="margin-top:4px;">${esc(f.notes)}</div>`;
  if (f.normalized && f.normalized.length)
    h += `<div style="margin-top:4px;">Normalized: <span class="copy">${esc(String(f.normalized[0]).slice(0, 160))}</span></div>`;
  for (const a of f.attempts || []) {
    h += `<div style="margin-top:6px; padding:6px; background:#fff; border:1px solid #eef0f3; border-radius:6px;">`;
    h += `<div><b>${esc(a.payload_type)}</b>${a.chain ? " · " + esc(a.chain) : ""}` +
         (a.likely_vulnerable ? ` <span class="badge vuln">vuln</span>` : "") +
         (a.skipped ? ` <span class="badge safe">skipped</span>` : "") + `</div>`;
    if (a.payload) h += `<div class="copy" style="margin-top:3px; white-space:pre-wrap; word-break:break-all;">${esc(String(a.payload).slice(0, 300))}</div>`;
    if (a.reason) h += `<div class="muted">skip: ${esc(a.reason)}</div>`;
    if (a.baseline) h += `<div class="muted" style="margin-top:3px;">baseline ${a.baseline.status} (${a.baseline.length}b) → mutated ${a.mutated.status} (${a.mutated.length}b)</div>`;
    if (a.mutated && a.mutated.body_sample)
      h += `<div class="copy" style="margin-top:3px; white-space:pre-wrap; word-break:break-all;">${esc(a.mutated.body_sample.slice(0, 300))}</div>`;
    for (const ind of (a.indicators || [])) h += `<div class="muted">• ${esc(ind)}</div>`;
    h += `</div>`;
  }
  h += `</div>`;
  return h;
}

function downloadBlob(filename, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  chrome.downloads.download({ url, filename, saveAs: true }, () => setTimeout(() => URL.revokeObjectURL(url), 10000));
}

async function onComplete() {
  $("completeBtn").disabled = true;
  $("capText").textContent = "Building HAR + scanning…";
  const res = await send({ cmd: "complete", tabId });
  setCapturing(false);
  if (!res || !res.ok) {
    $("summary").style.display = "block";
    $("summary").textContent = "Capture error: " + (res ? res.error : "no response");
    return;
  }
  if (!res.count) {
    $("summary").style.display = "block";
    $("summary").textContent = "No requests captured. Did you interact with the site?";
    return;
  }
  try {
    const r = await fetch(`${SERVER}/scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ har: res.har, replay: true }),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    renderResults(data);
  } catch (e) {
    $("summary").style.display = "block";
    $("summary").textContent = "Scan failed: " + (e.message || e);
  }
}

async function init() {
  const tab = await activeTab();
  tabId = tab.id;
  await checkServer();
  const st = await send({ cmd: "status", tabId });
  setCapturing(st && st.capturing, st && st.count);

  $("startBtn").onclick = async () => {
    const ok = await checkServer();
    if (!ok) return;
    const res = await send({ cmd: "start", tabId });
    if (res && res.ok) setCapturing(true, 0);
    else { $("summary").style.display = "block"; $("summary").textContent = "Could not start: " + (res ? res.error : "?"); }
  };
  $("completeBtn").onclick = onComplete;
  $("cancelBtn").onclick = async () => { await send({ cmd: "cancel", tabId }); setCapturing(false); };

  $("downloadBtn").onclick = () => {
    if (!lastReport) return;
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadBlob(`ethicalquoc-report-${ts}.json`, JSON.stringify(lastReport, null, 2), "application/json");
  };
  $("reportBtn").onclick = async () => {
    if (!lastReport) return;
    await chrome.storage.local.set({ lastReport });
    chrome.tabs.create({ url: chrome.runtime.getURL("results.html") });
  };
}

init();
