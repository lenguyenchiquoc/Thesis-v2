"""Local bridge server for the browser extension (ethicalquoc serve).

The Chrome extension captures a HAR in the browser and POSTs it here; this server
runs the same pipeline the CLI uses and returns findings as JSON. It binds to
127.0.0.1 only — the HAR carries real session cookies/tokens, so it must never
leave the machine. Uses the Python standard library only (no extra dependency),
so it runs identically on Windows / macOS / Linux.
"""

import json
import threading
import uuid
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Scanner.har_loader import HarLoader
from Analyze.postfiltered import VectorFiltering
from Analyze.cleanfilter import cleanfilter
from Replay.replay_request import ReplayRequest
from main import _analyze_one, _apply_replay_confirmation

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8099
# Only the browser extension (any id) may call us; the page's own scripts cannot.
ALLOWED_ORIGIN_PREFIX = "chrome-extension://"

# Scans run in a background thread (payload generation via java/php/etc. can take
# a while) so the HTTP request returns a job id immediately. The extension polls
# /result — this way a long scan never depends on the browser keeping a request
# (or its service worker) alive. Jobs are kept in memory until the server stops.
_jobs = {}
_jobs_lock = threading.Lock()


def _run_job(job_id, har, do_replay):
    try:
        result = run_pipeline(har, do_replay=do_replay)
        with _jobs_lock:
            _jobs[job_id] = {"status": "done", "result": result}
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": str(e)}


def run_pipeline(har_data: dict, do_replay: bool = True) -> dict:
    """scan -> analyze -> (optional) assess on an in-memory HAR; returns findings."""
    loader = HarLoader(file_path=None)
    vectors = loader.parse_data(har_data)

    filtered = VectorFiltering({"vectors": vectors}).filter()
    cleaned = cleanfilter(filtered)._clean_all()

    replayer = ReplayRequest() if do_replay else None
    findings = []
    for vector in cleaned:
        entry = _analyze_one(vector)
        fp = entry["fingerprint"]
        ex = entry["exploit_analysis"]
        mutations = [m for m in entry["mutations"] if "error" not in m]

        likely = False
        indicators: list[str] = []
        attempts = []  # full per-payload evidence, for the detailed report
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
                    })
                    continue
                base = result.get("baseline", {})
                mut = result.get("mutated", {})
                vuln = bool(result.get("likely_vulnerable"))
                attempts.append({
                    "payload_type": mutation.get("type"),
                    "chain": mutation.get("chain"),
                    "payload": mutation.get("payload_raw") or mutation.get("payload"),
                    "likely_vulnerable": vuln,
                    "indicators": result.get("indicators", []),
                    "baseline": {"status": base.get("status"), "length": base.get("length"),
                                 "body_sample": (base.get("body_sample") or "")[:800]},
                    "mutated": {"status": mut.get("status"), "length": mut.get("length"),
                                "body_sample": (mut.get("body_sample") or "")[:800]},
                })
                if vuln and not likely:
                    likely = True
                    indicators = result.get("indicators", [])
                if not indicators:
                    indicators = result.get("indicators", [])

        findings.append({
            "url": entry["vector"].get("url"),
            "method": entry["vector"].get("method"),
            "location": entry["vector"].get("location"),
            "name": entry["vector"].get("name"),
            "type": fp.get("type"),
            "subtype": fp.get("subtype"),
            "confidence": fp.get("confidence"),
            "risk_level": fp.get("risk_level"),
            "exploit_type": ex.get("exploit_type"),
            "suggested_probe": ex.get("suggested_probe"),
            "severity": ex.get("severity"),
            "confirmation_status": ex.get("confirmation_status"),
            "notes": ex.get("notes"),
            "normalized": entry.get("normalized", [])[:3],
            "mutations_count": len(mutations),
            "likely_vulnerable": likely,
            "indicators": indicators,
            "attempts": attempts,
        })

    findings.sort(key=lambda f: (not f["likely_vulnerable"], f["type"] == "Unknown"))
    return {
        "target": loader.target_name,
        "stats": {
            "vectors_scanned": len(vectors),
            "after_filter": len(cleaned),
            "findings": len(findings),
            "likely_vulnerable": sum(1 for f in findings if f["likely_vulnerable"]),
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
            # The extension/popup closed before we finished (e.g. a long scan while
            # the popup was closed). Nothing to send to; don't crash the thread.
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
            har = payload.get("har", payload)  # accept {"har": {...}} or a raw HAR
            do_replay = bool(payload.get("replay", True)) if isinstance(payload, dict) else True
            job_id = uuid.uuid4().hex
            with _jobs_lock:
                _jobs[job_id] = {"status": "running"}
            threading.Thread(target=_run_job, args=(job_id, har, do_replay), daemon=True).start()
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
