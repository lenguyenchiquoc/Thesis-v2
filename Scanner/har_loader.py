import json
import os
from urllib.parse import urlparse


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

            print(f"[+] Passive Scan: Extracted {len(self.vectors)} vectors")
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

        for param in req.get('queryString', []):
            self._add_vector(url, req['method'], "url_param", param['name'], param['value'], request_context)

        for cookie in req.get('cookies', []):
            self._add_vector(url, req['method'], "cookie", cookie['name'], cookie['value'], request_context)

        for header in req.get('headers', []):
            if has_parsed_cookies and header['name'].lower() == "cookie":
                continue
            self._add_vector(url, req['method'], "header", header['name'], header['value'], request_context)

        post_data = req.get('postData', {})

        if 'params' in post_data:
            for p in post_data['params']:
                self._add_vector(url, req['method'], "form_body", p['name'], p['value'], request_context)

        elif 'text' in post_data:
            self._add_vector(url, req['method'], "raw_body", "payload", post_data['text'], request_context)

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
    
