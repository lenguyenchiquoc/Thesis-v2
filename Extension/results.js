function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function render(data) {
  const s = data.stats || {};
  document.getElementById("sub").innerHTML =
    `Target <b>${esc(data.target)}</b> · ${s.findings} findings · ` +
    `<span style="color:${s.likely_vulnerable ? "#dc2626" : "#059669"}">${s.likely_vulnerable} likely vulnerable</span> · ` +
    `${s.vectors_scanned} vectors scanned · generated ${new Date().toLocaleString()}`;

  const box = document.getElementById("findings");
  box.innerHTML = "";
  if (!(data.findings || []).length) { box.innerHTML = `<div class="empty">No deserialization-related vectors found.</div>`; return; }

  for (const f of data.findings) {
    const div = document.createElement("div");
    div.className = "finding" + (f.likely_vulnerable ? " vuln" : "");
    const badge = f.likely_vulnerable ? `<span class="badge vuln">LIKELY VULN</span>`
                                      : `<span class="badge safe">${f.type === "Unknown" ? "unknown" : "suspected"}</span>`;
    let h = `<div class="ftop"><div><b>${esc(f.type)}</b> · ${esc(f.subtype || f.exploit_type || "-")}</div>${badge}</div>`;
    h += `<div class="ep">${esc(f.method)} ${esc(f.url)} &nbsp;[${esc(f.location)}/${esc(f.name)}]</div>`;
    h += `<div class="kv">Severity: ${esc(f.severity)} · ${esc(f.confirmation_status)} · confidence=${esc(f.confidence)} · probe=${esc(f.suggested_probe)}</div>`;
    if (f.notes) h += `<div class="kv">${esc(f.notes)}</div>`;
    if (f.normalized && f.normalized.length) h += `<div class="kv">Normalized candidate:</div><pre>${esc(f.normalized[0])}</pre>`;

    for (const a of f.attempts || []) {
      h += `<div class="attempt">`;
      h += `<div><b>${esc(a.payload_type)}</b>${a.chain ? " · " + esc(a.chain) : ""}` +
           (a.likely_vulnerable ? ` <span class="badge vuln">vuln</span>` : "") +
           (a.skipped ? ` <span class="badge safe">skipped</span>` : "") + `</div>`;
      if (a.payload) h += `<div class="kv">Payload sent:</div><pre>${esc(a.payload)}</pre>`;
      if (a.reason) h += `<div class="kv">Skipped: ${esc(a.reason)}</div>`;
      if (a.baseline) {
        h += `<div class="kv">Baseline → Mutated: ${a.baseline.status} (${a.baseline.length}b) → ${a.mutated.status} (${a.mutated.length}b)</div>`;
        if (a.mutated.body_sample) h += `<div class="kv">Mutated response:</div><pre>${esc(a.mutated.body_sample)}</pre>`;
      }
      for (const ind of (a.indicators || [])) h += `<div class="ind">• ${esc(ind)}</div>`;
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

chrome.storage.local.get("lastReport", ({ lastReport }) => {
  if (!lastReport) { document.getElementById("findings").innerHTML = "<div class='empty'>No report data.</div>"; return; }
  render(lastReport);
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  document.getElementById("dlJson").onclick = () => download(`ethicalquoc-report-${ts}.json`, JSON.stringify(lastReport, null, 2), "application/json");
  document.getElementById("dlHtml").onclick = () => download(`ethicalquoc-report-${ts}.html`, toHtml(lastReport), "text/html");
  document.getElementById("print").onclick = () => window.print();
});
