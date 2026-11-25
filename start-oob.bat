@echo off
setlocal
REM ---------------------------------------------------------------------------
REM  Start the self-hosted OOB (out-of-band) interaction collector.
REM
REM  This is the INTERNAL collector the scanner defaults to when the user leaves
REM  the "OOB domain" field in the extension empty (see config.json:
REM     "oob_domain": ""                 -> callbacks go to this collector
REM     "oob_collector_url": "http://127.0.0.1:9000"  -> where the scanner polls
REM
REM  Leave this window open while scanning. HTTP listens on :9000 (token from the
REM  first URL path segment, http://127.0.0.1:9000/<token>/...). The raw-LDAP
REM  catcher listens on :1389 to confirm Java/fastjson JNDI lookups
REM  (ldap://host.docker.internal:1389/<token>/a) instead of hanging on the HTTP port.
REM  The DNS catcher listens on :53 (token from the LEFTMOST label of <token>.<domain>)
REM  so subdomain-form callbacks confirm out-of-band even when the HTTP/TLS leg fails
REM  (e.g. the Ruby Gem s3 chain, which does HTTPS). Needed only when you set a dotted
REM  "OOB domain" in the extension (e.g. oast.local) AND point the target container's
REM  resolver here (docker run --dns <host-ip>). If :53 is busy / needs privileges the
REM  collector logs a warning and keeps running HTTP-only, so this is safe to leave on.
REM
REM  Endpoints:  /_health  /_hits?token=<t>  /_all
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

echo [*] Starting OOB collector:  HTTP http://127.0.0.1:9000  +  DNS udp://:53  +  LDAP tcp://:1389
echo     (HTTP = node/yaml/.NET/PHP path callbacks;  DNS = subdomain-form confirm incl. Ruby;  LDAP = Java/fastjson JNDI)
echo     Leave this window open. Press Ctrl+C to stop.
echo     Note: if :53 is busy/needs admin it falls back to HTTP-only automatically.
echo.

REM All three catchers run in the SAME process. DNS on :53 (--dns-port 53) lets
REM subdomain-form callbacks (<token>.<domain>) confirm out-of-band — required for the
REM Ruby Gem s3 chain, whose HTTPS leg fails the TLS handshake so the token only arrives
REM via the DNS lookup. Binding :53 is tolerant: on failure the collector keeps HTTP+LDAP.
REM Add --no-dns to force HTTP-only, or --no-ldap to drop the LDAP catcher.
python -m Server.oob_collector --http-port 9000 --dns-port 53 --ldap-port 1389

echo.
echo [!] Collector stopped.
pause
