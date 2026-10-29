function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function sevPill(sev) {
  const s = String(sev || "").toLowerCase();
  let cls = "low";
  if (s.includes("critical")) cls = "crit";
  else if (s.includes("high")) cls = "high";
  else if (s.includes("medium")) cls = "med";
  return `<span class="pill ${cls}">${esc(sev || "?")}</span>`;
}

function confPill(conf) {
  const c = String(conf || "").toLowerCase();
  const cls = c.includes("high") ? "conf-high" : c.includes("medium") ? "conf-med" : "conf-low";
  return `<span class="pill ${cls}">${esc(conf || "?")}</span>`;
}

function statusCode(code) {
  const c = Number(code) || 0;
  const cls = c >= 500 ? "err" : c >= 400 ? "warn" : c >= 200 ? "ok" : "";
  return `<span class="code ${cls}">${esc(code)}</span>`;
}

function deltaSpan(base, mut) {
  const d = (Number(mut) || 0) - (Number(base) || 0);
  if (!d) return "";
  return ` <span class="delta ${d > 0 ? "up" : "down"}">(${d > 0 ? "+" : ""}${d}b)</span>`;
}

function isStrongInd(t) {
  const s = String(t || "").toLowerCase();
  return s.includes("content differs") || s.includes("status code changed")
      || s.includes("error/exception") || s.includes("time-based")
      || s.includes("length changed significantly");
}

function evPill(ev) {
  const map = {
    "dynamic-strong": ["ev-strong", "dynamic: strong"],
    "dynamic-weak": ["ev-weak", "dynamic: weak"],
    "static-only": ["ev-static", "static only"],
  };
  const [cls, label] = map[ev] || ["ev-static", esc(ev || "static only")];
  return `<span class="pill ${cls}">${label}</span>`;
}

function sigBadge(sig) {
  if (sig === "strong") return ` <span class="badge vuln">strong</span>`;
  if (sig === "weak") return ` <span class="badge safe">weak</span>`;
  return "";
}

function render(data) {
  const s = data.stats || {};
  document.getElementById("sub").innerHTML =
    `Target <b>${esc(data.target)}</b> · ${s.findings} findings · ` +
    `<span style="color:${s.dynamic_strong ? "#dc2626" : "#059669"}">${s.dynamic_strong || 0} with strong dynamic signal</span> · ` +
    `${s.vectors_scanned} vectors scanned · generated ${new Date().toLocaleString()}` +
    (data.disclaimer ? `<div class="kv" style="margin-top:6px">${esc(data.disclaimer)}</div>` : "");

  const box = document.getElementById("findings");
  box.innerHTML = "";
  if (!(data.findings || []).length) { box.innerHTML = `<div class="empty">No deserialization-related vectors found.</div>`; return; }

  for (const f of data.findings) {
    const div = document.createElement("div");
    div.className = "finding" + (f.evidence === "dynamic-strong" ? " vuln" : "");
    let h = `<div class="ftop"><div><b>${esc(f.type)}</b> · ${esc(f.subtype || f.exploit_type || "-")}</div>${evPill(f.evidence)}</div>`;
    h += `<div class="ep">${esc(f.method)} ${esc(f.url)} &nbsp;[${esc(f.location)}/${esc(f.name)}]</div>`;
    h += `<div class="meta">` +
         `<span class="label">Severity</span>${sevPill(f.severity)}` +
         `<span class="label">confidence</span>${confPill(f.confidence)}` +
         `<span class="label">probe</span><span class="pill probe">${esc(f.suggested_probe)}</span>` +
         `</div>`;
    if (f.severity_note) h += `<div class="kv">⬆ ${esc(f.severity_note)}</div>`;
    if (f.notes) h += `<div class="kv">${esc(f.notes)}</div>`;
    if (f.normalized && f.normalized.length) h += `<div class="kv">Normalized candidate:</div><pre>${esc(f.normalized[0])}</pre>`;

    for (const a of f.attempts || []) {
      h += `<div class="attempt">`;
      h += `<div><span class="pill ptype">${esc(a.payload_type)}</span>${a.chain ? ` <span class="kv" style="display:inline">· ${esc(a.chain)}</span>` : ""}` +
           sigBadge(a.signal) +
           (a.skipped ? ` <span class="badge safe">skipped</span>` : "") + `</div>`;
      if (a.payload) h += `<div class="kv">Payload sent:</div><pre>${esc(a.payload)}</pre>`;
      if (a.reason) h += `<div class="kv">Skipped: ${esc(a.reason)}</div>`;
      if (a.baseline) {
        h += `<div class="kv">Baseline → Mutated: ${statusCode(a.baseline.status)} (${a.baseline.length}b) → ${statusCode(a.mutated.status)} (${a.mutated.length}b)${deltaSpan(a.baseline.length, a.mutated.length)}</div>`;
        if (a.mutated.body_sample) h += `<div class="kv">Mutated response:</div><pre>${esc(a.mutated.body_sample)}</pre>`;
      }
      for (const ind of (a.indicators || [])) h += `<div class="ind${isStrongInd(ind) ? " strong" : ""}">• ${esc(ind)}</div>`;
      h += `</div>`;
    }
    div.innerHTML = h;
    box.appendChild(div);
  }
}

function download(filename, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function toHtml(data) {
  // Self-contained HTML snapshot = the current page's rendered report.
  return "<!doctype html><meta charset='utf-8'><title>EthicalQuoc Report</title>" +
    "<style>" + document.querySelector("style").textContent + "</style>" +
    "<body><h1>EthicalQuoc — Scan Report</h1><div class='sub'>" +
    document.getElementById("sub").innerHTML + "</div>" +
    "<div>" + document.getElementById("findings").innerHTML + "</div></body>";
}

// Report lives in the `scan` key written by popup.js when the scan finished (single copy).
chrome.storage.local.get("scan", ({ scan }) => {
  const lastReport = scan && scan.status === "done" ? scan.data : null;
  if (!lastReport) { document.getElementById("findings").innerHTML = "<div class='empty'>No report data.</div>"; return; }
  render(lastReport);
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  document.getElementById("dlJson").onclick = () => download(`ethicalquoc-report-${ts}.json`, JSON.stringify(lastReport, null, 2), "application/json");
  document.getElementById("dlHtml").onclick = () => download(`ethicalquoc-report-${ts}.html`, toHtml(lastReport), "text/html");
  document.getElementById("print").onclick = () => window.print();
});
