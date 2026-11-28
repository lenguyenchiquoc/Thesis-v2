# EthicalQuoc

CLI decision-support tool for detecting insecure deserialization in black-box web applications, with automated payload mutation and pentest-oriented reporting.

Built as a pre-thesis project at International University — VNU-HCM. Not a production security scanner — intended for lab/CTF/authorized pentest environments only. See [Disclaimer](#disclaimer).

## Table of contents

- [How it works](#how-it-works)
- [Supported serialization formats](#supported-serialization-formats)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Credits](#credits)
- [Disclaimer](#disclaimer)

## How it works

EthicalQuoc runs a black-box analysis pipeline over HTTP traffic captured from a target application. Instead of requiring the tester to manually spot a serialized parameter, identify its format, and hand-craft an exploit (the current state of tools like `ysoserial`/`phpggc`), it automates the pipeline end to end:

```
Stage 1  Input Collection   (scan)      HAR file or live browser capture -> raw HTTP vectors
Stage 2  PostFilter                     drop noise: irrelevant locations/headers, keep suspicious values
Stage 3  CleanFilter                    strip known prefixes (Bearer, session=, Cookie:, ...)
Stage 4  Normalize                      peel URL-encoding / Base64 / gzip / hex layers (BFS, multi-layer)
Stage 5  Fingerprint                    classify against known serialization signatures + confidence score
Stage 6  Exploitability Analysis        map fingerprint -> exploit type, severity, suggested probe
Stage 7  Payload Mutation               generate type-specific exploit payloads for the suggested probe
Stage 8  Replay + Confirmation (assess) inject payload into the real request, compare vs baseline response
Stage 9  Report                         split findings into Confirmed vs Suspected, export JSON
```

Each stage writes structured JSON, so any stage can be re-run or inspected independently without re-running the whole pipeline.

### Confirmed vs Suspected

A signature match alone (e.g. "this cookie contains `__wakeup`") is not proof of exploitability in a black-box setting — it only means the *shape* of the data looks dangerous. EthicalQuoc keeps this distinction explicit throughout the pipeline:

- **Suspected** — the exploitability analysis stage detected a signature/pattern and generated a payload for it, but nothing has confirmed the target actually deserializes it.
- **Confirmed** — the `assess` stage replayed the mutated payload against the live target and observed real evidence: a timing delay, a status/response-length change, or an error/exception disclosed in the response.

A failed or skipped replay (timeout, unreachable target) never downgrades a finding to "not vulnerable" — it just means it wasn't verified this run.

## Supported serialization formats

| Format | Fingerprinting | Exploitability analysis | Payload mutation |
|---|---|---|---|
| Java | ✅ | ✅ | ✅ ysoserial subprocess (multi gadget-chain × command) |
| PHP | ✅ | ✅ | ✅ phpggc (gadget chains) + inline mutation (flip_boolean / modify_string / modify_integer / magic_method) |
| Python Pickle | ✅ | ✅ | ✅ inline `pickle`-based payload |
| YAML | ✅ | ✅ | ✅ inline `!!python/object/apply` payload |
| NodeJS | ✅ | ✅ | ✅ node-serialize IIFE + prototype pollution |
| Ruby Marshal | ✅ | ✅ | ✅ `ruby -e` subprocess (requires Ruby installed) |
| .NET (ViewState / BinaryFormatter / JSON.NET) | ✅ | ✅ | ✅ ysonet subprocess + inline JSON.NET `$type` payload |
| Wrapper (`phar://`, `expect://`, `gopher://`, `php://`, `data://`, `glob://`, ...) | ✅ | ✅ | ✅ inline construction + phpggc phar output + optional Gopherus |

All mutation paths that shell out to an external tool (`ysoserial`, `phpggc`, `ysonet`, `Gopherus`) fail gracefully with a clear error/hint when the tool isn't installed, instead of silently returning nothing.

## Installation

### Option A — Windows via WSL2 (recommended on Windows: all 5 tools work in one command)

```powershell
git clone https://github.com/lenguyenchiquoc/Thesis.git
cd Thesis
.\setup.ps1                 # one-time: installs Ubuntu (WSL2) + java/php/ruby/python3 inside it
.\ethicalquoc.ps1 analyze -i results/scan_output.json -o results/analyze_output.json
```
`setup.ps1` is idempotent (safe to re-run) — it installs the `Ubuntu` WSL distro if missing, then `java`/`php`/`ruby`/`python3` inside it, and enables `phar.readonly=0` for phpggc. After that, `ethicalquoc.ps1 <args>` runs `main.py` inside that Ubuntu WSL environment for every command — arguments are passed straight through, e.g. `.\ethicalquoc.ps1 run --har TestCase/comprehensive.har -o results/report.json`.

This gets **all 4 mutation paths working from one command** (`ysoserial`, `phpggc`, Ruby Marshal, `ysonet`). The key trick: WSL2 has built-in Windows interop, so a Linux process running inside it can directly execute `tools/dotnet/ysonet.exe` (a real Windows binary) — unlike a Docker container, which is isolated from the Windows kernel and needs `mono` (confirmed by testing not to work for this tool's gadgets, see [Known limitations](#known-limitations)). Requires Windows 10 (2004+) or 11 with virtualization enabled; `setup.ps1` tells you the exact command to run if WSL itself isn't installed yet.

### Option B — Docker (cross-platform, but `.NET` mutation does not work)

```bash
git clone https://github.com/lenguyenchiquoc/Thesis.git
cd Thesis
docker build -t ethicalquoc .
docker run --rm -v "$(pwd)/results:/app/results" ethicalquoc analyze -i results/scan_output.json
```
The image bundles Python, Java (JRE), PHP CLI, and Ruby — every mutation path except `.NET`/`ysonet` works out of the box. Use this on macOS/Linux, or on Windows if you'd rather not set up WSL2.

**`.NET` mutation (`ysonet`) does not work inside the Docker container.** `ysonet.exe` is a Windows .NET Framework binary; running it under Linux requires `mono`, and testing confirmed all 3 gadgets this project uses fail under `mono` — `ObjectDataProvider` because it depends on WPF (`PresentationFramework`), which mono never implemented, and `TypeConfuseDelegate`/`ActivitySurrogateSelector` fail with unrelated errors (mono is an independent reimplementation of .NET Framework, not a 1:1 port, and these gadgets rely on low-level reflection tricks mono doesn't replicate exactly).

### Option C — Manual local install (no wrapper, full control)

Requires Python 3.10+. The core pipeline (`scan --har`, `analyze`, `assess`, `report`) only needs the standard library (`json`, `re`, `base64`, `subprocess`, `urllib`) — no extra Python packages. Additional runtimes are needed only for the features that shell out to them:

| Feature | Requires |
|---|---|
| Java mutation (`ysoserial`) | `java` on PATH |
| PHP mutation (`phpggc`) | `php` on PATH |
| Ruby mutation (Marshal payloads) | `ruby` on PATH |
| .NET mutation (`ysonet`) | already vendored, works out of the box on Windows 10/11 — not available on Linux/macOS (`mono` cannot run it, see [Known limitations](#known-limitations)) |

If a runtime is missing, the corresponding mutation returns a clear `{"error": ..., "hint": ...}` entry instead of failing silently — everything else in the pipeline still works.

## Usage

The tool runs the whole pipeline (scan → filter → normalize → fingerprint → exploit analysis → mutate → replay → OOB confirm) in one command on a HAR exported from your browser's DevTools. This is the exact same `run_pipeline` the browser extension uses, so a CLI report is identical in shape to an extension report.

```bash
# Full pipeline in one shot (replay + OOB confirmation included)
python main.py run --har capture.har -o results/report.json
```

Useful flags:

| Flag | Effect |
|---|---|
| `--oob-domain <collector>` | Embed this out-of-band collector domain in canary payloads (same field the extension sends). Omit to fall back to `config.json`/env, or run detect-only when none is configured. |
| `--no-replay` | Static detection only — stop after mutate, skip replay/assess/OOB (no live requests are sent). |
| `--dump-stages` | In the same run, also write `<report>.scan.json` / `.analyze.json` / `.assess.json` next to the report, so each stage's output can be inspected manually — no separate commands needed. |

`-o` is optional. If omitted, the report is still saved — under `results/<DDMMYYYY>/report_<HHMMSS>.json` (the date folder is created automatically), so nothing is silently lost when you forget to name an output file. Each dumped stage file is plain JSON — see `results/` for examples.

> The browser extension talks to a local bridge: `python main.py serve` (binds `127.0.0.1:8099` by default). The HAR carries real session cookies, so the server is loopback-only and must never be exposed.

## Configuration

Third-party exploitation tools are **not bundled with a fixed absolute path** — paths are resolved through `config.json` at the project root, via `tool_config.py`:

```json
{
    "tools": {
        "ysoserial": "tools/java/ysoserial-all.jar",
        "phpggc": "tools/phpggc/phpggc",
        "ysonet": "tools/dotnet/ysonet.exe",
        "gopherus": "tools/gopherus/gopherus.py"
    },
    "oob_domain": "",
    "replay": {
        "time_delay_threshold_sec": 4,
        "content_similarity_threshold": 0.8,
        "length_change_ratio": 0.5,
        "request_timeout_sec": 10
    }
}
```

- Relative paths are resolved against the project root, so the tool works regardless of the drive letter or clone location.
- To point at tools installed elsewhere, either edit `config.json` directly or set the `ETHICALQUOC_CONFIG` environment variable to a different config file path.
- `ysoserial-all.jar`, `phpggc`, and [ysonet](https://github.com/irsdl/ysonet) (actively maintained fork/replacement of the now largely inactive `pwntester/ysoserial.net`) are all vendored under `tools/` — cloning the repo is enough, nothing to download separately for Java/PHP/.NET mutation. Only Gopherus is not bundled — install it separately and update `config.json` if you need the enhanced SSRF path (a manual fallback payload is generated even without it).
- `ysonet.exe` targets .NET Framework — it runs out of the box on Windows 10/11, which ship .NET Framework 4.8 pre-installed as an OS component (no separate .NET install needed). It does **not** run on Linux/macOS or inside the Docker image (see [Known limitations](#known-limitations)); on those platforms, `.NET` mutation returns a clear error/hint instead of a payload.
- `replay` — thresholds of the replay oracle (baseline / mutated / control comparison in `Replay/replay_request.py`). Edit them here instead of in the code; a missing section or key uses the default shown, and an invalid value (wrong type, out of range, unknown key) is reported at startup and replaced by its default:

  | Key | Default | Meaning |
  |---|---|---|
  | `time_delay_threshold_sec` | `4` | Mutated response at least this many seconds slower than baseline → time-based **strong** signal |
  | `content_similarity_threshold` | `0.8` | Body similarity (0–1) for "small localized content change" and for the control-probe downgrade |
  | `length_change_ratio` | `0.5` | Length change above this fraction of the baseline length → "length changed significantly" |
  | `request_timeout_sec` | `10` | HTTP timeout per replayed request |

  `time_delay_threshold_sec` must stay **below** `request_timeout_sec`, otherwise the request is cut off before it can exceed the threshold and the time-based signal never fires (the tool warns about this). The defaults are the values the tool was evaluated with — changing them changes what is flagged: lower similarity / ratio → more findings and more false positives; a higher delay threshold → slow-but-real sinks may be missed.
- `oob_domain` — set this to your own Burp Collaborator or Interactsh subdomain (or set `ETHICALQUOC_OOB_DOMAIN`) to have URLDNS and blind-SSRF payloads embed a real canary instead of a placeholder. Interaction logs must still be checked manually — this tool does not poll an OOB provider's API for you.

## Project structure

```
main.py                     CLI entry point (scan / analyze / assess / report)
tool_config.py               third-party tool path resolution
config.json                  tool path configuration
note.md                      running fix log (before/after code, root cause, how verified)
setup.ps1                    one-time Windows setup: installs Ubuntu (WSL2) + java/php/ruby/python3
setup-wsl.sh                 apt-get install + phar.readonly=0, run inside WSL by setup.ps1
ethicalquoc.ps1              runs main.py inside Ubuntu WSL, forwarding all arguments as-is
Dockerfile, .dockerignore    cross-platform Docker build (Option B) — everything except .NET

Scanner/
  har_loader.py               parses HAR files into HTTP vectors

Analyze/
  postfiltered.py             Stage 2 — location/header/heuristic filtering
  cleanfilter.py               Stage 3 — prefix/whitespace normalization
  normalize.py                 Stage 4 — multi-layer decode (BFS)
  finderprint.py                Stage 5 — serialization fingerprinting
  ExploitabilityAnalysis.py    Stage 6 — exploit type, severity, suggested probe
  payloadMutation.py           Stage 7 — payload generation per format

Replay/
  replay_request.py            Stage 8 — request replay + Confirmed/Suspected evidence

Input/, Output/                schema-validated JSON load/save helpers
Utility/
  signatures.py                 shared serialization signatures (single source of
                                 truth for postfiltered.py, cleanfilter.py, finderprint.py)
  schemas.py                    TypedDict schemas for every stage's I/O

tools/                          vendored ysoserial-all.jar, phpggc (not project source —
                                 external exploitation tools, see Configuration above)

docs/
  PAYLOAD_MUTATION_REVIEW.md    Stage 7 design review — idea, per-format implementation detail

results/                       pipeline output, organized as results/<DDMMYYYY>/<phase>_<HHMMSS>.json
                                when -o isn't given; only result1.json is real captured lab data
                                (PortSwigger) — result2.json/comprehensive_scan.json are synthetic
                                test fixtures, not real traffic
TestCase/
  generate_comprehensive_har.py  regenerates comprehensive.har (reproducible, not a static blob)
  comprehensive.har               benchmark fixture: synthetic realistic requests (mostly noise) +
                                   malicious payloads covering all 8 formats and known edge cases
  test_*.py                       unit tests (run: python -m unittest discover -s TestCase)
```

## Known limitations

- Static signature matching (e.g. detecting `monolog`/`laravel` keywords, magic method names) infers exploitability from the *shape* of the payload, not from confirmed knowledge of the target's classpath/dependencies — this is an inherent limitation of black-box analysis, not something the tool can fully resolve. The Confirmed/Suspected split exists specifically to keep this honest.
- Attacks requiring a prerequisite step (e.g. forging an HMAC-signed cookie, leaking a signing key such as Django's `SECRET_KEY` or Rails' `secret_key_base`) are out of scope — the tool assumes the observed payload is directly mutable.
- Out-of-band (OOB) confirmation is semi-manual: `assess` will embed a configured canary domain (`oob_domain`) into URLDNS/blind-SSRF payloads, but does not poll an Interactsh/Burp Collaborator API for interactions — checking the interaction log is still a manual step.
- `.NET` mutation (`ysonet`) only runs on Windows. `mono` cannot run it on Linux/macOS or inside the Docker image — tested directly: `ObjectDataProvider` fails because it depends on WPF (`PresentationFramework`), which mono never implemented, and `TypeConfuseDelegate`/`ActivitySurrogateSelector` fail with unrelated errors, since mono is an independent reimplementation of .NET Framework rather than a 1:1 port and doesn't replicate every low-level reflection trick these gadgets rely on.

## Credits

Payload generation for Java, PHP, and .NET builds on top of:
- [ysoserial](https://github.com/frohoff/ysoserial) — Java deserialization gadget chains
- [phpggc](https://github.com/ambionics/phpggc) — PHP deserialization gadget chains
- [ysonet](https://github.com/irsdl/ysonet) — .NET deserialization gadget chains (fork/replacement of [ysoserial.net](https://github.com/pwntester/ysoserial.net))

## Disclaimer

This tool was built for academic/research purposes as part of a pre-thesis project. It is **not** intended for use against systems you do not own or do not have explicit authorization to test. Use only in controlled lab environments (e.g. PortSwigger Web Security Academy) or authorized penetration testing engagements.
