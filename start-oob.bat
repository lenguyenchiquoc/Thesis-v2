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
REM
REM  Endpoints:  /_health  /_hits?token=<t>  /_all
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

echo [*] Starting OOB collector:  HTTP http://127.0.0.1:9000  +  LDAP tcp://:1389
echo     (HTTP = node/yaml/.NET callbacks;  LDAP = Java/fastjson JNDI confirm)
echo     Leave this window open. Press Ctrl+C to stop.
echo.

REM --no-dns keeps DNS off (not needed for localhost Web_vul_env). The raw-LDAP
REM catcher (--ldap-port 1389) runs in the SAME process so JNDI/fastjson lookups
REM confirm out-of-band instead of hanging on the HTTP port. Add --no-ldap to disable.
python -m Server.oob_collector --http-port 9000 --ldap-port 1389 --no-dns

echo.
echo [!] Collector stopped.
pause
