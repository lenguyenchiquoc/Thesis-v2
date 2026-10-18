// Service worker: attaches the Chrome debugger (CDP) to the active tab and buffers
// network requests, so traffic is captured WITHOUT the user opening DevTools. On
// "complete" it builds a HAR from the buffered requests. The popup drives it via
// messages and does the POST to the local EthicalQuoc server itself.

const PROTOCOL_VERSION = "1.3";

// tabId -> { requests: Map<requestId, entry>, attached: bool }
const sessions = {};

function targetFor(tabId) {
  return { tabId };
}

async function sendCommand(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(targetFor(tabId), method, params || {}, (res) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(res);
    });
  });
}

function onEvent(source, method, params) {
  const tabId = source.tabId;
  const s = sessions[tabId];
  if (!s) return;

  if (method === "Network.requestWillBeSent") {
    const r = params.request;
    s.requests.set(params.requestId, {
      startedDateTime: new Date().toISOString(),
      request: {
        method: r.method,
        url: r.url,
        headers: r.headers || {},
        postData: r.postData,
        hasPostData: r.hasPostData || false,
      },
      response: { status: 0 },
    });
  } else if (method === "Network.responseReceived") {
    const e = s.requests.get(params.requestId);
    if (e) e.response.status = params.response.status;
  }
}

async function startCapture(tabId) {
  if (sessions[tabId]) return;
  sessions[tabId] = { requests: new Map(), attached: false };
  await new Promise((resolve, reject) => {
    chrome.debugger.attach(targetFor(tabId), PROTOCOL_VERSION, () => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve();
    });
  });
  sessions[tabId].attached = true;
  await sendCommand(tabId, "Network.enable");
}

const IGNORE_EXT = /\.(css|js|png|jpe?g|gif|svg|ico|woff2?|ttf|map|mp4|mp3)(\?|$)/i;

function headerArray(obj) {
  return Object.entries(obj || {}).map(([name, value]) => ({ name, value: String(value) }));
}

function parseCookies(headers) {
  const cookieHeader = Object.entries(headers || {}).find(([k]) => k.toLowerCase() === "cookie");
  if (!cookieHeader) return [];
  return cookieHeader[1].split(";").map((p) => {
    const i = p.indexOf("=");
    return i < 0 ? null : { name: p.slice(0, i).trim(), value: p.slice(i + 1).trim() };
  }).filter(Boolean);
}

function parseQuery(url) {
  try {
    const u = new URL(url);
    return [...u.searchParams.entries()].map(([name, value]) => ({ name, value }));
  } catch (_) {
    return [];
  }
}

function contentTypeOf(headers) {
  const ct = Object.entries(headers || {}).find(([k]) => k.toLowerCase() === "content-type");
  return ct ? ct[1] : "application/octet-stream";
}

async function buildHar(tabId) {
  const s = sessions[tabId];
  const entries = [];
  for (const [requestId, e] of s.requests.entries()) {
    const r = e.request;
    if (IGNORE_EXT.test(r.url)) continue;
    if (!/^https?:/i.test(r.url)) continue;

    let postData;
    if (r.postData !== undefined) {
      postData = { mimeType: contentTypeOf(r.headers), text: r.postData };
    } else if (r.hasPostData) {
      try {
        const res = await sendCommand(tabId, "Network.getRequestPostData", { requestId });
        if (res && res.postData) postData = { mimeType: contentTypeOf(r.headers), text: res.postData };
      } catch (_) { /* best effort — some bodies are gone after the request completes */ }
    }

    const entry = {
      startedDateTime: e.startedDateTime,
      request: {
        method: r.method,
        url: r.url,
        httpVersion: "HTTP/1.1",
        headers: headerArray(r.headers),
        queryString: parseQuery(r.url),
        cookies: parseCookies(r.headers),
        headersSize: -1,
        bodySize: postData ? (postData.text || "").length : 0,
      },
      response: { status: e.response.status, statusText: "", httpVersion: "HTTP/1.1",
                  headers: [], cookies: [], content: {}, redirectURL: "", headersSize: -1, bodySize: -1 },
      cache: {},
      timings: { send: 0, wait: 0, receive: 0 },
    };
    if (postData) entry.request.postData = postData;
    entries.push(entry);
  }
  return { log: { version: "1.2", creator: { name: "EthicalQuoc Capture", version: "1.0" }, entries } };
}

async function stopCapture(tabId) {
  const s = sessions[tabId];
  if (!s) return { log: { version: "1.2", entries: [] } };
  const har = await buildHar(tabId);
  if (s.attached) {
    await new Promise((resolve) => chrome.debugger.detach(targetFor(tabId), () => resolve()));
  }
  delete sessions[tabId];
  return har;
}

chrome.debugger.onEvent.addListener(onEvent);
chrome.debugger.onDetach.addListener((source) => { delete sessions[source.tabId]; });

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.cmd === "start") {
        await startCapture(msg.tabId);
        sendResponse({ ok: true, capturing: true });
      } else if (msg.cmd === "complete") {
        const har = await stopCapture(msg.tabId);
        sendResponse({ ok: true, har, count: har.log.entries.length });
      } else if (msg.cmd === "status") {
        sendResponse({ ok: true, capturing: !!sessions[msg.tabId],
                       count: sessions[msg.tabId] ? sessions[msg.tabId].requests.size : 0 });
      } else if (msg.cmd === "cancel") {
        await stopCapture(msg.tabId);
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: "unknown cmd" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e.message || e) });
    }
  })();
  return true; // async response
});
