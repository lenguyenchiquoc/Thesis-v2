import argparse
import io
import platform
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from Scanner.har_loader import HarLoader
from Output.save_output import save_output_file_type, default_output_path
from Input.input_loader import InputLoader
from Analyze.postfiltered import VectorFiltering
from Analyze.normalize import DataNormalizer
from Analyze.cleanfilter import cleanfilter
from Analyze.finderprint import Fingerprint
import json
from Analyze.ExploitabilityAnalysis import ExploitAnalyze
from Analyze.payloadMutation import PayloadMutation
from Replay.replay_request import ReplayRequest
VERSION = "2025.1.0.0"

def _apply_replay_confirmation(exploit_analysis: dict, replay_result: dict) -> dict:
    # Never auto-confirms — replay heuristics are unreliable; always leave this to manual review.
    result = dict(exploit_analysis)
    severity = result.get("severity", "Low")
    result["confirmation_status"] = "Suspected"
    result["display_severity"] = f"Suspected-{severity}"
    result["confidence_source"] = "static_signature"

    if replay_result.get("skipped"):
        result["replay_note"] = replay_result.get("reason")
        return result

    result["observations"] = replay_result.get("indicators", [])
    result["replay_note"] = "Not auto-confirmed — review baseline/mutated response manually"
    return result


def main():
    parser = argparse.ArgumentParser(
        prog="ethicalQuoc",
        description="Insecure deserialization detection tool"
    )

    parser.add_argument("--setup", action="store_true", help="Set up tool")
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument("--update", action="store_true", help="Update tool")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_cmd = subparsers.add_parser("scan", help="Scan target")
    scan_cmd.add_argument("--har", type=str, help="Input HAR file")
    scan_cmd.add_argument("-o", "--output", type=str, help="Export scan result file")

    analyze_cmd = subparsers.add_parser("analyze", help="Analyze input vectors")
    analyze_cmd.add_argument("-i", "--input", type=str, required=True, help="Input scan file")
    analyze_cmd.add_argument("-o", "--output", type=str, help="Export analyze result")

    assess_cmd = subparsers.add_parser("assess", help="Risk assessment")
    assess_cmd.add_argument("-i", "--input", type=str, required=True, help="Input analyze file")
    assess_cmd.add_argument("-o", "--output", type=str, help="Export assessment result")

    report_cmd = subparsers.add_parser("report", help="Generate report")
    report_cmd.add_argument("-i", "--input", type=str, required=True, help="Input assessment file")
    report_cmd.add_argument("--format", choices=["json", "pdf", "html"], default="json")
    report_cmd.add_argument("-o", "--output", type=str, help="Output report file")

    args = parser.parse_args()
    handle_arg(args)


def handle_arg(args):

    if args.setup:
        print("[*] Initializing environment...")
        return

    if args.version:
        print(f"EthicalQuoc version {VERSION}")
        return

    if args.update:
        print("[*] Updating EthicalQuoc...")
        return

    if args.command == "scan":

        if not args.har:
            print("[!] Error: scan requires --har")
            return

        total_vectors = []

        if args.har:
            loader = HarLoader(args.har)
            har_vectors = loader.parse()
            total_vectors.extend(har_vectors)
            print(f"[+] HAR collected: {len(har_vectors)} vectors")

        print(f"[+] Total collected: {len(total_vectors)} vectors")

        save_output_file_type(
            vectors=total_vectors,
            target_output_name=args.output or default_output_path("scan"),
            phase="scan",
            version=VERSION
        )

    elif args.command == "analyze":

        print(f"[*] Analyzing: {args.input}")

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

        results = []

        if args.input:
            reader = InputLoader(args.input)
            file_read = reader.load()
            vector_filtered = VectorFiltering(file_read)
            vector_filtered_list = vector_filtered.filter()
            print(f"[+] Vectors after filter: {len(vector_filtered_list)}")
            clean_filter = cleanfilter(vector_filtered_list)
            clean_filter.clean_and_output()

            for i in clean_filter._clean_all():
                value = i["cleaned_value"]
                normalizer = DataNormalizer(value)
                value_normalize = normalizer.normalize()
                print(f"Normalize is: {value_normalize}")
                for candidate in value_normalize:
                    fingerprint = Fingerprint([candidate]).fingerprint_serial()
                    print(json.dumps(fingerprint, indent=4, ensure_ascii=False))
                    ExploitAnalyze_rs = ExploitAnalyze(fingerprint).analyze()
                    print(json.dumps(ExploitAnalyze_rs, indent=4, ensure_ascii=False))

                    mutation_vector = dict(i)
                    mutation_vector["value"] = candidate
                    mutation_vector["encoding_chain"] = normalizer.get_encoding_chain(candidate)
                    mutations = PayloadMutation(ExploitAnalyze_rs, mutation_vector).mutate()
                    print(mutations)

                    results.append({
                        "vector": {
                            "url": i.get("url"),
                            "method": i.get("method"),
                            "location": i.get("location"),
                            "name": i.get("name"),
                            "original_value": i.get("original_value"),
                        },
                        "normalized": [candidate],
                        "fingerprint": fingerprint,
                        "exploit_analysis": ExploitAnalyze_rs,
                        "mutations": mutations,
                    })

        save_output_file_type(
            vectors=results,
            target_output_name=args.output or default_output_path("analyze"),
            phase="analyze",
            version=VERSION
        )

    elif args.command == "assess":

        print(f"[*] Assessing risk for: {args.input}")

        results = []

        if args.input:
            with open(args.input, "r", encoding="utf-8") as f:
                analyze_data = json.load(f)

            replayer = ReplayRequest()

            for entry in analyze_data.get("vectors", []):
                mutations = entry.get("mutations", [])
                if not mutations:
                    continue

                for mutation in mutations:
                    replay_result = replayer.replay(mutation)
                    print(json.dumps(replay_result, indent=4, ensure_ascii=False, default=str))

                    exploit_analysis = _apply_replay_confirmation(
                        entry.get("exploit_analysis") or {}, replay_result
                    )

                    results.append({
                        "exploit_analysis": exploit_analysis,
                        "mutation": mutation,
                        "replay": replay_result,
                    })

        save_output_file_type(
            vectors=results,
            target_output_name=args.output or default_output_path("assess"),
            phase="assess",
            version=VERSION
        )
            
    elif args.command == "report":

        print(f"[*] Generating {args.format.upper()} report from {args.input}")

        if args.format != "json":
            print(f"[!] Format '{args.format}' not implemented yet — falling back to json")

        findings = []

        if args.input:
            with open(args.input, "r", encoding="utf-8") as f:
                assess_data = json.load(f)

            for entry in assess_data.get("vectors", []):
                exploit_analysis = entry.get("exploit_analysis") or {}
                replay = entry.get("replay") or {}
                findings.append({
                    "exploit_type": exploit_analysis.get("exploit_type"),
                    "severity": exploit_analysis.get("display_severity"),
                    "score": exploit_analysis.get("score"),
                    "suggested_probe": exploit_analysis.get("suggested_probe"),
                    "notes": exploit_analysis.get("notes"),
                    "mutation": entry.get("mutation"),
                    "observations": exploit_analysis.get("observations", []),
                    "replay_note": exploit_analysis.get("replay_note"),
                    "baseline": replay.get("baseline"),
                    "mutated": replay.get("mutated"),
                })

        results = {
            "summary": {
                "total_findings": len(findings),
            },
            "findings": findings,
        }

        print(f"[+] Total findings: {len(findings)} — all require manual review, tool does not auto-confirm")

        save_output_file_type(
            vectors=results,
            target_output_name=args.output or default_output_path("report"),
            phase="report",
            version=VERSION
        )


if __name__ == "__main__":
    main()