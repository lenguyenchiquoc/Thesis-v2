import argparse
import io
import os
import platform
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from Output.save_output import save_output_file_type, default_output_path
from Analyze.normalize import DataNormalizer
from Analyze.finderprint import Fingerprint
import json
from Analyze.ExploitabilityAnalysis import ExploitAnalyze
from Analyze.payloadMutation import PayloadMutation
VERSION = "2025.1.0.0"

_SEVERITY_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
_RCE_MARKERS = ("functorexception", "invokertransformer", "java.lang.runtime", "runtime' threw")
_DESER_MARKERS = ("objectinputstream", "invalidclassexception", "streamcorruptedexception")


def _marker_is_genuine(marker: str, body: str, payload: str, strong: bool) -> bool:
    """A severity marker counts as server-produced evidence only when the server actually
    emitted it — i.e. the marker is NOT a substring of what we sent (so it cannot be a mere
    echo), OR this same attempt independently produced a strong signal (reflection already
    ruled out). Java/.NET gadget class names (InvokerTransformer, java.lang.Runtime) are
    plaintext inside the serialized bytes, so an endpoint that reflects the raw payload would
    otherwise be mis-escalated to Critical on its own echo."""
    return marker in body and (marker not in payload or strong)


def _escalate_severity(static_severity: str, attempts) -> tuple:
    """Raise severity to the strongest replay evidence across attempts. Never lowers; returns
    (severity, note|None) with note set only when actually raised. Each attempt is judged with
    its OWN payload/signal (see _marker_is_genuine) so a reflected gadget is not counted as RCE
    evidence. Reflects observed impact; it does NOT auto-confirm (all findings remain Suspected).

    attempts: list of {body, payload, signal, indicators}."""
    best_tier = None
    best_reason = None
    for a in attempts:
        body = (a.get("body") or "").lower()
        payload = (a.get("payload") or "").lower()
        strong = a.get("signal") == "strong"
        ind_blob = " ".join((i or "").lower() for i in (a.get("indicators") or []))

        tier = reason = None
        if any(_marker_is_genuine(m, body, payload, strong) for m in _RCE_MARKERS):
            tier, reason = "Critical", "response leaked RCE evidence (gadget chain reached Runtime.exec)"
        elif any(_marker_is_genuine(m, body, payload, strong) for m in _DESER_MARKERS):
            tier, reason = "High", "response leaked deserialization evidence (ObjectInputStream processed attacker bytes)"
        elif "receivedtype" in body and "content differs" in ind_blob:
            tier, reason = "High", "response shows deserialized type changed (receivedType), confirming the payload was deserialized"

        if tier and (best_tier is None or _SEVERITY_RANK[tier] > _SEVERITY_RANK[best_tier]):
            best_tier, best_reason = tier, reason

    if best_tier and _SEVERITY_RANK[best_tier] > _SEVERITY_RANK.get(static_severity, 0):
        return best_tier, f"raised from {static_severity} — {best_reason}"
    return static_severity, None


def _apply_replay_confirmation(exploit_analysis: dict, replay_result: dict, mutation: dict | None = None) -> dict:
    result = dict(exploit_analysis)
    static_severity = result.get("severity", "Low")

    if replay_result.get("skipped"):
        result["evidence"] = "static-only"
        result["replay_note"] = replay_result.get("reason")
        return result

    mutated = replay_result.get("mutated") or {}
    indicators = replay_result.get("indicators", [])
    mutation = mutation or {}
    severity, severity_note = _escalate_severity(
        static_severity,
        [{
            "body": mutated.get("body_sample") or "",
            "payload": mutation.get("payload_raw") or mutation.get("payload") or "",
            "signal": replay_result.get("signal"),
            "indicators": indicators,
        }],
    )
    result["severity"] = severity
    result["evidence"] = "dynamic-strong" if replay_result.get("signal") == "strong" else "dynamic-weak"
    if severity_note:
        result["severity_note"] = severity_note
    result["observations"] = indicators
    result["replay_note"] = "Not auto-confirmed — review baseline/mutated response manually"
    return result


def _is_format_hint_header(vector: dict) -> bool:
    return (str(vector.get("location") or "").lower() == "header"
            and str(vector.get("name") or "").lower() == "content-type")


def _analyze_one(vector: dict) -> dict:
    value = vector["cleaned_value"]
    normalizer = DataNormalizer(value)
    value_normalize = normalizer.normalize()

    fingerprint = Fingerprint(value_normalize).fingerprint_serial()
    exploit_result = ExploitAnalyze(fingerprint).analyze()

    candidate = value_normalize[0] if value_normalize else value
    mutation_vector = dict(vector)
    mutation_vector["value"] = candidate
    mutation_vector["encoding_chain"] = normalizer.get_encoding_chain(candidate)
    mutation_vector["slot_value"] = vector.get("original_value", vector.get("value"))
    mutation_vector["transform_chain"] = (
        list(vector.get("clean_steps") or []) + normalizer.get_transform_chain(candidate)
    )
    if _is_format_hint_header(vector):
        # The Content-Type VALUE (e.g. application/x-java-serialized-object) only labels the body
        # format — it is not where the server deserializes. Injecting binary gadgets into the header
        # just fails urllib with "Invalid header value" (bug B, 2026-11-21). The body itself is a
        # separate raw_body vector and gets the payloads there.
        mutations = []
        exploit_result = dict(exploit_result)
        exploit_result["notes"] = " | ".join(filter(None, [
            exploit_result.get("notes"),
            "Content-Type header is a format hint, not an injection slot — no payload sent here; "
            "the request body is tested as its own raw_body vector",
        ]))
    else:
        mutations = PayloadMutation(exploit_result, mutation_vector).mutate()

    return {
        "vector": {
            "url": vector.get("url"),
            "method": vector.get("method"),
            "location": vector.get("location"),
            "name": vector.get("name"),
            "original_value": vector.get("original_value"),
            "occurrences": vector.get("occurrences", 1),
        },
        "normalized": value_normalize,
        "fingerprint": fingerprint,
        "exploit_analysis": exploit_result,
        "mutations": mutations,
    }


def main():
    parser = argparse.ArgumentParser(
        prog="ethicalQuoc",
        description="Insecure deserialization detection tool"
    )

    parser.add_argument("--update", action="store_true", help="Update tool")

    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_cmd = subparsers.add_parser("serve", help="Run local bridge server for the browser extension")
    serve_cmd.add_argument("--host", type=str, default="127.0.0.1", help="Bind host (loopback only by default)")
    serve_cmd.add_argument("--port", type=int, default=8099, help="Bind port")

    run_cmd = subparsers.add_parser(
        "run",
        help="Full pipeline (scan->analyze->assess->OOB) on a HAR in one shot — "
             "identical output to the browser extension (same run_pipeline)",
    )
    run_cmd.add_argument("--har", type=str, required=True, help="Input HAR file")
    run_cmd.add_argument("-o", "--output", type=str, help="Export report file (default: results/<date>/report_<time>.json)")
    run_cmd.add_argument("--oob-domain", type=str, default=None,
                         help="OOB collector domain to embed in canaries (same field the extension sends). "
                              "Omit to fall back to config.json/env, or run detect-only when none is configured.")
    run_cmd.add_argument("--no-replay", action="store_true",
                         help="Static detection only — skip replay/assess/OOB (scan->analyze stages)")
    run_cmd.add_argument("--dump-stages", action="store_true",
                         help="Also write per-stage files (<report>.scan/.analyze/.assess.json) next to "
                              "the report, for stage-by-stage inspection — one command, no 4-command chain")

    args = parser.parse_args()
    handle_arg(args)


def handle_arg(args):

    if args.update:
        print("[*] Updating EthicalQuoc...")
        return

    if args.command == "run":
        # Single source of truth: route the CLI through the EXACT same pipeline the
        # browser extension uses (Server.serve.run_pipeline), so a CLI report is
        # byte-for-byte the same shape as an extension report — same per-vector
        # finding aggregation, same severity escalation, same OOB confirmation,
        # same sort/stats. Lazy import avoids the serve<->main circular import.
        from Server.serve import run_pipeline

        if platform.system() != "Windows":
            print(
                "[!] WARNING: running on a non-Windows platform (Docker/Linux/macOS). "
                ".NET deserialization detection (ysonet gadgets: ObjectDataProvider / "
                "TypeConfuseDelegate / ActivitySurrogateSelector) cannot execute here — mono "
                "does not implement enough of the real .NET Framework CLR for these gadgets "
                "to run. An absence of .NET findings in this run means the tool could NOT "
                "test that vector class, NOT that the target is safe. For full .NET coverage, "
                "run natively on Windows or via WSL2 (see README)."
            )

        with open(args.har, "r", encoding="utf-8") as f:
            har_data = json.load(f)

        stages = {} if args.dump_stages else None
        result = run_pipeline(
            har_data,
            do_replay=not args.no_replay,
            oob_domain=args.oob_domain,
            stages_out=stages,
        )

        out_path = args.output or default_output_path("report")
        parent_dir = os.path.dirname(out_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4, ensure_ascii=False)

        if stages is not None:
            # Same single run, dumped stage-by-stage for inspection (no 4-command chain).
            base = out_path[:-5] if out_path.lower().endswith(".json") else out_path
            for phase in ("scan", "analyze", "assess"):
                save_output_file_type(
                    vectors=stages.get(phase, []),
                    target_output_name=f"{base}.{phase}.json",
                    phase=phase,
                    version=VERSION,
                )

        stats = result.get("stats", {})
        oob = stats.get("oob", {}) if isinstance(stats.get("oob"), dict) else {}
        print(
            f"[+] Vectors scanned: {stats.get('vectors_scanned')} | after filter: {stats.get('after_filter')} | "
            f"findings: {stats.get('findings')} | dynamic-strong: {stats.get('dynamic_strong')} | "
            f"OOB: {oob.get('status')}"
            + (f" (confirmed {oob.get('confirmed')})" if oob.get('status') == 'ran' else "")
        )
        print(f"[+] All findings are Suspected — tool never auto-confirms; verify each manually.")
        print(f"[+] Report saved to {out_path}")

    elif args.command == "serve":
        from Server.serve import serve
        serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()