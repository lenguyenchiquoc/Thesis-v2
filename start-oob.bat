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
REM  Leave this window open while scanning. HTTP listens on :9000; token is read
REM  from the first URL path segment (http://127.0.0.1:9000/<token>/...), which is
REM  the form the scanner uses for the internal/localhost default.
REM
REM  Endpoints:  /_health  /_hits?token=<t>  /_all
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

echo [*] Starting OOB collector on http://127.0.0.1:9000  (HTTP only)
echo     Leave this window open. Press Ctrl+C to stop.
echo.

REM --no-dns keeps it HTTP-only (enough for localhost Web_vul_env). Drop --no-dns
REM and add --dns-port 53 --answer-ip 127.0.0.1 for a DNS-callback setup.
python -m Server.oob_collector --http-port 9000 --no-dns

echo.
echo [!] Collector stopped.
pause
