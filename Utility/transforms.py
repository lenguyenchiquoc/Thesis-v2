"""Reversible transform steps: the provenance of a candidate value.

Every way the pipeline narrows a captured HTTP slot value (cookie / header /
query param / body) down to the candidate it analyses is recorded as a Step:
a JSON-serialisable dict carrying everything needed to run it again (forward)
and to undo it (inverse).

Replay never rebuilds a request from scratch. It walks the chain forward from
the ORIGINAL slot value to recover every intermediate parent, then walks it
backward, substituting the mutated value into each original parent. Siblings
(other cookies, other JSON keys, other form params, the JWT signature...) and
the original formatting (base64 alphabet, padding, hex case, url-quoting
style, JSON separators) are therefore preserved by construction.

A step whose op is unknown raises TransformError: replay then reports the
vector as not faithfully reconstructable instead of silently overwriting the
whole slot with the fragment (the root cause of the Cookie-header and nested
JSON body bugs).
"""

import base64
import binascii
import gzip
import json
import re
import urllib.parse


class TransformError(Exception):
    pass


Step = dict


def trim_of(raw: str) -> list[int]:
    stripped = raw.strip()
    if not stripped:
        return [0, 0]
    lead = len(raw) - len(raw.lstrip())
    trail = len(raw) - len(raw.rstrip())
    return [lead, trail]


def _apply_trim(raw: str, trim) -> str:
    lead, trail = trim
    return raw[lead:len(raw) - trail]


def _splice_trim(raw: str, trim, new_inner: str) -> str:
    lead, trail = trim
    return raw[:lead] + new_inner + raw[len(raw) - trail:]


def slice_step(start: int, end: int) -> Step:
    return {"op": "slice", "start": start, "end": end}


def url_step(parent: str) -> Step:
    raw_unreserved = set(urllib.parse.quote("".join(chr(c) for c in range(32, 127)), safe=""))
    safe = sorted({c for c in parent if c not in raw_unreserved and c != "%" and 32 < ord(c) < 127})
    hex_digits = re.findall(r"%([0-9A-Fa-f]{2})", parent)
    lower = bool(hex_digits) and all(h == h.lower() for h in hex_digits) and any(c.isalpha() for h in hex_digits for c in h)
    return {"op": "url", "safe": "".join(safe), "lower": lower}


def base64_step(parent: str, gz: bool = False) -> Step:
    urlsafe = "-" in parent or "_" in parent
    body = parent.rstrip("=")
    pad = parent.endswith("=") or (len(body) % 4 == 0 and not urlsafe)
    return {"op": "base64_gzip" if gz else "base64", "urlsafe": urlsafe, "pad": pad}


def hex_step(parent: str) -> Step:
    return {"op": "hex", "upper": any(c in "ABCDEF" for c in parent) and not any(c in "abcdef" for c in parent)}


def jwt_step(index: int) -> Step:
    return {"op": "jwt_segment", "index": index}


def json_step(parent: str, path: list) -> Step:
    obj = json.loads(parent)
    style = "default"
    for ascii_only in (False, True):
        if json.dumps(obj, separators=(",", ":"), ensure_ascii=ascii_only) == parent:
            style = "compact_ascii" if ascii_only else "compact"
            break
    else:
        if json.dumps(obj, ensure_ascii=True) == parent:
            style = "default_ascii"
    return {"op": "json", "path": list(path), "style": style}


def _b64_decode(s: str) -> bytes:
    val = s.replace("-", "+").replace("_", "/").rstrip("=")
    if len(val) % 4:
        val += "=" * (4 - len(val) % 4)
    return base64.b64decode(val, validate=False)


def _b64_encode(data: bytes, step: Step) -> str:
    out = base64.urlsafe_b64encode(data) if step.get("urlsafe") else base64.b64encode(data)
    text = out.decode("ascii")
    return text if step.get("pad", True) else text.rstrip("=")


def _json_get(obj, path):
    for key in path:
        obj = obj[key]
    return obj


def _json_set(obj, path, value):
    if not path:
        return value
    parent = _json_get(obj, path[:-1])
    parent[path[-1]] = value
    return obj


def _json_dump(obj, style: str) -> str:
    if style == "compact":
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    if style == "compact_ascii":
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=True)
    if style == "default_ascii":
        return json.dumps(obj, ensure_ascii=True)
    return json.dumps(obj, ensure_ascii=False)


def _json_node_text(node) -> str:
    if isinstance(node, str):
        return node
    return json.dumps(node, separators=(",", ":"), ensure_ascii=False)


def _forward_raw(step: Step, parent: str) -> str:
    op = step.get("op")
    if op == "slice":
        return parent[step["start"]:step["end"]]
    if op == "url":
        return urllib.parse.unquote(parent, encoding="latin-1")
    if op == "base64":
        return _b64_decode(parent).decode("latin-1")
    if op == "base64_gzip":
        return gzip.decompress(_b64_decode(parent)).decode("latin-1")
    if op == "hex":
        return bytes.fromhex(parent).decode("latin-1")
    if op == "jwt_segment":
        seg = parent.split(".")[step["index"]]
        return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)).decode("latin-1")
    if op == "json":
        return _json_node_text(_json_get(json.loads(parent), step["path"]))
    raise TransformError(f"unknown transform op: {op!r}")


def _inverse_raw(step: Step, new_raw: str, parent: str) -> str:
    op = step.get("op")
    if op == "slice":
        return parent[:step["start"]] + new_raw + parent[step["end"]:]
    if op == "url":
        out = urllib.parse.quote(new_raw, safe=step.get("safe", ""), encoding="latin-1")
        if step.get("lower"):
            out = re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), out)
        return out
    if op == "base64":
        return _b64_encode(new_raw.encode("latin-1"), step)
    if op == "base64_gzip":
        return _b64_encode(gzip.compress(new_raw.encode("latin-1")), step)
    if op == "hex":
        out = new_raw.encode("latin-1").hex()
        return out.upper() if step.get("upper") else out
    if op == "jwt_segment":
        parts = parent.split(".")
        parts[step["index"]] = base64.urlsafe_b64encode(new_raw.encode("latin-1")).decode("ascii").rstrip("=")
        return ".".join(parts)
    if op == "json":
        obj = json.loads(parent)
        path = step["path"]
        old_node = _json_get(obj, path)
        if isinstance(old_node, str):
            new_node = new_raw
        else:
            try:
                new_node = json.loads(new_raw)
            except ValueError:
                new_node = new_raw
        return _json_dump(_json_set(obj, path, new_node), step.get("style", "default"))
    raise TransformError(f"unknown transform op: {op!r}")


def forward(step: Step, parent: str) -> str:
    try:
        raw = _forward_raw(step, parent)
    except TransformError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, binascii.Error, OSError, EOFError) as e:
        raise TransformError(f"cannot apply {step.get('op')!r}: {e}") from e
    return _apply_trim(raw, step.get("trim", [0, 0]))


def inverse(step: Step, new_child: str, parent: str) -> str:
    if step.get("lossy"):
        raise TransformError(
            f"{step.get('op')!r} step discarded part of its input when it was recorded "
            "(e.g. base64 over non-base64 text), so it cannot be inverted faithfully"
        )
    try:
        raw = _forward_raw(step, parent)
        new_raw = _splice_trim(raw, step.get("trim", [0, 0]), new_child)
        return _inverse_raw(step, new_raw, parent)
    except TransformError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, binascii.Error, OSError, EOFError, UnicodeEncodeError) as e:
        raise TransformError(f"cannot invert {step.get('op')!r}: {e}") from e


def _equivalent(step: Step, rebuilt: str, parent: str) -> bool:
    # Encodings with several valid spellings of the same content.
    op = step.get("op")
    try:
        if op == "url":
            return urllib.parse.unquote(rebuilt, encoding="latin-1") == urllib.parse.unquote(parent, encoding="latin-1")
        if op == "base64_gzip":
            return _forward_raw(step, rebuilt) == _forward_raw(step, parent)
        if op == "json" and step.get("style") == "default":
            return json.loads(rebuilt) == json.loads(parent)
    except (ValueError, binascii.Error, OSError, EOFError):
        return False
    return False


def mark_if_lossy(step: Step, parent: str, child: str) -> Step:
    """Record-time check: undoing the step on its own output must give back the
    parent (byte-identical, or equivalent for encodings with several spellings).
    If not, the step threw information away and is flagged so replay refuses it
    instead of rebuilding a different request."""
    try:
        rebuilt = inverse(step, child, parent)
    except TransformError:
        step["lossy"] = True
        return step
    if rebuilt != parent and not _equivalent(step, rebuilt, parent):
        step["lossy"] = True
    return step


def apply_chain(root: str, chain: list[Step]) -> str:
    current = root
    for step in chain:
        current = forward(step, current)
    return current


def rebuild(root: str, chain: list[Step], new_leaf: str) -> str:
    """Substitute new_leaf for the value reached by `chain` from `root`, and
    return the new root. Every untouched part of every level is preserved."""
    parents = []
    current = root
    for step in chain:
        parents.append(current)
        current = forward(step, current)
    new_value = new_leaf
    for step, parent in zip(reversed(chain), reversed(parents)):
        new_value = inverse(step, new_value, parent)
    return new_value
