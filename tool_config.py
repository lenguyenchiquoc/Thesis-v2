import json
import os
from urllib.parse import urlsplit

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

_DEFAULT_TOOLS = {
    "ysoserial": "tools/java/ysoserial-all.jar",
    "phpggc": "tools/phpggc/phpggc",
    "ysonet": "tools/dotnet/ysonet.exe",
    "gopherus": "tools/gopherus/gopherus.py",
}

_config_cache = None


def _load_raw_config() -> dict:
    config_path = os.environ.get("ETHICALQUOC_CONFIG", DEFAULT_CONFIG_PATH)
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[!] Failed to read config at {config_path}: {e} — using built-in defaults")
        return {}


def get_tool_path(name: str) -> str:
    global _config_cache
    if _config_cache is None:
        raw = _load_raw_config()
        overrides = raw.get("tools")
        if not isinstance(overrides, dict):
            overrides = {}
        _config_cache = {**_DEFAULT_TOOLS, **overrides}

    path = _config_cache.get(name, "")
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


_oob_override = None


def set_oob_override(domain) -> None:
    """Per-scan runtime override for the OOB domain (e.g. typed in the extension UI),
    taking precedence over the env var and config.json so users don't have to edit a
    file each run. Pass a falsy value to clear it. Note: process-global — assumes one
    scan at a time, which is how the extension/serve bridge is used."""
    global _oob_override
    _oob_override = domain.strip() if isinstance(domain, str) and domain.strip() else None


_INTERNAL_COLLECTOR_URL = "http://127.0.0.1:9000"


def get_oob_domain() -> str:
    """The OOB callback base the scanner embeds in payloads.

    Precedence: UI override (set_oob_override) > env > config.json 'oob_domain' >
    the INTERNAL self-hosted collector (derived from the collector URL). So if the user
    sets an OOB domain it is used; if they set nothing, callbacks go to our own
    collector on localhost instead of any external service."""
    if _oob_override:
        return _oob_override

    env_value = os.environ.get("ETHICALQUOC_OOB_DOMAIN")
    if env_value:
        return env_value

    raw = _load_raw_config()
    value = raw.get("oob_domain")
    if isinstance(value, str) and value.strip():
        return value.strip()

    return _internal_oob_base()


def _internal_oob_base() -> str:
    """host:port of the configured collector (used as the default OOB base)."""
    collector = get_oob_collector_url()
    if not collector:
        return ""
    netloc = urlsplit(collector).netloc
    return netloc


def get_oob_collector_url() -> str:
    """Where the scanner polls for OOB hits (the self-hosted collector's HTTP API).
    Separate from the embedded OOB *domain*: the domain is what the target calls back
    to (may be a public host / ngrok / VPS), while this is where WE read the hit log —
    often http://127.0.0.1:9000 even when the domain is public, if the collector runs
    locally. Defaults to the internal collector; set to empty in config.json to disable
    OOB auto-confirmation entirely."""
    env_value = os.environ.get("ETHICALQUOC_OOB_COLLECTOR")
    if env_value:
        return env_value
    raw = _load_raw_config()
    value = raw.get("oob_collector_url")
    if isinstance(value, str):
        return value.strip()
    return _INTERNAL_COLLECTOR_URL


def format_oob_token(base: str, token: str) -> str:
    """Per-vector OOB callback address embedded in a payload, given the base and a
    unique token. Picks the form the collector can actually read the token from:
      - real domain (has a dot, no port, e.g. abc.oast.fun) -> SUBDOMAIN form
        '<token>.<base>' (collector reads the leftmost DNS label);
      - IP or host:port (internal localhost collector, e.g. 127.0.0.1:9000) -> PATH form
        '<base>/<token>' (an IP takes no subdomain; collector falls back to the first
        path segment for HTTP-only callbacks)."""
    base = base.strip().rstrip('/')
    if not base:
        return token
    if _looks_like_ip_or_hostport(base):
        return f"{base}/{token}"
    return f"{token}.{base}"


def _looks_like_ip_or_hostport(base: str) -> bool:
    if ':' in base:
        return True
    labels = base.split('.')
    return len(labels) == 4 and all(lbl.isdigit() for lbl in labels)


def get_oob_wait_seconds() -> float:
    """Seconds to wait after replay before polling the collector — OOB callbacks are
    asynchronous and can lag the request that triggered them."""
    raw = _load_raw_config()
    try:
        return float(raw.get("oob_wait_seconds", 6))
    except (TypeError, ValueError):
        return 6.0
