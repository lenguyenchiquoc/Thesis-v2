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


def _oob_ldap_port() -> int:
    """TCP port of the collector's raw-LDAP catcher (JNDI/fastjson callbacks). Must match the
    collector's --ldap-port. Override via env ETHICALQUOC_OOB_LDAP_PORT or config 'oob_ldap_port'."""
    env_value = os.environ.get("ETHICALQUOC_OOB_LDAP_PORT")
    if env_value and env_value.strip().isdigit():
        return int(env_value.strip())
    value = _load_raw_config().get("oob_ldap_port")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 1389


def get_oob_ldap_target() -> str:
    """JNDI/LDAP callback target for ldap:// gadgets (fastjson/Jackson). Same host + per-vector
    token as get_oob_domain(), but on the collector's LDAP port instead of its HTTP port — the
    raw-LDAP catcher listens there, so the lookup gets answered instead of hanging on the HTTP port:

        host.docker.internal:9000/<token>  ->  host.docker.internal:1389/<token>
        <token>.abc.oast.fun               ->  <token>.abc.oast.fun   (real OOB provider, ldap:389)
    """
    base = (get_oob_domain() or "").strip()
    if not base:
        return ""
    if '/' in base:
        hostport, tail = base.split('/', 1)
        tail = '/' + tail
    else:
        hostport, tail = base, ''
    if ':' in hostport:                      # internal host:port form -> swap the port
        host = hostport.rsplit(':', 1)[0]
        return f"{host}:{_oob_ldap_port()}{tail}"
    return base                              # real-domain subdomain form -> leave as-is


def _looks_like_ip_or_hostport(base: str) -> bool:
    if ':' in base:
        return True
    labels = base.split('.')
    return len(labels) == 4 and all(lbl.isdigit() for lbl in labels)


# Replay oracle thresholds (Replay/replay_request.py _compare). Defaults are the values the
# tool was evaluated with — a config.json without a "replay" section, or with any key
# missing/invalid, behaves exactly as before. Changing them changes what gets flagged.
_DEFAULT_REPLAY = {
    # mutated response at least this many seconds slower than baseline -> time-based strong
    "time_delay_threshold_sec": 4.0,
    # body similarity (0..1) for "small localized content diff" and for the control-probe downgrade
    "content_similarity_threshold": 0.8,
    # |mutated-baseline| / baseline length above this ratio -> "length changed significantly"
    "length_change_ratio": 0.5,
    # per-request HTTP timeout for baseline / mutated / control
    "request_timeout_sec": 10.0,
}


def get_replay_settings() -> dict:
    """Replay thresholds from config.json's "replay" section, validated key by key: a bad
    value is reported and replaced by its default, never silently used."""
    settings = dict(_DEFAULT_REPLAY)
    section = _load_raw_config().get("replay")
    if section is None:
        return settings
    if not isinstance(section, dict):
        print('[!] config.json "replay" must be an object — using built-in replay defaults')
        return settings

    for key, value in section.items():
        if key not in _DEFAULT_REPLAY:
            print(f'[!] config.json replay.{key}: unknown key — ignored '
                  f'(known: {", ".join(_DEFAULT_REPLAY)})')
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            print(f'[!] config.json replay.{key}={value!r}: must be a number — '
                  f'using default {_DEFAULT_REPLAY[key]}')
            continue
        value = float(value)
        valid = 0 < value <= 1 if key == "content_similarity_threshold" else value > 0
        if not valid:
            rule = "between 0 (exclusive) and 1" if key == "content_similarity_threshold" else "> 0"
            print(f'[!] config.json replay.{key}={value}: must be {rule} — '
                  f'using default {_DEFAULT_REPLAY[key]}')
            continue
        settings[key] = value

    if settings["time_delay_threshold_sec"] >= settings["request_timeout_sec"]:
        print(f'[!] config.json replay: time_delay_threshold_sec ({settings["time_delay_threshold_sec"]}) '
              f'>= request_timeout_sec ({settings["request_timeout_sec"]}) — a mutated request is cut '
              f'off by the timeout before it can exceed the delay threshold, so the time-based signal '
              f'can never fire. Raise request_timeout_sec above the threshold.')
    return settings


def get_oob_wait_seconds() -> float:
    """Seconds to wait after replay before polling the collector — OOB callbacks are
    asynchronous and can lag the request that triggered them."""
    raw = _load_raw_config()
    try:
        return float(raw.get("oob_wait_seconds", 6))
    except (TypeError, ValueError):
        return 6.0
