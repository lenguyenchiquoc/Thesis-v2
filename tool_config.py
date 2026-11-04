import json
import os

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


def get_oob_domain() -> str:
    if _oob_override:
        return _oob_override

    env_value = os.environ.get("ETHICALQUOC_OOB_DOMAIN")
    if env_value:
        return env_value

    raw = _load_raw_config()
    value = raw.get("oob_domain")
    return value if isinstance(value, str) else ""


def get_oob_collector_url() -> str:
    """Where the scanner polls for OOB hits (the self-hosted collector's HTTP API).
    Separate from the embedded OOB *domain*: the domain is what the target calls back
    to (may be a public host / ngrok / VPS), while this is where WE read the hit log —
    often http://127.0.0.1:9000 even when the domain is public, if the collector runs
    locally. Empty disables OOB auto-confirmation."""
    env_value = os.environ.get("ETHICALQUOC_OOB_COLLECTOR")
    if env_value:
        return env_value
    raw = _load_raw_config()
    value = raw.get("oob_collector_url")
    return value if isinstance(value, str) else ""


def get_oob_wait_seconds() -> float:
    """Seconds to wait after replay before polling the collector — OOB callbacks are
    asynchronous and can lag the request that triggered them."""
    raw = _load_raw_config()
    try:
        return float(raw.get("oob_wait_seconds", 6))
    except (TypeError, ValueError):
        return 6.0
