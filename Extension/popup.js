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

function say(msg) {
  $("summary").style.display = "block";
  $("summary").textContent = msg;
  console.log("[EthicalQuoc]", msg);
}

let pollTimer = null;
function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

async function tick() {
  const { scan } = await chrome.storage.local.get("scan");
  if (!scan) { stopPoll(); return; }
  if (scan.status === "empty") { stopPoll(); say("No requests captured for this app. Click Start, use the site, then Complete — on the SAME tab."); return; }
  if (scan.status === "error") { stopPoll(); say("Scan failed: " + scan.error + " — is the server running?"); return; }
  if (scan.status === "done") { stopPoll(); renderResults(scan.data); return; }
  if (scan.status === "scanning") {
    if (!scan.job) { say(scan.phase || "Preparing…"); return; }   // still building HAR / POSTing
    say(scan.phase || "Scanning…");
    try {
      const r = await fetch(`${scan.server}/result?job=${scan.job}`);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const job = await r.json();
      if (job.status === "done") {
        stopPoll();
        await chrome.storage.local.set({ scan: { status: "done", data: job.result } });
        renderResults(job.result);
      } else if (job.status === "error") {
        stopPoll(); say("Scan failed: " + job.error);
        await chrome.storage.local.set({ scan: { status: "error", error: job.error } });
      }
      // else still running — keep polling
    } catch (e) {
      say("Waiting for server… (" + (e.message || e) + ")");
    }
  }
}
function startPoll() { stopPoll(); tick(); pollTimer = setInterval(tick, 1000); }
function applyScanState() { tick(); }

async function onComplete() {
  $("completeBtn").disabled = true;
  setCapturing(false);
  say("Building HAR…");
  const oob = ($("oobInput").value || "").trim();
  const res = await send({ cmd: "scan", tabId, server: SERVER, oob });
  if (!res || !res.ok) { say("Could not start scan: " + (res ? res.error : "no response")); return; }
  startPoll();
}

async function init() {
  const tab = await activeTab();
  tabId = tab.id;
  await checkServer();
  const st = await send({ cmd: "status", tabId });
  setCapturing(st && st.capturing, st && st.count);

  // OOB domain: remember the last value so users don't retype it each scan.
  try {
    const { oobDomain } = await chrome.storage.local.get("oobDomain");
    if (oobDomain) $("oobInput").value = oobDomain;
  } catch (_) {}
  $("oobInput").onchange = () => {
    chrome.storage.local.set({ oobDomain: ($("oobInput").value || "").trim() });
  };

  // If a scan is running or finished (popup was closed during it), resume it.
  const { scan } = await chrome.storage.local.get("scan");
  if (scan && scan.status === "scanning") startPoll();
  else if (scan && (scan.status === "done" || scan.status === "error" || scan.status === "empty")) tick();

  $("startBtn").onclick = async () => {
    const ok = await checkServer();
    if (!ok) { say("Server offline — run `python main.py serve` first."); return; }
    const res = await send({ cmd: "start", tabId });
    if (res && res.ok) { setCapturing(true, 0); say("Capturing — use the site, then reopen and click Complete."); }
    else { say("Could not start capture: " + (res ? res.error : "?") + " (close DevTools on this tab if open)"); }
  };
  $("completeBtn").onclick = onComplete;
  $("cancelBtn").onclick = async () => { await send({ cmd: "cancel", tabId }); setCapturing(false); };

  $("downloadBtn").onclick = () => {
    if (!lastReport) return;
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadBlob(`ethicalquoc-report-${ts}.json`, JSON.stringify(lastReport, null, 2), "application/json");
  };
  // results.html reads the report straight from the `scan` key (already stored when the scan
  // finished) — do NOT copy it into a second key: a large report stored twice blows the
  // chrome.storage quota, set() rejects and the tab silently never opens.
  $("reportBtn").onclick = async () => {
    if (!lastReport) return;
    try {
      await chrome.tabs.create({ url: chrome.runtime.getURL("results.html") });
    } catch (e) {
      say("Could not open report: " + (e.message || e));
    }
  };
  chrome.storage.local.remove("lastReport");   // drop the old duplicate key from earlier versions
}

init();
