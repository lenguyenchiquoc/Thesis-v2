import json
import os
from urllib.parse import parse_qsl, unquote_plus, urlparse


class HarLoader:

    def __init__(self, file_path):
        self.file_path = file_path
        self.ignore_ext = {"jpg", "jpeg", "png", "gif", "css", "js", "svg", "mp4", "mp3"}
        self.vectors = []
        self.target_name = None

    def parse(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                har_data = json.load(f)
            return self.parse_data(har_data)
        except Exception as e:
            print(f"[!] HAR Parsing failed: {e}")
            return []

    def parse_data(self, har_data):
        try:
            entries = har_data['log']['entries']
            if not entries:
                print("[!] HAR file empty")
                return []

            first_url = entries[0]['request']['url']
            self.target_name = urlparse(first_url).netloc

            for entry in entries:
                self._process_entry(entry)

            raw_count = len(self.vectors)
            self.vectors = self._dedup(self.vectors)
            collapsed = raw_count - len(self.vectors)
            msg = f"[+] Passive Scan: Extracted {len(self.vectors)} vectors"
            if collapsed:
                msg += f" ({collapsed} duplicate request(s) collapsed)"
            print(msg)
            return self.vectors

        except Exception as e:
            print(f"[!] HAR Parsing failed: {e}")
            return []

    def _build_request_context(self, req):
        headers = {h['name']: h['value'] for h in req.get('headers', [])}
        cookies = {c['name']: c['value'] for c in req.get('cookies', [])}
        post_data = req.get('postData', {})
        body = post_data.get('text') if 'text' in post_data else None
        return {"headers": headers, "cookies": cookies, "body": body}

    def _process_entry(self, entry):
        req = entry['request']
        url = req['url']
        has_parsed_cookies = bool(req.get('cookies'))

        path = urlparse(url).path
        ext = path.split('.')[-1].lower()
        if ext in self.ignore_ext:
            return

        request_context = self._build_request_context(req)

        # Query params are re-parsed from the URL itself, not taken from queryString[]: HAR
        # producers disagree on that array (Chrome DevTools keeps values %-encoded, the
        # extension's URLSearchParams decodes them), and the encoded form made replay encode
        # the payload twice (bug P1, 2026-11-25). Values come out DECODED; replay
        # (_send, url_param) percent-encodes exactly once. latin-1 keeps every byte 1:1,
        # matching replay's quote(..., encoding="latin-1").
        url_params = self._parse_urlencoded(urlparse(url).query)
        for name, value in url_params:
            self._add_vector(url, req['method'], "url_param", name, value, request_context)
        # A param listed only in queryString[] (URL carries no such query — hand-built /
        # synthetic HARs, e.g. TestCase/comprehensive.har) keeps the legacy as-is reading.
        in_url = {name for name, _ in url_params}
        for param in req.get('queryString', []):
            if param['name'] not in in_url:
                self._add_vector(url, req['method'], "url_param", param['name'], param['value'], request_context)

        for cookie in req.get('cookies', []):
            self._add_vector(url, req['method'], "cookie", cookie['name'], cookie['value'], request_context)

        for header in req.get('headers', []):
            if has_parsed_cookies and header['name'].lower() == "cookie":
                continue
            self._add_vector(url, req['method'], "header", header['name'], header['value'], request_context)

        post_data = req.get('postData', {})

        if self._is_urlencoded_form(post_data, request_context["headers"]):
            # A urlencoded form body is split into its fields here, for every HAR producer,
            # from the raw wire text (bug P, 2026-11-25): DevTools' params[] keep values
            # %-encoded (-> replay double-encoded, P1) and the extension records no params at
            # all, so the whole "cart=..." body became one raw_body slot whose key the payload
            # then overwrote (P2). Values come out DECODED; replay (_send, form_body) swaps
            # just that pair and percent-encodes it exactly once.
            if 'text' in post_data:
                fields = self._parse_urlencoded(post_data['text'] or "")
            else:  # params only, no wire text: same %-decoding as the text path
                fields = [(unquote_plus(p['name'], encoding="latin-1"),
                           unquote_plus(p.get('value', ""), encoding="latin-1"))
                          for p in post_data.get('params', [])]
            for name, value in fields:
                self._add_vector(url, req['method'], "form_body", name, value, request_context)

        elif 'params' in post_data:
            for p in post_data['params']:
                self._add_vector(url, req['method'], "form_body", p['name'], p['value'], request_context)

        elif 'text' in post_data:
            self._add_vector(url, req['method'], "raw_body", "payload", post_data['text'], request_context)

    @staticmethod
    def _parse_urlencoded(raw):
        return parse_qsl(raw, keep_blank_values=True, encoding="latin-1")

    @staticmethod
    def _is_urlencoded_form(post_data, headers):
        mime = post_data.get('mimeType') or next(
            (v for k, v in headers.items() if k.lower() == "content-type"), "")
        return "application/x-www-form-urlencoded" in (mime or "").lower()

    def _dedup(self, vectors):
        """Collapse vectors identical on (url, method, location, name, value) —
        the same request captured more than once, e.g. a page re-visited during
        capture. Every downstream stage (normalize, fingerprint, mutation,
        phpggc/ysoserial generation, replay) is a pure function of exactly this
        tuple, so identical vectors always yield identical findings; keeping one
        and recording how many times it was seen is lossless and cuts duplicate
        process spawns + replay traffic. A difference in ANY field keeps the
        vectors separate — the same cookie on two endpoints, or two different
        values on one endpoint, are genuinely distinct tests, not duplicates.
        Raw value is used (pre-clean) and dict insertion order preserves the
        first occurrence."""
        unique = {}
        for v in vectors:
            key = (v["url"], v["method"], v["location"], v["name"], v["value"])
            existing = unique.get(key)
            if existing is None:
                v["occurrences"] = 1
                unique[key] = v
            else:
                existing["occurrences"] += 1
        return list(unique.values())

    def _add_vector(self, url, method, location, name, value, request_context):
        self.vectors.append({
            "source": "har",
            "url": url,
            "method": method,
            "location": location,
            "name": name,
            "value": value,
            "request_context": request_context
        })
    
