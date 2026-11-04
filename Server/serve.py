"""Local bridge server for the browser extension (ethicalquoc serve).

The Chrome extension captures a HAR in the browser and POSTs it here; this server
runs the same pipeline the CLI uses and returns findings as JSON. It binds to
127.0.0.1 only — the HAR carries real session cookies/tokens, so it must never
leave the machine. Uses the Python standard library only (no extra dependency),
so it runs identically on Windows / macOS / Linux.
"""

import json
import threading
import time
import uuid
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Scanner.har_loader import HarLoader
from Analyze.postfiltered import VectorFiltering
from Analyze.cleanfilter import cleanfilter
from Replay.replay_request import ReplayRequest
from main import _analyze_one, _apply_replay_confirmation, _escalate_severity
from tool_config import (set_oob_override, get_oob_domain,
                         get_oob_collector_url, get_oob_wait_seconds)


def _collector_alive(collector_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{collector_url.rstrip('/')}/_health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _poll_oob(collector_url: str, token: str) -> int:
    """Return how many OOB callbacks the collector logged for this token."""
    try:
        url = f"{collector_url.rstrip('/')}/_hits?token={urllib.parse.quote(token)}"
        with urllib.request.urlopen(url, timeout=3) as r:
            return int(json.loads(r.read().decode("utf-8")).get("count", 0))
    except Exception:
        return 0


def _oob_confirm(findings: list, token_by_idx: dict, base_domain: str):
    """After replay, poll the self-hosted collector and elevate any finding whose
    unique per-vector token received an out-of-band callback (DNS/HTTP) to
    dynamic-strong — this is the only path that reaches 'strong' on blind labs where
    the in-band control probe downgrades everything. No-op (and silent) when OOB is
    not configured or the collector is unreachable, so detect-only runs are unaffected."""
    collector_url = get_oob_collector_url()
    if not (base_domain and token_by_idx and collector_url):
        return
    if not _collector_alive(collector_url):
        print(f"    [oob] collector {collector_url} unreachable — skipping OOB confirmation")
        return
    wait = get_oob_wait_seconds()
    if wait > 0:
        print(f"    [oob] waiting {wait:.0f}s for out-of-band callbacks…")
        time.sleep(wait)
    for idx, token in token_by_idx.items():
        hits = _poll_oob(collector_url, token)
        if hits > 0:
            f = findings[idx]
            f["evidence"] = "dynamic-strong"
            f["oob_confirmed"] = True
            f["indicators"] = [
                f"OOB callback received ({hits} hit(s)) on token {token} — confirmed "
                f"out-of-band interaction: the payload was deserialized and executed"
            ] + list(f.get("indicators", []))
            print(f"    [oob] CONFIRMED strong: {f.get('location')}/{f.get('name')} "
                  f"{f.get('url')} ({hits} hit(s))")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8099
ALLOWED_ORIGIN_PREFIX = "chrome-extension://"

_jobs = {}
_jobs_lock = threading.Lock()


def _run_job(job_id, har, do_replay, oob_domain=None):
    try:
        result = run_pipeline(har, do_replay=do_replay, oob_domain=oob_domain)
        with _jobs_lock:
            _jobs[job_id] = {"status": "done", "result": result}
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": str(e)}


def run_pipeline(har_data: dict, do_replay: bool = True, oob_domain: str | None = None) -> dict:
    """scan -> analyze -> (optional) assess on an in-memory HAR; returns findings.

    oob_domain, when provided (e.g. typed in the extension UI), overrides config.json /
    env for this scan so URLDNS / blind-SSRF canaries embed the caller's Collaborator /
    Interactsh subdomain. Set fresh each run (clears when empty) — see set_oob_override."""
    set_oob_override(oob_domain)
    loader = HarLoader(file_path=None)
    vectors = loader.parse_data(har_data)

    filtered = VectorFiltering({"vectors": vectors}).filter()
    cleaned = cleanfilter(filtered)._clean_all()

    base_oob = get_oob_domain()
    token_by_idx: dict[int, str] = {}
    replayer = ReplayRequest() if do_replay else None
    findings = []
    for vector in cleaned:
        oob_token = None
        if base_oob and replayer:
            # Unique per-vector OOB token so a callback maps back to THIS finding.
            oob_token = uuid.uuid4().hex[:12]
            set_oob_override(f"{oob_token}.{base_oob}")
        entry = _analyze_one(vector)
        fp = entry["fingerprint"]
        ex = entry["exploit_analysis"]
        mutations = [m for m in entry["mutations"] if "error" not in m]

        any_strong = False
        indicators: list[str] = []
        attempts = []
        if replayer and mutations:
            for mutation in mutations:
                result = replayer.replay(mutation)
                if result.get("skipped"):
                    attempts.append({
                        "payload_type": mutation.get("type"),
                        "chain": mutation.get("chain"),
                        "payload": mutation.get("payload_raw") or mutation.get("payload"),
                        "skipped": True,
                        "reason": result.get("reason"),
                        "signal": "skipped",
                    })
                    continue
                base = result.get("baseline", {})
                mut = result.get("mutated", {})
                sig = result.get("signal")
                strong = sig == "strong"
                attempts.append({
                    "payload_type": mutation.get("type"),
                    "chain": mutation.get("chain"),
                    "payload": mutation.get("payload_raw") or mutation.get("payload"),
                    "signal": sig,
                    "indicators": result.get("indicators", []),
                    "baseline": {"status": base.get("status"), "length": base.get("length"),
                                 "body_sample": (base.get("body_sample") or "")[:800]},
                    "mutated": {"status": mut.get("status"), "length": mut.get("length"),
                                "body_sample": (mut.get("body_sample") or "")[:800]},
                })
                if strong and not any_strong:
                    any_strong = True
                    indicators = result.get("indicators", [])
                if not indicators:
                    indicators = result.get("indicators", [])

        severity, severity_note = _escalate_severity(
            ex.get("severity"),
            [(a.get("mutated") or {}).get("body_sample") or "" for a in attempts],
            [ind for a in attempts for ind in a.get("indicators", [])],
        )
        sent_any = any(not a.get("skipped") for a in attempts)
        evidence = "dynamic-strong" if any_strong else ("dynamic-weak" if sent_any else "static-only")
        findings.append({
            "url": entry["vector"].get("url"),
            "method": entry["vector"].get("method"),
            "location": entry["vector"].get("location"),
            "name": entry["vector"].get("name"),
            "occurrences": entry["vector"].get("occurrences", 1),
            "oob_token": oob_token,
            "type": fp.get("type"),
            "subtype": fp.get("subtype"),
            "confidence": fp.get("confidence"),
            "exploit_type": ex.get("exploit_type"),
            "suggested_probe": ex.get("suggested_probe"),
            "severity": severity,
            "severity_note": severity_note,
            "evidence": evidence,
            "notes": ex.get("notes"),
            "normalized": entry.get("normalized", [])[:3],
            "mutations_count": len(mutations),
            "indicators": indicators,
            "attempts": attempts,
        })
        if oob_token:
            token_by_idx[len(findings) - 1] = oob_token

    _oob_confirm(findings, token_by_idx, base_oob)

    _rank = {"dynamic-strong": 0, "dynamic-weak": 1, "static-only": 2}
    findings.sort(key=lambda f: (_rank.get(f["evidence"], 3), f["type"] == "Unknown"))
    return {
        "target": loader.target_name,
        "disclaimer": "All findings are Suspected — the tool flags candidates and never auto-confirms; verify each manually.",
        "stats": {
            "vectors_scanned": len(vectors),
            "after_filter": len(cleaned),
            "findings": len(findings),
            "dynamic_strong": sum(1 for f in findings if f["evidence"] == "dynamic-strong"),
        },
        "findings": findings,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "EthicalQuoc/1.0"

    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin.startswith(ALLOWED_ORIGIN_PREFIX):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            print("    [extension] client disconnected before response was sent")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "service": "ethicalquoc", "version": "1.0"})
        elif parsed.path == "/result":
            job_id = urllib.parse.parse_qs(parsed.query).get("job", [None])[0]
            with _jobs_lock:
                job = _jobs.get(job_id)
            if not job:
                self._json(404, {"error": "unknown job"})
            else:
                self._json(200, job)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/scan":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            har = payload.get("har", payload)
            do_replay = bool(payload.get("replay", True)) if isinstance(payload, dict) else True
            oob_domain = payload.get("oob_domain") if isinstance(payload, dict) else None
            job_id = uuid.uuid4().hex
            with _jobs_lock:
                _jobs[job_id] = {"status": "running"}
            threading.Thread(target=_run_job, args=(job_id, har, do_replay, oob_domain), daemon=True).start()
            self._json(200, {"job_id": job_id})
        except Exception as e:
            self._json(400, {"error": f"scan failed: {e}"})

    def log_message(self, fmt, *args):
        print(f"    [extension] {self.address_string()} - {fmt % args}")


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"[+] EthicalQuoc server ready at http://{host}:{port} — extension can connect")
    print(f"    GET  http://{host}:{port}/health")
    print(f"    POST http://{host}:{port}/scan   (HAR in body)")
    print("    Bound to loopback only; press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down EthicalQuoc server.")
        httpd.shutdown()
