"""Stage 9 — OOB CONFIRM (shared).

Extracted out of Server/serve.py so BOTH the extension bridge (run_pipeline) and
the staged CLI (analyze -> assess) use the exact same out-of-band confirmation
logic — no drift. This is the only stage that can push a finding to
'dynamic-strong' on a blind lab where the in-band control probe downgrades
everything: it polls the self-hosted collector and elevates any finding whose
unique per-vector token received an out-of-band callback (DNS/HTTP).

Pure stdlib + tool_config; imports nothing from Server/ or main, so it is safe to
import from either side with no circular dependency.
"""

import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
import uuid

from tool_config import (set_oob_override, format_oob_token,
                         get_oob_collector_url, get_oob_wait_seconds)

# Bypass any system/env proxy — the collector is always loopback/LAN, and a proxy
# in front of it would make every poll fail.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def set_vector_oob(base_oob: str | None) -> str | None:
    """Mint a unique per-vector token and point the OOB override at
    {base_oob}/{token} so this vector's canary payloads embed it. Returns the
    token (to later match a collector hit back to this finding), or None when no
    OOB base domain is configured (detect-only run). Call this right BEFORE
    mutating/analyzing a vector, so the token lands inside its payloads."""
    if not base_oob:
        return None
    token = uuid.uuid4().hex[:12]
    set_oob_override(format_oob_token(base_oob, token))
    return token


def wsl_host_collector_urls(port) -> list:
    """When serve runs inside WSL2 but the collector runs on the Windows host, neither
    127.0.0.1 (WSL's own localhost) nor host.docker.internal (a Docker-backend-only name,
    not present in a plain WSL distro) reaches it. The Windows host IS reachable as the
    WSL default-route gateway (and usually the resolv.conf nameserver). Return those as
    collector URL candidates. Empty when not under WSL. The gateway is dynamic, so we
    resolve it fresh each run rather than hard-coding it."""
    try:
        with open("/proc/version") as f:
            if "microsoft" not in f.read().lower():
                return []
    except Exception:
        return []
    ips = []
    try:
        out = subprocess.run(["ip", "route", "show", "default"],
                             capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
        if m:
            ips.append(m.group(1))
    except Exception:
        pass
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    ip = line.split()[1]
                    if ip not in ips:
                        ips.append(ip)
                    break
    except Exception:
        pass
    return [f"http://{ip}:{port}" for ip in ips]


def collector_probe(collector_url: str):
    """(reachable?, error_reason). The reason is surfaced in stats.oob so a failing poll
    says WHY (proxy, timeout, connection refused, DNS) instead of just 'unreachable'."""
    url = f"{collector_url.rstrip('/')}/_health"
    try:
        with _LOCAL_OPENER.open(url, timeout=3) as r:
            if r.status == 200:
                return True, None
            return False, f"HTTP {r.status} from {url}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def collector_alive(collector_url: str) -> bool:
    ok, _ = collector_probe(collector_url)
    return ok


def poll_oob(collector_url: str, token: str) -> int:
    """Return how many OOB callbacks the collector logged for this token."""
    try:
        url = f"{collector_url.rstrip('/')}/_hits?token={urllib.parse.quote(token)}"
        with _LOCAL_OPENER.open(url, timeout=3) as r:
            return int(json.loads(r.read().decode("utf-8")).get("count", 0))
    except Exception:
        return 0


_SEVERITY_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}

# OOB canaries whose callback can only happen if attacker-chosen code/command ran
# (phpggc system/exec/passthru curl, pickle/yaml/jsonpickle __reduce__ urlopen,
# node-serialize / js-yaml function http.get, ysonet/Json.NET Process.Start, Java
# CommonsCollections Runtime.exec).
_EXEC_OOB_TYPES = frozenset({
    "php_object_oob", "pickle_oob", "jsonpickle_oob", "yaml_oob",
    "yaml_js_function_oob", "node_serialize_oob",
    "dotnet_jsonnet_oob", "dotnet_ysonet_oob", "java_rce_escalation",
})
# OOB canaries that only perform a lookup/fetch (Java URLDNS, Jackson/Fastjson JNDI,
# Ruby Gem::Requirement->RemoteFetcher which deliberately stops at the fetch).
_LOOKUP_OOB_TYPES = frozenset({
    "java_urldns", "fastjson_oob", "jackson_oob",
    "oj_detection_oob", "yaml_detection_oob",
})


def _escalate_on_oob(finding: dict) -> None:
    """Raise severity of an OOB-confirmed finding (never lowers). The collector only returns
    a hit COUNT per token and every canary of the vector shares that token, so the hit can be
    attributed to code execution only when ALL OOB-capable attempts of the vector are
    exec-type. Mixed or lookup-only vectors still prove the sink deserialized attacker input
    -> at least High. Still Suspected (note text says so); nothing is auto-confirmed."""
    types = {a.get("payload_type") for a in finding.get("attempts") or []
             if not a.get("skipped")}
    exec_t = types & _EXEC_OOB_TYPES
    lookup_t = types & _LOOKUP_OOB_TYPES
    if exec_t and not lookup_t:
        tier = "Critical"
        reason = ("OOB callback on a token carried only by command/code-execution canaries "
                  "(" + ", ".join(sorted(exec_t)) + ") — suspected RCE")
    else:
        tier = "High"
        reason = "OOB callback confirms the sink deserialized attacker-supplied input"
    current = finding.get("severity") or "Low"
    if _SEVERITY_RANK[tier] > _SEVERITY_RANK.get(current, 0):
        finding["severity"] = tier
        finding["severity_note"] = f"raised from {current} — {reason}"


def oob_confirm(findings: list, token_by_idx: dict, base_domain: str) -> dict:
    """After replay, poll the self-hosted collector and elevate any finding whose
    unique per-vector token received an out-of-band callback (DNS/HTTP) to
    dynamic-strong — this is the only path that reaches 'strong' on blind labs where
    the in-band control probe downgrades everything. No-op (and silent) when OOB is
    not configured or the collector is unreachable, so detect-only runs are unaffected.

    Returns a status dict (surfaced in the report's stats.oob) so a report can show
    whether OOB confirmation actually ran, was skipped, and how many it confirmed."""
    collector_url = get_oob_collector_url()
    if not (base_domain and token_by_idx and collector_url):
        return {"status": "not_configured",
                "detail": "no OOB domain/collector configured — detect-only run"}

    port = urllib.parse.urlsplit(collector_url).port or 9000
    candidates = [collector_url]
    alt = f"http://{base_domain}"
    if alt.rstrip('/') != collector_url.rstrip('/'):
        candidates.append(alt)
    for u in wsl_host_collector_urls(port):
        if u.rstrip('/') not in [c.rstrip('/') for c in candidates]:
            candidates.append(u)
    chosen, errors = None, []
    for cand in candidates:
        alive, err = collector_probe(cand)
        if alive:
            chosen = cand
            break
        errors.append(f"{cand} ({err})")
    if not chosen:
        detail = "serve could not reach the collector at " + " or ".join(errors) + \
                 ". The container reaching host.docker.internal:9000 does NOT prove serve " \
                 "can reach it — run serve on the SAME host as the collector, or point " \
                 "oob_collector_url at a host:port serve can reach; also check proxy/firewall."
        print(f"    [oob] collector unreachable: {'; '.join(errors)}")
        return {"status": "collector_unreachable", "collector": collector_url,
                "tried": candidates, "error": errors[0] if errors else None, "detail": detail}
    collector_url = chosen
    wait = get_oob_wait_seconds()
    if wait > 0:
        print(f"    [oob] waiting {wait:.0f}s for out-of-band callbacks…")
        time.sleep(wait)
    confirmed = 0
    for idx, token in token_by_idx.items():
        hits = poll_oob(collector_url, token)
        if hits > 0:
            confirmed += 1
            f = findings[idx]
            f["evidence"] = "dynamic-strong"
            f["oob_confirmed"] = True
            f["indicators"] = [
                f"OOB callback received ({hits} hit(s)) on token {token} — out-of-band "
                f"interaction observed: the payload was deserialized and triggered an outbound "
                f"lookup/request (suspected; verify manually — a callback does not by itself "
                f"prove arbitrary code execution)"
            ] + list(f.get("indicators", []))
            _escalate_on_oob(f)
            print(f"    [oob] CONFIRMED strong: {f.get('location')}/{f.get('name')} "
                  f"{f.get('url')} ({hits} hit(s))")
    return {"status": "ran", "collector": collector_url, "base_domain": base_domain,
            "tokens_polled": len(token_by_idx), "confirmed": confirmed}
