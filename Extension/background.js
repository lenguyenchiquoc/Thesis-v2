// Service worker: captures a tab's traffic via chrome.debugger (no DevTools) and
// buffers it in chrome.storage.session, NOT in memory — MV3 can recycle the worker
// at any time, which would otherwise lose the capture and leave "Complete" dead.
// Event listeners are registered at top level so they survive a worker restart.

const PROTOCOL_VERSION = "1.3";
const keyFor = (tabId) => `cap_${tabId}`;

// Serialize read-modify-write so concurrent network events don't clobber storage.
let writeChain = Promise.resolve();
function update(tabId, fn) {
  writeChain = writeChain.then(async () => {
    const key = keyFor(tabId);
    const data = (await chrome.storage.session.get(key))[key] || { capturing: false, requests: {} };
    fn(data);
    await chrome.storage.session.set({ [key]: data });
  }).catch(() => {});
  return writeChain;
}
async function read(tabId) {
  const key = keyFor(tabId);
  return (await chrome.storage.session.get(key))[key] || { capturing: false, requests: {} };
}

function target(tabId) { return { tabId }; }

function sendCommand(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(target(tabId), method, params || {}, (res) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(res);
    });
  });
}

// ---- capture ----
chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source.tabId;
  if (method === "Network.requestWillBeSent") {
    const r = params.request;
    update(tabId, (d) => {
      if (!d.capturing) return;
      d.requests[params.requestId] = {
        startedDateTime: new Date().toISOString(),
        request: { method: r.method, url: r.url, headers: r.headers || {},
                   postData: r.postData, hasPostData: r.hasPostData || false },
        response: { status: 0 },
      };
    });
  } else if (method === "Network.responseReceived") {
    update(tabId, (d) => {
      if (d.requests[params.requestId]) d.requests[params.requestId].response.status = params.response.status;
    });
  } else if (method === "Network.requestWillBeSentExtraInfo") {
    update(tabId, (d) => {
      if (!d.capturing) return;
      d.extraHeaders = d.extraHeaders || {};
      d.extraHeaders[params.requestId] = params.headers || {};
    });
  }
});

chrome.debugger.onDetach.addListener((source) => {
  // Keep the buffer (user may still Complete), just mark not capturing.
  update(source.tabId, (d) => { d.capturing = false; });
});

async function startCapture(tabId) {
  let origin = null;
  try { const tab = await chrome.tabs.get(tabId); origin = new URL(tab.url).origin; } catch (_) {}
  await new Promise((resolve, reject) => {
    chrome.debugger.attach(target(tabId), PROTOCOL_VERSION, () => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve();
    });
  });
  await sendCommand(tabId, "Network.enable");
  await update(tabId, (d) => { d.capturing = true; d.requests = {}; d.extraHeaders = {}; d.origin = origin; });
}

// ---- HAR building ----
const IGNORE_EXT = /\.(css|js|png|jpe?g|gif|svg|ico|woff2?|ttf|map|mp4|mp3)(\?|$)/i;
const headerArray = (o) => Object.entries(o || {}).map(([name, value]) => ({ name, value: String(value) }));
function mergeHeaders(base, extra) {
  const out = {};
  const seen = {};
  for (const [k, v] of Object.entries(base || {})) { out[k] = v; seen[k.toLowerCase()] = k; }
  for (const [k, v] of Object.entries(extra || {})) {
    const prev = seen[k.toLowerCase()];
    if (prev !== undefined && prev !== k) delete out[prev];
    out[k] = v; seen[k.toLowerCase()] = k;
  }
  return out;
}
function parseCookies(headers) {
  const h = Object.entries(headers || {}).find(([k]) => k.toLowerCase() === "cookie");
  if (!h) return [];
  return h[1].split(";").map((p) => {
    const i = p.indexOf("="); return i < 0 ? null : { name: p.slice(0, i).trim(), value: p.slice(i + 1).trim() };
  }).filter(Boolean);
}
function parseQuery(url) {
  try { return [...new URL(url).searchParams.entries()].map(([name, value]) => ({ name, value })); }
  catch (_) { return []; }
}
const contentTypeOf = (h) => { const c = Object.entries(h || {}).find(([k]) => k.toLowerCase() === "content-type"); return c ? c[1] : "application/octet-stream"; };

async function buildHar(tabId, data) {
  const entries = [];
  const origin = data.origin;
  for (const [requestId, e] of Object.entries(data.requests || {})) {
    const r = e.request;
    if (IGNORE_EXT.test(r.url) || !/^https?:/i.test(r.url)) continue;
    // Only the app under test — drop third-party analytics/CDN noise that would
    // otherwise blow the scan up to thousands of irrelevant vectors.
    if (origin) { try { if (new URL(r.url).origin !== origin) continue; } catch (_) { continue; } }
    const mergedHeaders = mergeHeaders(r.headers, (data.extraHeaders || {})[requestId] || {});
    let postData;
    if (r.postData !== undefined) {
      postData = { mimeType: contentTypeOf(mergedHeaders), text: r.postData };
    } else if (r.hasPostData) {
      try { const res = await sendCommand(tabId, "Network.getRequestPostData", { requestId });
            if (res && res.postData) postData = { mimeType: contentTypeOf(mergedHeaders), text: res.postData }; }
      catch (_) {}
    }
    const entry = {
      startedDateTime: e.startedDateTime,
      request: { method: r.method, url: r.url, httpVersion: "HTTP/1.1",
        headers: headerArray(mergedHeaders), queryString: parseQuery(r.url), cookies: parseCookies(mergedHeaders),
        headersSize: -1, bodySize: postData ? (postData.text || "").length : 0 },
      response: { status: e.response.status, statusText: "", httpVersion: "HTTP/1.1",
        headers: [], cookies: [], content: {}, redirectURL: "", headersSize: -1, bodySize: -1 },
      cache: {}, timings: { send: 0, wait: 0, receive: 0 },
    };
    if (postData) entry.request.postData = postData;
    entries.push(entry);
  }
  return { log: { version: "1.2", creator: { name: "EthicalQuoc Capture", version: "1.0" }, entries } };
}

async function stopCapture(tabId) {
  const data = await read(tabId);
  const har = await buildHar(tabId, data);
  try { await new Promise((resolve) => chrome.debugger.detach(target(tabId), () => resolve())); } catch (_) {}
  await chrome.storage.session.remove(keyFor(tabId));
  return har;
}

// ---- messaging ----
async function setScan(state) { await chrome.storage.local.set({ scan: state }); }

// Builds the HAR and hands it to the server, which runs the (possibly slow) scan
// in its OWN thread and returns a job id immediately. The popup then polls the
// server for the result — so neither the service worker nor the popup needs to
// stay alive through a long scan.
async function runScan(tabId, server, oob) {
  await setScan({ status: "scanning", phase: "Building HAR…", server });
  const har = await stopCapture(tabId);
  const count = har.log.entries.length;
  if (!count) { await setScan({ status: "empty" }); return; }
  try {
    const body = { har, replay: true };
    if (oob) body.oob_domain = oob;
    const r = await fetch(`${server}/scan`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error("server HTTP " + r.status);
    const data = await r.json();
    if (data.error || !data.job_id) throw new Error(data.error || "no job id");
    await setScan({ status: "scanning", phase: `Captured ${count} requests — scanning…`, count,
                    server, job: data.job_id });
  } catch (e) {
    await setScan({ status: "error", error: String((e && e.message) || e) });
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.cmd === "start") {
        await startCapture(msg.tabId);
        await setScan({ status: "idle" });
        sendResponse({ ok: true, capturing: true });
      } else if (msg.cmd === "scan") {
        // Fire-and-forget: run in background, popup polls chrome.storage for result.
        runScan(msg.tabId, msg.server, msg.oob);
        sendResponse({ ok: true, started: true });
      } else if (msg.cmd === "status") {
        const d = await read(msg.tabId);
        sendResponse({ ok: true, capturing: !!d.capturing, count: Object.keys(d.requests || {}).length });
      } else if (msg.cmd === "cancel") {
        await stopCapture(msg.tabId);
        await setScan({ status: "idle" });
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: "unknown cmd" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String((e && e.message) || e) });
    }
  })();
  return true; // keep the message channel open for the async sendResponse
});
