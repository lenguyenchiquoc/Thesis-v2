import argparse
import io
import json
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from Scanner.har_loader import HarLoader
from Input.input_loader import InputLoader
from Output.save_output import save_output_file_type
from Analyze.postfiltered import VectorFiltering
from Analyze.cleanfilter import cleanfilter
from Analyze.normalize import DataNormalizer
from Analyze.finderprint import Fingerprint
from Analyze.ExploitabilityAnalysis import ExploitAnalyze

STEP_NAMES = {
    1: "Scan (HarLoader)",
    2: "PostFilter (VectorFiltering)",
    3: "CleanFilter",
    4: "Normalize",
    5: "Fingerprint",
    6: "ExploitabilityAnalysis",
    7: "PayloadMutation",
    8: "Replay (ReplayRequest/Assess)",
}


def main():
    parser = argparse.ArgumentParser(
        prog="debug_pipeline",
        description="Run the analyze pipeline up to a chosen stage and show that stage's output.",
    )
    parser.add_argument("-i", "--input", help="Input scan_output.json (use instead of --har to skip Stage 1)")
    parser.add_argument("--har", help="Input HAR file for Stage 1 (scan)")
    parser.add_argument(
        "--step", type=int, required=True, choices=sorted(STEP_NAMES),
        help="Which stage's output to inspect: " + ", ".join(f"{k}={v}" for k, v in STEP_NAMES.items()),
    )
    parser.add_argument("-o", "--output", help="Optional: save this stage's output to a JSON file")
    args = parser.parse_args()

    if not args.input and not args.har:
        parser.error("one of -i/--input or --har is required")
    if args.step == 1 and not args.har:
        parser.error("--step 1 requires --har")

    print(f"[*] Running pipeline up to Stage {args.step}: {STEP_NAMES[args.step]}")

    if args.har:
        total_vectors = []
        har_vectors = HarLoader(args.har).parse()
        total_vectors.extend(har_vectors)
        print(f"[+] HAR collected: {len(har_vectors)} vectors")

        print(f"[+] Stage 1 (Scan): {len(total_vectors)} vectors")
        if args.step == 1:
            if args.output:
                save_output_file_type(total_vectors, args.output, phase="scan")
            return

        file_read = {"vectors": total_vectors}
    else:
        reader = InputLoader(args.input)
        file_read = reader.load()

    vector_filtered_list = VectorFiltering(file_read).filter()
    print(f"[+] Stage 2 (PostFilter): {len(vector_filtered_list)} vectors kept")
    if args.step == 2:
        _emit(vector_filtered_list, args.output)
        return

    cleaned_vectors = cleanfilter(vector_filtered_list)._clean_all()
    print(f"[+] Stage 3 (CleanFilter): {len(cleaned_vectors)} vectors")
    if args.step == 3:
        _emit(cleaned_vectors, args.output)
        return

    if args.step < 7:
        results = []
        for vector in cleaned_vectors:
            value = vector["cleaned_value"]
            normalizer = DataNormalizer(value)
            value_normalize = normalizer.normalize()

            entry = {
                "vector": {
                    "url": vector.get("url"),
                    "method": vector.get("method"),
                    "location": vector.get("location"),
                    "name": vector.get("name"),
                    "original_value": vector.get("original_value"),
                    "cleaned_value": vector.get("cleaned_value"),
                },
                "normalized": value_normalize,
            }

            if args.step >= 5:
                fingerprint = Fingerprint(value_normalize).fingerprint_serial()
                entry["fingerprint"] = fingerprint

            if args.step >= 6:
                entry["exploit_analysis"] = ExploitAnalyze(fingerprint).analyze()

            results.append(entry)

        print(f"[+] Stage {args.step} ({STEP_NAMES[args.step]}): {len(results)} vectors")
        _emit(results, args.output)
        return

    # Step >= 7 needs the exact same normalize->fingerprint->exploit->mutate result
    # main.py's "analyze" command produces — reuse it instead of recomputing, so the
    # two entry points can never drift apart the way they did before.
    from main import _analyze_one, _apply_replay_confirmation

    results = [_analyze_one(vector) for vector in cleaned_vectors]

    if args.step == 7:
        print(f"[+] Stage 7 ({STEP_NAMES[7]}): {len(results)} vectors")
        _emit(results, args.output)
        return

    from Replay.replay_request import ReplayRequest

    replayer = ReplayRequest()
    assess_results = []
    for entry in results:
        for mutation in entry.get("mutations", []):
            replay_result = replayer.replay(mutation)
            exploit_analysis = _apply_replay_confirmation(entry.get("exploit_analysis") or {}, replay_result)
            assess_results.append({
                "exploit_analysis": exploit_analysis,
                "mutation": mutation,
                "replay": replay_result,
            })

    print(f"[+] Stage 8 (Replay): {len(assess_results)} replay results")
    _emit(assess_results, args.output)


def _emit(data, output_path):
    #print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"[+] Saved to {output_path}")


if __name__ == "__main__":
    main()
