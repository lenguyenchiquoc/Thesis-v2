"""Detection evaluation — precision / recall / F1 of EthicalQuoc's deser detection.

Runs the detection stages (Scan -> filter -> clean -> normalize -> fingerprint;
NO replay, NO phpggc/ysoserial, so it is fast and deterministic) over a set of HARs
whose ground truth is in labels.json, then counts how often the tool's flags match
the real deserialization sinks.

Ground truth is INDEPENDENT of the tool: labels.json is hand-written from the
serialization format's magic bytes. A flag is matched to a sink by its ADDRESS.

Two matching keys are reported side by side:
  (location, name)        — same cookie on many pages = ONE logical sink (collapses URL;
                            correct for a cookie deserialized by shared server code).
  (url, location, name)   — every request is its own unit (distinguishes a param that is
                            vulnerable on one endpoint but not another). A URL-less label
                            sink auto-expands to every request carrying that (location,name).

Definitions (aggregated over all HARs):
  TP = tool flagged an address that IS a labelled deser sink
  FP = tool flagged an address that is NOT a sink   (false alarm)
  FN = a labelled sink the tool did NOT flag        (miss)
  Precision = TP/(TP+FP)   Recall = TP/(TP+FN)   F1 = 2PR/(P+R)

A naive regex baseline ("any long base64/url-ish token is suspicious") runs on the same
vectors to show the signature filter discriminates better than guessing.

Usage:  python -I eval/evaluate.py [--har-dir results] [--labels eval/labels.json]
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from Scanner.har_loader import HarLoader
from Analyze.postfiltered import VectorFiltering
from Analyze.cleanfilter import cleanfilter
from Analyze.normalize import DataNormalizer
from Analyze.finderprint import Fingerprint

DESER_TYPES = {"PHP", "Java", "Ruby", "Python", ".NET", "Jackson", "YAML"}
BASELINE_RE = re.compile(r"^[A-Za-z0-9+/=_%.\-]{16,}$")


def analyze_har(har_path):
    """Return (flags, present, nvec):
       flags   = {(url, location, name): fingerprint_type}  — what the tool surfaces
       present = {(location, name): set(urls)}              — where each slot appears (all vectors)
       baseline= {(url, location, name)}                    — the naive detector's flags"""
    har = json.load(open(har_path, "r", encoding="utf-8"))
    vectors = HarLoader(har_path).parse_data(har)
    filtered = VectorFiltering({"vectors": vectors}).filter()
    cleaned = cleanfilter(filtered)._clean_all()

    flags = {}
    for v in cleaned:
        key = (v.get("url"), v.get("location"), v.get("name"))
        try:
            t = Fingerprint(DataNormalizer(v.get("cleaned_value", "")).normalize()).fingerprint_serial().get("type", "Unknown")
        except Exception:
            t = "Unknown"
        if key not in flags or (flags[key] not in DESER_TYPES and t in DESER_TYPES):
            flags[key] = t

    present = {}
    baseline = set()
    for v in vectors:
        val = v.get("value", "")
        if isinstance(val, str) and val.strip():
            present.setdefault((v.get("location"), v.get("name")), set()).add(v.get("url"))
            if BASELINE_RE.match(val):
                baseline.add((v.get("url"), v.get("location"), v.get("name")))
    return flags, present, baseline, len(vectors)


def score(flagged, sinks):
    tp = flagged & sinks
    return tp, flagged - sinks, sinks - flagged


def prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 1.0
    r = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def build_sets(flags, present, baseline, label_sinks, keymode):
    """Return (tool_flagged, tool_sinks, base_flagged) as sets at the chosen key
    granularity, plus the count of folded header/Cookie duplicates."""
    has_cookie_sink = any(loc == "cookie" for loc, _ in label_sinks)

    if keymode == "locname":
        tool = {(loc, name) for (_u, loc, name) in flags}
        base = {(loc, name) for (_u, loc, name) in baseline}
        sinks = set(label_sinks.keys())
        dup = 0
        if ("header", "Cookie") in tool and has_cookie_sink:
            tool.discard(("header", "Cookie")); dup = 1
        return tool, sinks, base, dup

    tool = set(flags.keys())
    base = set(baseline)
    sinks = set()
    for (loc, name), meta in label_sinks.items():
        want = meta.get("url_contains")
        for u in present.get((loc, name), ()):
            if want is None or (want in (u or "")):
                sinks.add((u, loc, name))
    dup = 0
    if has_cookie_sink:
        hc = {k for k in tool if k[1] == "header" and k[2] == "Cookie"}
        tool -= hc; dup = len(hc)
    return tool, sinks, base, dup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--har-dir", default=os.path.join(ROOT, "results"))
    ap.add_argument("--labels", default=os.path.join(ROOT, "eval", "labels.json"))
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    labels = {k: v for k, v in json.load(open(args.labels, encoding="utf-8")).items()
              if not k.startswith("_")}

    modes = ["locname", "url"]
    agg = {m: {"tool": [0, 0, 0], "base": [0, 0, 0], "dup": 0} for m in modes}
    type_ok = type_tp = 0
    type_conf = {}
    rows = []

    for name, lab in labels.items():
        har = os.path.join(args.har_dir, name)
        if not os.path.exists(har):
            rows.append((name, "MISSING", "", "", "")); continue
        label_sinks = {(s["location"], s["name"]): {"type": s.get("type"),
                       "url_contains": s.get("url_contains")} for s in lab.get("deser_sinks", [])}
        flags, present, baseline, nvec = analyze_har(har)

        per = {}
        for m in modes:
            tool, sinks, base, dup = build_sets(flags, present, baseline, label_sinks, m)
            ttp, tfp, tfn = score(tool, sinks)
            btp, bfp, bfn = score(base, sinks)
            agg[m]["tool"][0] += len(ttp); agg[m]["tool"][1] += len(tfp); agg[m]["tool"][2] += len(tfn)
            agg[m]["base"][0] += len(btp); agg[m]["base"][1] += len(bfp); agg[m]["base"][2] += len(bfn)
            agg[m]["dup"] += dup
            per[m] = (len(ttp), len(tfp), len(tfn))

        tool_ln = {(loc, name) for (_u, loc, name) in flags} - ({("header", "Cookie")} if ("header", "Cookie") in flags else set())
        for key in (tool_ln & set(label_sinks)):
            type_tp += 1
            pred = next(t for (u, l, n), t in flags.items() if (l, n) == key)
            want = label_sinks[key]["type"]
            type_ok += (pred == want)
            type_conf.setdefault(want, {}).setdefault(pred, 0)
            type_conf[want][pred] += 1

        det = "-" if not label_sinks else ("YES" if per["locname"][0] else "NO")
        rows.append((name, f"{nvec}v", f"{per['locname'][0]}/{per['locname'][1]}/{per['locname'][2]}",
                     f"{per['url'][0]}/{per['url'][1]}/{per['url'][2]}", lab.get("lang", "?"), det))

    print("\n=== Per-HAR (tool TP/FP/FN) ===")
    print(f"{'HAR':11} {'vectors':>8} {'(loc,name)':>12} {'(url,loc,name)':>16} {'lang':>5} {'det':>4}")
    for r in rows:
        print(f"{r[0]:11} {r[1]:>8} {r[2]:>12} {r[3]:>16} {r[4]:>5} {r[5]:>4}")

    print("\n=== Aggregate ===")
    for m in modes:
        tp, fp, fn = agg[m]["tool"]; p, r, f1 = prf(tp, fp, fn)
        btp, bfp, bfn = agg[m]["base"]; bp, br, bf1 = prf(btp, bfp, bfn)
        klabel = "(location,name)" if m == "locname" else "(url,location,name)"
        print(f"\n-- key = {klabel}   [header/Cookie dups folded: {agg[m]['dup']}]")
        print(f"   TOOL      TP={tp} FP={fp} FN={fn}  ->  P={p:.3f}  R={r:.3f}  F1={f1:.3f}")
        print(f"   BASELINE  TP={btp} FP={bfp} FN={bfn}  ->  P={bp:.3f}  R={br:.3f}  F1={bf1:.3f}")

    print(f"\nType accuracy (on tool TPs): {type_ok}/{type_tp}"
          + (f" = {type_ok/type_tp:.3f}" if type_tp else ""))
    for want, preds in sorted(type_conf.items()):
        print(f"  {want:6} -> " + ", ".join(f"{k}:{v}" for k, v in sorted(preds.items())))

    if args.json_out:
        out = {m: {"tool": dict(zip("tp fp fn".split(), agg[m]["tool"])),
                   "base": dict(zip("tp fp fn".split(), agg[m]["base"])),
                   "dup_folded": agg[m]["dup"]} for m in modes}
        out["type_accuracy"] = (type_ok / type_tp if type_tp else None)
        out["type_confusion"] = type_conf
        json.dump(out, open(args.json_out, "w", encoding="utf-8"), indent=2)
        print(f"\n[+] wrote {args.json_out}")


if __name__ == "__main__":
    main()
