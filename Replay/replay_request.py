import base64
import difflib
import gzip
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import cast

from Utility.schemas import HttpProbeSample, Mutation, RequestContext, ReplayResult, ReplaySkipped
from Utility.transforms import TransformError, rebuild


class ReplayRequest:
    ERROR_KEYWORDS = [
        "exception", "stack trace", "stacktrace", "traceback",
        "fatal error", "unserialize()", "objectinputstream",
        "invalidclassexception", "classnotfoundexception",
        "yaml.constructor", "pickle.unpicklingerror", "syntaxerror",
        "internal server error", "500 internal", "segmentation fault",
    ]

    TIME_DELAY_THRESHOLD_SEC = 4.0

    DESER_SPECIFIC_MARKERS = (
        "unserialize()", "objectinputstream", "invalidclassexception",
        "classnotfoundexception", "yaml.constructor", "pickle.unpicklingerror",
    )

    def __init__(self, timeout: int = 10, verify_tls: bool = True):
        self.timeout = timeout
        self.verify_tls = verify_tls

    def replay(self, payload: Mutation) -> ReplayResult:
        url = cast("str | None", payload.get("url"))
        location = cast("str | None", payload.get("location"))
        name = cast("str | None", payload.get("name"))
        method = (cast("str | None", payload.get("method")) or "GET").upper()
        if location in ("body", "form_body") and method == "GET":
            method = "POST"

        if not url or not location or not name:
            return self._skip_result(payload, "Missing url/location/name — cannot reconstruct request")

        try:
            raw_payload = self._select_payload_value(payload)
        except TransformError as e:
            return self._skip_result(payload, f"Cannot faithfully rebuild the request slot: {e}")
        if raw_payload is None:
            return self._skip_result(payload, "No usable payload value found")

        comparison_value = self._decode_raw_value(payload)
        request_context = cast("RequestContext | None", payload.get("request_context"))

        try:
            baseline = self._send(url, method, location, name, value=None, request_context=request_context)
            mutated = self._send(url, method, location, name, value=raw_payload, request_context=request_context)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return self._skip_result(payload, f"Request failed: {e}")

        control = None
        try:
            control = self._control_probe(url, method, location, name, payload, request_context)
        except (urllib.error.URLError, OSError, ValueError):
            control = None

        indicators, strong_signal = self._compare(baseline, mutated, comparison_value, control)
        baseline.pop("body_compare", None)
        mutated.pop("body_compare", None)

        return {
            "url": url,
            "method": method,
            "location": location,
            "name": name,
            "payload_type": cast("str | None", payload.get("type")),
            "baseline": baseline,
            "mutated": mutated,
            "control": {"status": control["status"], "length": control["length"]} if control else None,
            "indicators": indicators,
            "signal": "strong" if strong_signal else "weak",
        }

    def replay_all(self, payloads: list[Mutation]) -> list[ReplayResult]:
        return [self.replay(p) for p in payloads if "error" not in p]

    REWRAPPABLE_OPS = {"url", "base64", "base64_gzip", "hex"}

    CONTROL_JUNK = "control_probe_not_a_serialized_object_0123456789abcdef"

    def _make_control_value(self, payload: Mutation) -> str:
        transform_chain = cast("list[dict] | None", payload.get("transform_chain"))
        slot_value = cast("str | None", payload.get("slot_value"))
        try:
            if transform_chain is not None and slot_value is not None:
                return rebuild(slot_value, transform_chain, self.CONTROL_JUNK)
            encoding_chain = cast("list[str] | None", payload.get("encoding_chain")) or []
            if encoding_chain and all(op in self.REWRAPPABLE_OPS for op in encoding_chain):
                return self._reapply_encoding_chain(self.CONTROL_JUNK, encoding_chain)
        except Exception:
            pass
        return self.CONTROL_JUNK

    def _control_probe(self, url, method, location, name, payload, request_context):
        if not hasattr(self, "_control_cache"):
            self._control_cache = {}
        key = (url, location, name)
        if key in self._control_cache:
            return self._control_cache[key]
        value = self._make_control_value(payload)
        sample = self._send(url, method, location, name, value=value, request_context=request_context)
        self._control_cache[key] = sample
        return sample

    def _select_payload_value(self, payload: Mutation) -> str | None:
        raw_value = self._decode_raw_value(payload)
        if raw_value is None:
            return None

        transform_chain = cast("list[dict] | None", payload.get("transform_chain"))
        if transform_chain is not None:
            slot_value = cast("str | None", payload.get("slot_value"))
            if slot_value is None:
                raise TransformError("mutation carries a transform_chain but no slot_value")
            return rebuild(slot_value, transform_chain, raw_value)

        encoding_chain = cast("list[str] | None", payload.get("encoding_chain")) or []
        if encoding_chain and all(op in self.REWRAPPABLE_OPS for op in encoding_chain):
            return self._reapply_encoding_chain(raw_value, encoding_chain)
        return raw_value

    def _decode_raw_value(self, payload: Mutation) -> str | None:
        encoding = cast("str | None", payload.get("encoding"))
        b64_payload = cast("str | None", payload.get("payload"))
        payload_raw = cast("str | None", payload.get("payload_raw"))

        if encoding == "base64" and b64_payload:
            try:
                return base64.b64decode(b64_payload).decode("latin-1")
            except Exception:
                return payload_raw or b64_payload
        return payload_raw or b64_payload

    def _reapply_encoding_chain(self, value: str, chain: list[str]) -> str:
        current = value
        for op in reversed(chain):
            if op == "base64":
                current = base64.b64encode(current.encode("latin-1")).decode("ascii")
            elif op == "base64_gzip":
                compressed = gzip.compress(current.encode("latin-1"))
                current = base64.b64encode(compressed).decode("ascii")
            elif op == "hex":
                current = current.encode("latin-1").hex()
            elif op == "url":
                current = urllib.parse.quote(current, safe="", encoding="latin-1")
        return current

    def _send(
        self, url: str, method: str, location: str, name: str, value: str | None,
        request_context: "RequestContext | None" = None,
    ) -> HttpProbeSample:
        request_context = request_context or {}
        headers = {
            k: v for k, v in (request_context.get("headers") or {}).items()
            if k.lower() not in ("content-length", "host", "accept-encoding") and not k.startswith(":")
        }
        headers.setdefault("User-Agent", "EthicalQuoc/replay")
        cookies = dict(request_context.get("cookies") or {})
        ctx_body = request_context.get("body")
        body = ctx_body.encode("utf-8") if isinstance(ctx_body, str) else None
        target_url = url

        if location == "cookie":
            if value is not None:
                cookies[name] = value
        elif location == "header":
            if value is not None:
                headers[name] = value
        elif location in ("query", "url_param"):
            if value is not None:
                parsed = urllib.parse.urlsplit(url)
                encoded_value = urllib.parse.quote(value, safe="", encoding="latin-1")
                new_query = self._replace_pair(parsed.query, name, encoded_value)
                target_url = urllib.parse.urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
                )
        elif location in ("body", "form_body"):
            if value is not None:
                content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
                if "multipart/" in content_type.lower():
                    raise ValueError("multipart form bodies cannot be rebuilt faithfully yet")
                encoded_value = urllib.parse.quote(value, safe="", encoding="latin-1")
                original_body = body.decode("utf-8") if body else ""
                body = self._replace_pair(original_body, name, encoded_value).encode("utf-8")
                if not content_type:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif location == "raw_body":
            if value is not None:
                body = value.encode("latin-1")

        is_testing_cookie_header = location == "header" and name.lower() == "cookie"
        if cookies and not is_testing_cookie_header:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

        req = urllib.request.Request(target_url, data=body, headers=headers, method=method)

        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                elapsed = time.monotonic() - start
                raw = resp.read()
                return {
                    "status": resp.status,
                    "elapsed_sec": round(elapsed, 3),
                    "length": len(raw),
                    "body_sample": raw[:2000].decode("utf-8", errors="replace"),
                    "body_compare": raw[:self.COMPARE_BODY_LIMIT].decode("utf-8", errors="replace"),
                }
        except urllib.error.HTTPError as e:
            elapsed = time.monotonic() - start
            raw = e.read()
            return {
                "status": e.code,
                "elapsed_sec": round(elapsed, 3),
                "length": len(raw),
                "body_sample": raw[:2000].decode("utf-8", errors="replace"),
                "body_compare": raw[:self.COMPARE_BODY_LIMIT].decode("utf-8", errors="replace"),
            }

    @staticmethod
    def _replace_pair(raw: str, name: str, encoded_value: str) -> str:
        parts = raw.split("&") if raw else []
        for i, part in enumerate(parts):
            key = part.split("=", 1)[0]
            if urllib.parse.unquote_plus(key) == name:
                parts[i] = f"{key}={encoded_value}"
                return "&".join(parts)
        parts.append(f"{urllib.parse.quote(name, safe='')}={encoded_value}")
        return "&".join(parts)

    CONTENT_DIFF_SIMILARITY_THRESHOLD = 0.8
    COMPARE_BODY_LIMIT = 20000

    VOLATILE_PATTERNS = [
        re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
        re.compile(r"\b\d{13}\b"),
    ]

    def _strip_volatile(self, text: str) -> str:
        for pattern in self.VOLATILE_PATTERNS:
            text = pattern.sub("<volatile>", text)
        return text

    @staticmethod
    def _reflection_normalize(s: str) -> str:
        s = re.sub(r"\\u[0-9a-fA-F]{4}", "", s)
        s = s.replace('\\"', '"').replace("\\\\", "\\")
        return re.sub(r"[^A-Za-z0-9]", "", s)

    def _is_mere_reflection(self, mutated_body: str, injected_value: str | None) -> bool:
        if not injected_value:
            return False
        unescaped = mutated_body.replace('\\"', '"')
        if injected_value in mutated_body or injected_value in unescaped:
            return True
        inj = re.sub(r"\s+", "", injected_value)
        if len(inj) >= 12 and inj in re.sub(r"\s+", "", unescaped):
            return True
        norm_inj = self._reflection_normalize(injected_value)
        if len(norm_inj) >= 12 and norm_inj in self._reflection_normalize(mutated_body):
            return True
        return False

    OBJECT_REPR_PATTERNS = [
        re.compile(r"#<([A-Z]\w*(?:::[A-Z]\w*)*)"),
        re.compile(r"<([\w.]+) object at 0x[0-9a-f]+>"),
    ]

    @classmethod
    def _new_object_classes(cls, base_text: str, mutated_text: str) -> set[str]:
        def classes(t: str) -> set[str]:
            return {m.group(1) for p in cls.OBJECT_REPR_PATTERNS for m in p.finditer(t)}
        return classes(mutated_text) - classes(base_text)

    def _compare(
        self, baseline: HttpProbeSample, mutated: HttpProbeSample, injected_value: str | None = None,
        control: HttpProbeSample | None = None,
    ) -> tuple[list[str], bool]:
        indicators = []
        strong_signal = False

        mutated_lower = mutated["body_sample"].lower()
        baseline_lower = baseline["body_sample"].lower()
        error_hits = [kw for kw in self.ERROR_KEYWORDS if kw in mutated_lower]
        # Only error keywords that appear in the mutated response but NOT already in the
        # baseline count as mutation-induced. A keyword present in BOTH is a constant
        # endpoint error (e.g. a Java endpoint that always 500s with "objectinputstream"
        # regardless of input) — the mutation changed nothing, so it must not raise strong.
        new_error_hits = [kw for kw in error_hits if kw not in baseline_lower]

        clean_rejection = (400 <= mutated["status"] < 500) and not error_hits

        delay_delta = mutated["elapsed_sec"] - baseline["elapsed_sec"]
        if delay_delta >= self.TIME_DELAY_THRESHOLD_SEC:
            indicators.append(
                f"Time-based: mutated response {delay_delta:.2f}s slower than baseline"
            )
            strong_signal = True

        if mutated["status"] != baseline["status"]:
            suffix = " (clean client rejection — weak)" if clean_rejection else ""
            indicators.append(
                f"Status code changed: baseline={baseline['status']} mutated={mutated['status']}{suffix}"
            )
            if not clean_rejection:
                strong_signal = True

        length_delta = abs(mutated["length"] - baseline["length"])
        length_changed_significantly = baseline["length"] > 0 and length_delta / baseline["length"] > 0.5
        if length_changed_significantly:
            reflected = self._is_mere_reflection(
                mutated.get("body_compare") or mutated["body_sample"], injected_value)
            if clean_rejection:
                suffix = " (clean client rejection — weak)"
            elif reflected:
                suffix = " (response merely reflects the injected payload — weak)"
            else:
                suffix = ""
            indicators.append(
                f"Response length changed significantly: baseline={baseline['length']} mutated={mutated['length']}{suffix}"
            )
            if not clean_rejection and not reflected:
                strong_signal = True
        elif length_delta > 0 and mutated["status"] == baseline["status"] and not error_hits:
            indicators.append(
                f"Observation: response length changed by {mutated['length'] - baseline['length']:+d} bytes "
                f"(baseline={baseline['length']} mutated={mutated['length']}, same status {mutated['status']}) "
                f"— possible behavioral change, verify manually"
            )

        if error_hits:
            if new_error_hits:
                indicators.append(f"Error/exception disclosure in response: {new_error_hits}")
                strong_signal = True
            else:
                indicators.append(
                    f"Error/exception keywords {error_hits} present in BOTH baseline and mutated "
                    f"responses — a constant endpoint error, not triggered by this mutation "
                    f"(no mutation-induced signal — weak)"
                )

        base_cmp = baseline.get("body_compare") or baseline["body_sample"]
        mut_cmp = mutated.get("body_compare") or mutated["body_sample"]
        if (
            mutated["status"] == baseline["status"]
            and not length_changed_significantly
            and not error_hits
            and mut_cmp != base_cmp
            and self._strip_volatile(mut_cmp) != self._strip_volatile(base_cmp)
        ):
            similarity = difflib.SequenceMatcher(None, base_cmp, mut_cmp).ratio()
            if similarity >= self.CONTENT_DIFF_SIMILARITY_THRESHOLD:
                indicators.append(
                    f"Response content differs in a small, localized way despite same status (similarity={similarity:.2f}) "
                    f"(baseline={base_cmp[:200]!r} mutated={mut_cmp[:200]!r})"
                )
                if not self._is_mere_reflection(mut_cmp, injected_value):
                    strong_signal = True

        new_object_classes = self._new_object_classes(base_cmp, mut_cmp)
        if new_object_classes and not self._is_mere_reflection(mut_cmp, injected_value):
            indicators.append(
                f"Response reveals a reconstructed object of type {sorted(new_object_classes)} "
                f"not present in baseline — the server instantiated an attacker-named type "
                f"(deserialization executed)"
            )
            strong_signal = True

        if control is not None and strong_signal:
            has_deser_marker = any(m in mutated_lower for m in self.DESER_SPECIFIC_MARKERS)
            ctrl_cmp = control.get("body_compare") or control.get("body_sample") or ""
            same_status = control["status"] == mutated["status"]
            body_sim = (
                difflib.SequenceMatcher(None, ctrl_cmp, mut_cmp).ratio()
                if ctrl_cmp and mut_cmp else 0.0
            )
            if not has_deser_marker and same_status and body_sim >= self.CONTENT_DIFF_SIMILARITY_THRESHOLD:
                strong_signal = False
                indicators.append(
                    f"Control probe (non-serialized junk) returned the same status {control['status']} and a "
                    f"near-identical body (similarity={body_sim:.2f}) with no deserializer-specific marker — the "
                    f"server reacts the same to any invalid value, so this change is NOT deserialization-specific "
                    f"(downgraded, verify manually)"
                )

        return indicators, strong_signal

    def _skip_result(self, payload: Mutation, reason: str) -> ReplaySkipped:
        return {
            "url": cast("str | None", payload.get("url")),
            "location": cast("str | None", payload.get("location")),
            "name": cast("str | None", payload.get("name")),
            "payload_type": cast("str | None", payload.get("type")),
            "skipped": True,
            "reason": reason,
            "signal": "skipped",
        }
