"""Self-hosted OOB (out-of-band) interaction collector.

Replaces reliance on Interactsh/Collaborator for blind-deserialization confirmation:
the tool embeds a unique token per vector into its canary payloads (URLDNS, curl/HTTP
RCE, gopher SSRF, SnakeYAML, …). When the target actually deserializes a payload, it
calls back here — a DNS lookup and/or an HTTP request — and this server logs the hit
keyed by that token. The scanner then polls `/_hits?token=…` and elevates the matching
finding from dynamic-weak to dynamic-strong (confirmed OOB interaction).

Token is read from the LEFTMOST DNS/Host label (`<token>.<base-domain>`, the normal
public/ngrok/VPS case) OR, as a fallback for IP/localhost HTTP where no subdomain is
possible, the FIRST path segment (`http://127.0.0.1:9000/<token>/…`).

Pure standard library — runs identically on Windows/macOS/Linux, no pip install.

Run:
    python -m Server.oob_collector                 # HTTP on :9000 + DNS on :5353
    python -m Server.oob_collector --http-port 9000 --dns-port 53 --answer-ip 127.0.0.1
    python -m Server.oob_collector --no-dns        # HTTP only (e.g. behind ngrok)

Reachability (the target must be able to reach this host):
  - Public domain + VPS : point an NS record for <base> at this box, run DNS on :53.
  - ngrok (HTTP only)   : `ngrok http 9000`; use the ngrok host as <base>; token via path.
  - localhost Web_vul_env: run DNS on a port the target's resolver uses, answer-ip=127.0.0.1;
                           or use the path-token form for HTTP-only callbacks.
"""

import argparse
import json
import re
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingTCPServer, ThreadingUDPServer, BaseRequestHandler
from urllib.parse import urlsplit, parse_qs

RESERVED_PATHS = {"/_hits", "/_health", "/_all"}


class HitStore:
    """Thread-safe token -> hits map, shared by the HTTP and DNS listeners."""

    def __init__(self, cap_per_token: int = 50, cap_recent: int = 500):
        self._by_token: dict[str, list] = {}
        self._recent = deque(maxlen=cap_recent)
        self._cap = cap_per_token
        self._lock = threading.Lock()

    def record(self, token: str, kind: str, src: str, detail: str):
        if not token:
            token = "_none"
        hit = {"token": token, "kind": kind, "src": src, "detail": detail,
               "ts": time.time()}
        with self._lock:
            lst = self._by_token.setdefault(token, [])
            if len(lst) < self._cap:
                lst.append(hit)
            self._recent.append(hit)
        print(f"    [oob] {kind} hit  token={token}  from={src}  {detail}")

    def hits_for(self, token: str) -> list:
        with self._lock:
            return list(self._by_token.get(token, []))

    def recent(self, n: int = 100) -> list:
        with self._lock:
            return list(self._recent)[-n:]


_NON_TOKEN_HOSTS = {"localhost", "host.docker.internal", "gateway.docker.internal"}


def _token_from_host(host: str) -> str:
    """Leftmost label of a hostname, unless it's an IP / bare host / routing alias."""
    host = (host or "").split(":")[0].strip(".").lower()
    if not host or host.replace(".", "").isdigit() or host in _NON_TOKEN_HOSTS:
        return ""
    parts = host.split(".")
    return parts[0] if len(parts) >= 2 else ""


def _token_from_path(path: str) -> str:
    seg = urlsplit(path).path.strip("/").split("/", 1)[0]
    return seg if seg and seg not in {p.strip("/") for p in RESERVED_PATHS} else ""


def make_http_handler(store: HitStore):
    class Handler(BaseHTTPRequestHandler):
        server_version = "EthicalQuocOOB/1.0"

        def _send(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _handle(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/_health":
                return self._send(200, {"status": "ok", "service": "oob-collector"})
            if parsed.path == "/_hits":
                token = parse_qs(parsed.query).get("token", [""])[0]
                hits = store.hits_for(token)
                return self._send(200, {"token": token, "count": len(hits), "hits": hits})
            if parsed.path == "/_all":
                return self._send(200, {"recent": store.recent()})
            host = self.headers.get("Host", "")
            token = _token_from_host(host) or _token_from_path(self.path)
            src = self.client_address[0]
            store.record(token, "http", src, f"{self.command} {self.path} Host={host}")
            self._send(200, {"ok": True})

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle
        do_HEAD = _handle

        def log_message(self, fmt, *args):
            pass

    return Handler



def _parse_qname(data: bytes, offset: int):
    labels = []
    while True:
        length = data[offset]
        if length == 0:
            offset += 1
            break
        offset += 1
        labels.append(data[offset:offset + length].decode("latin-1"))
        offset += length
    return labels, offset


def make_dns_handler(store: HitStore, answer_ip: str):
    ip_bytes = socket.inet_aton(answer_ip)

    class DNSHandler(BaseRequestHandler):
        def handle(self):
            data, sock = self.request
            try:
                if len(data) < 12:
                    return
                tid = data[:2]
                qdcount = int.from_bytes(data[4:6], "big")
                labels, end = _parse_qname(data, 12)
                qtype = data[end:end + 2]
                qclass = data[end + 2:end + 4]
                qname = ".".join(labels)
                token = labels[0].lower() if len(labels) >= 2 else ""
                store.record(token, "dns", self.client_address[0], qname)
                question = data[12:end + 4]
                header = tid + b"\x81\x80" + qdcount.to_bytes(2, "big") + \
                    b"\x00\x01" + b"\x00\x00" + b"\x00\x00"
                answer = b"\xc0\x0c" + b"\x00\x01" + b"\x00\x01" + \
                    (60).to_bytes(4, "big") + (4).to_bytes(2, "big") + ip_bytes
                sock.sendto(header + question + answer, self.client_address)
            except Exception as e:
                print(f"    [oob] DNS parse error: {e}")

    return DNSHandler


_LDAP_TOKEN_RE = re.compile(rb'[0-9a-f]{8,32}')


def _token_from_ldap(buf: bytes) -> str:
    """The token is embedded as the LDAP baseDN (format_oob_token path form -> .../<token>/a),
    so it shows up as an ASCII hex run inside the SearchRequest bytes."""
    m = _LDAP_TOKEN_RE.search(buf)
    return m.group(0).decode("latin-1") if m else ""


def make_ldap_handler(store: HitStore):
    """Minimal raw-LDAP catcher: answer the anonymous BindRequest so the JNDI client proceeds to
    send its SearchRequest (which carries the baseDN token), log the token, close. This CONFIRMS a
    JNDI/fastjson lookup reached us out-of-band; it does NOT serve a malicious Reference (no RCE)."""
    class LDAPHandler(BaseRequestHandler):
        def handle(self):
            sock = self.request
            sock.settimeout(4.0)
            buf = b""
            try:
                data = sock.recv(4096)
                if not data:
                    return
                buf += data
                # Echo the BindRequest's messageID so the client accepts our BindResponse.
                msgid = 1
                try:
                    if len(data) >= 5 and data[0] == 0x30 and data[2] == 0x02:
                        ilen = data[3]
                        msgid = data[3 + ilen]
                except Exception:
                    msgid = 1
                bind_ok = bytes([0x30, 0x0c, 0x02, 0x01, msgid & 0xff,
                                 0x61, 0x07, 0x0a, 0x01, 0x00, 0x04, 0x00, 0x04, 0x00])
                try:
                    sock.sendall(bind_ok)
                except OSError:
                    pass
                try:
                    more = sock.recv(4096)  # the SearchRequest (baseDN token), if not pipelined above
                    if more:
                        buf += more
                except (socket.timeout, OSError):
                    pass
                token = _token_from_ldap(buf)
                store.record(token, "ldap", self.client_address[0],
                             f"JNDI/LDAP lookup ({len(buf)} bytes)")
            except Exception as e:
                print(f"    [oob] LDAP handler error: {e}")
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
    return LDAPHandler


def serve(http_port=9000, dns_port=5353, answer_ip="127.0.0.1",
          host="0.0.0.0", enable_dns=True, ldap_port=1389, enable_ldap=True):
    store = HitStore()
    http_srv = ThreadingHTTPServer((host, http_port), make_http_handler(store))
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()
    print(f"[+] OOB collector HTTP ready on http://{host}:{http_port}")
    print(f"    GET /_hits?token=<t>  ·  /_health  ·  /_all")

    dns_srv = None
    if enable_dns:
        try:
            ThreadingUDPServer.allow_reuse_address = True
            dns_srv = ThreadingUDPServer((host, dns_port), make_dns_handler(store, answer_ip))
            threading.Thread(target=dns_srv.serve_forever, daemon=True).start()
            print(f"[+] OOB collector DNS  ready on udp://{host}:{dns_port} "
                  f"(answers every name -> {answer_ip})")
        except PermissionError:
            print(f"[!] DNS port {dns_port} needs privileges — retry with --dns-port 5353 "
                  f"or run elevated. Continuing HTTP-only.")
        except OSError as e:
            print(f"[!] Could not bind DNS on {dns_port}: {e}. Continuing HTTP-only.")

    ldap_srv = None
    if enable_ldap:
        try:
            ThreadingTCPServer.allow_reuse_address = True
            ldap_srv = ThreadingTCPServer((host, ldap_port), make_ldap_handler(store))
            threading.Thread(target=ldap_srv.serve_forever, daemon=True).start()
            print(f"[+] OOB collector LDAP ready on tcp://{host}:{ldap_port} "
                  f"(JNDI/fastjson callback confirm)")
        except OSError as e:
            print(f"[!] Could not bind LDAP on {ldap_port}: {e}. Continuing without LDAP.")

    print("    Bound; press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[*] Shutting down OOB collector.")
        http_srv.shutdown()
        if dns_srv:
            dns_srv.shutdown()
        if ldap_srv:
            ldap_srv.shutdown()


def main():
    ap = argparse.ArgumentParser(description="EthicalQuoc self-hosted OOB collector")
    ap.add_argument("--http-port", type=int, default=9000)
    ap.add_argument("--dns-port", type=int, default=5353)
    ap.add_argument("--ldap-port", type=int, default=1389,
                    help="TCP port for the raw-LDAP catcher (JNDI/fastjson callback confirm)")
    ap.add_argument("--answer-ip", default="127.0.0.1",
                    help="A-record IP returned for every DNS query (where callbacks should land)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-dns", action="store_true", help="HTTP only (e.g. behind ngrok)")
    ap.add_argument("--no-ldap", action="store_true", help="Disable the raw-LDAP catcher")
    args = ap.parse_args()
    serve(args.http_port, args.dns_port, args.answer_ip, args.host, not args.no_dns,
          args.ldap_port, not args.no_ldap)


if __name__ == "__main__":
    main()
