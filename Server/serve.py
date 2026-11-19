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
from Replay.oob_confirm import oob_confirm, set_vector_oob
from main import _analyze_one, _apply_replay_confirmation, _escalate_severity
from tool_config import set_oob_override, get_oob_domain


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


def run_pipeline(har_data: dict, do_replay: bool = True, oob_domain: str | None = None,
                 stages_out: dict | None = None) -> dict:
    """scan -> analyze -> (optional) assess on an in-memory HAR; returns findings.

    oob_domain, when provided (e.g. typed in the extension UI), overrides config.json /
    env for this scan so URLDNS / blind-SSRF canaries embed the caller's Collaborator /
    Interactsh subdomain. Set fresh each run (clears when empty) — see set_oob_override.

    stages_out, when a dict is passed, is filled with per-stage artifacts
    ({"scan","analyze","assess"}) so the CLI's `run --dump-stages` can write the same
    intermediate files the staged commands produce — inspection without 4 commands.
    The extension never passes it, so its result is unchanged."""
    set_oob_override(oob_domain)
    loader = HarLoader(file_path=None)
    vectors = loader.parse_data(har_data)

    filtered = VectorFiltering({"vectors": vectors}).filter()
    cleaned = cleanfilter(filtered)._clean_all()

    base_oob = get_oob_domain()
    token_by_idx: dict[int, str] = {}
    replayer = ReplayRequest() if do_replay else None
    findings = []
    analyze_view = []   # populated only when stages_out is requested
    for vector in cleaned:
        oob_token = set_vector_oob(base_oob) if replayer else None
        entry = _analyze_one(vector)
        if stages_out is not None:
            analyze_view.append({**entry, "oob_token": oob_token})
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
            [{
                "body": (a.get("mutated") or {}).get("body_sample") or "",
                "payload": a.get("payload") or "",
                "signal": a.get("signal"),
                "indicators": a.get("indicators") or [],
            } for a in attempts],
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

    oob_status = oob_confirm(findings, token_by_idx, base_oob)

    _rank = {"dynamic-strong": 0, "dynamic-weak": 1, "static-only": 2}
    findings.sort(key=lambda f: (_rank.get(f["evidence"], 3), f["type"] == "Unknown"))

    if stages_out is not None:
        stages_out["scan"] = vectors          # raw extracted vectors
        stages_out["analyze"] = analyze_view  # fingerprint + exploit + mutations + oob_token
        stages_out["assess"] = findings       # per-vector replay detail (attempts) + evidence
    return {
        "target": loader.target_name,
        "disclaimer": "All findings are Suspected — the tool flags candidates and never auto-confirms; verify each manually.",
        "stats": {
            "vectors_scanned": len(vectors),
            "after_filter": len(cleaned),
            "findings": len(findings),
            "dynamic_strong": sum(1 for f in findings if f["evidence"] == "dynamic-strong"),
            "oob": oob_status,
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
