"""
Unit test cho Scanner/har_loader.py (class HarLoader).

Bug regression: mot request HAR mang CUNG 1 du lieu cookie o 2 noi doc lap -
`request.cookies[]` (da duoc trinh duyet/HAR-capture-tool tach san, 1 entry/
cookie) VA `request.headers[]` (dong "Cookie:" tho, dang composite noi boi
"; "). Neu loader tao vector rieng cho CA 2 noi, vector header/Cookie se la
ban sao mo ta lai dung du lieu da co trong cac vector cookie/* - khi replay,
vector header/Cookie ghi de THANG vao headers["Cookie"] (xem
Replay/replay_request.py _send(), nhanh location=="header") nen xoa mat cac
cookie khac (vd session token thuc), gay false-positive.

Tham chieu doc lap: HAR 1.2 spec (ahmadnassri/har-spec) - field `cookies` cua
request object la field BAT BUOC phai ton tai (co the la mang rong `[]`), tuc
spec KHONG dam bao no luon duoc dien day du moi khi co header `Cookie` tho -
vi vay fix phai la "skip co dieu kien" (chi skip khi cookies[] da co du lieu),
khong phai "skip vo dieu kien", de khong mat kha nang test voi HAR tu nguon
khac Chrome.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Scanner.har_loader import HarLoader


def process(entry: dict) -> list[dict]:
    loader = HarLoader("unused.har")
    loader._process_entry(entry)
    return loader.vectors


def make_entry(headers: list[dict], cookies: list[dict], url="http://example.test/api/profile", method="GET") -> dict:
    return {
        "request": {
            "url": url,
            "method": method,
            "headers": headers,
            "cookies": cookies,
            "queryString": [],
        }
    }


class TestCookieHeaderSkippedWhenCookiesArrayPopulated(unittest.TestCase):
    """Case thuc te da gay bug: 4 cookie giong HAR thuc (next-auth.session-token,
    ref_tag, prefs, session), dong Cookie header la composite cua ca 4 - sau fix
    phai CHI con 4 vector cookie/*, khong con vector header/Cookie nao."""

    def setUp(self):
        self.cookies = [
            {"name": "next-auth.session-token", "value": "tok123"},
            {"name": "ref_tag", "value": "O%3A3%3A%22Tag%22"},
            {"name": "prefs", "value": "%7B%22theme%22%3A%22dark%22%7D"},
            {"name": "session", "value": "rO0AB"},
        ]
        composite = "; ".join(f"{c['name']}={c['value']}" for c in self.cookies)
        self.headers = [
            {"name": "Cookie", "value": composite},
            {"name": "User-Agent", "value": "test-agent"},
        ]

    def test_no_header_cookie_vector_is_created(self):
        vectors = process(make_entry(self.headers, self.cookies))
        header_cookie = [v for v in vectors if v["location"] == "header" and v["name"].lower() == "cookie"]
        self.assertEqual(header_cookie, [])

    def test_all_four_cookie_vectors_still_created_independently(self):
        vectors = process(make_entry(self.headers, self.cookies))
        cookie_vectors = {v["name"]: v["value"] for v in vectors if v["location"] == "cookie"}
        self.assertEqual(cookie_vectors, {c["name"]: c["value"] for c in self.cookies})

    def test_other_headers_are_unaffected(self):
        vectors = process(make_entry(self.headers, self.cookies))
        ua = [v for v in vectors if v["location"] == "header" and v["name"] == "User-Agent"]
        self.assertEqual(len(ua), 1)
        self.assertEqual(ua[0]["value"], "test-agent")

    def test_case_insensitive_cookie_header_name_is_also_skipped(self):
        headers = [{"name": "COOKIE", "value": "a=1"}]
        vectors = process(make_entry(headers, [{"name": "a", "value": "1"}]))
        header_cookie = [v for v in vectors if v["location"] == "header"]
        self.assertEqual(header_cookie, [])


class TestCookieHeaderKeptAsFallbackWhenCookiesArrayEmpty(unittest.TestCase):
    """HAR 1.2 khong bat buoc cookies[] phai duoc dien day du (vd HAR tu
    mitmproxy/Burp export) - trong truong hop do vector header/Cookie la nguon
    DUY NHAT con lai de test, nen phai duoc GIU, khong duoc skip."""

    def test_header_cookie_vector_survives_when_cookies_array_is_empty(self):
        headers = [{"name": "Cookie", "value": "a=1; b=2"}]
        vectors = process(make_entry(headers, cookies=[]))
        header_cookie = [v for v in vectors if v["location"] == "header" and v["name"].lower() == "cookie"]
        self.assertEqual(len(header_cookie), 1)
        self.assertEqual(header_cookie[0]["value"], "a=1; b=2")

    def test_no_cookie_located_vectors_exist_in_that_case(self):
        headers = [{"name": "Cookie", "value": "a=1; b=2"}]
        vectors = process(make_entry(headers, cookies=[]))
        cookie_vectors = [v for v in vectors if v["location"] == "cookie"]
        self.assertEqual(cookie_vectors, [])


class TestRequestContextStillCarriesFullCookieHeaderRegardless(unittest.TestCase):
    """Bo vector header/Cookie KHONG duoc lam mat du lieu trong request_context -
    _build_request_context() phai van copy nguyen headers['Cookie'] cho moi
    vector (dung lam baseline headers khi replay), bat ke co bi skip lam vector
    rieng hay khong."""

    def test_request_context_headers_cookie_is_preserved(self):
        headers = [{"name": "Cookie", "value": "a=1; b=2"}]
        cookies = [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]
        vectors = process(make_entry(headers, cookies))
        self.assertTrue(vectors)
        for v in vectors:
            self.assertEqual(v["request_context"]["headers"]["Cookie"], "a=1; b=2")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# --- Bug P (2026-11-25): urlencoded form / query values must reach replay DECODED -------------
# Chrome DevTools keeps postData.params[].value and queryString[].value %-encoded; the extension
# records postData.text only (no params). Both made replay send a broken value (P1: encoded twice;
# P2: the whole "cart=..." body overwritten, key lost). The loader now splits the wire text itself.

import urllib.parse  # noqa: E402

from Replay.replay_request import ReplayRequest  # noqa: E402

PHP_CART = 'O:4:"Cart":1:{s:5:"owner";s:6:"wiener";}'
JAVA_B64 = "rO0ABXNy+/AB=="          # base64 alphabet incl. + / = (all %-encoded in a form)
FORM_CT = "application/x-www-form-urlencoded;charset=UTF-8"


def form_entry(fields: dict, with_params: bool, encoded_params: bool = True,
               url="http://example.test/api/cart") -> dict:
    text = urllib.parse.urlencode(fields)
    post = {"mimeType": FORM_CT, "text": text}
    if with_params:
        post["params"] = [{"name": k, "value": urllib.parse.quote_plus(v) if encoded_params else v}
                          for k, v in fields.items()]
    return {"request": {"url": url, "method": "POST",
                        "headers": [{"name": "Content-Type", "value": FORM_CT}],
                        "cookies": [], "postData": post}}


def server_view(vector: dict, payload: str) -> dict:
    """What the server's form parser sees after replay swaps `payload` into this vector."""
    body = ReplayRequest._replace_pair(vector["request_context"]["body"], vector["name"],
                                       urllib.parse.quote(payload, safe="", encoding="latin-1"))
    return urllib.parse.parse_qs(body)


class TestUrlencodedFormSplitIntoDecodedFields(unittest.TestCase):

    def _cart(self, entry):
        vs = [v for v in process(entry) if v["location"] in ("form_body", "raw_body")]
        self.assertEqual(len(vs), 1)
        return vs[0]

    def test_devtools_style_encoded_params_are_decoded(self):
        v = self._cart(form_entry({"cart": PHP_CART}, with_params=True))
        self.assertEqual((v["location"], v["name"], v["value"]), ("form_body", "cart", PHP_CART))

    def test_extension_style_text_only_becomes_form_field_not_raw_body(self):
        v = self._cart(form_entry({"cart": PHP_CART}, with_params=False))
        self.assertEqual((v["location"], v["name"], v["value"]), ("form_body", "cart", PHP_CART))

    def test_already_decoded_params_give_the_same_value(self):
        v = self._cart(form_entry({"cart": PHP_CART}, with_params=True, encoded_params=False))
        self.assertEqual(v["value"], PHP_CART)

    def test_base64_plus_slash_equals_survive(self):
        for with_params in (True, False):
            v = self._cart(form_entry({"cart": JAVA_B64}, with_params=with_params))
            self.assertEqual(v["value"], JAVA_B64)

    def test_replayed_payload_reaches_server_exactly_once_encoded_and_keeps_other_fields(self):
        gadget = 'O:1:"X":1:{s:1:"a";s:3:"+/%";}'
        for with_params in (True, False):
            entry = form_entry({"csrf": "t0k+n", "cart": PHP_CART}, with_params=with_params)
            cart = [v for v in process(entry) if v["name"] == "cart"][0]
            seen = server_view(cart, gadget)
            self.assertEqual(seen["cart"], [gadget])
            self.assertEqual(seen["csrf"], ["t0k+n"])

    def test_non_form_text_body_is_still_one_raw_body_vector(self):
        entry = {"request": {"url": "http://example.test/api/import", "method": "POST",
                             "headers": [{"name": "Content-Type", "value": "application/json"}],
                             "cookies": [], "postData": {"mimeType": "application/json",
                                                         "text": '{"a":"b=c&d"}'}}}
        vs = [v for v in process(entry) if v["location"] in ("form_body", "raw_body")]
        self.assertEqual([(v["location"], v["name"]) for v in vs], [("raw_body", "payload")])


class TestQueryParamsDecodedFromUrl(unittest.TestCase):

    def test_encoded_query_value_is_decoded_whatever_queryString_says(self):
        url = "http://example.test/api/doc?file=..%2Fdocuments%2Fwelcome.txt&data=" + urllib.parse.quote(PHP_CART)
        entry = {"request": {"url": url, "method": "GET", "headers": [], "cookies": [],
                             "queryString": [{"name": "file", "value": "..%2Fdocuments%2Fwelcome.txt"}]}}
        got = {v["name"]: v["value"] for v in process(entry) if v["location"] == "url_param"}
        self.assertEqual(got, {"file": "../documents/welcome.txt", "data": PHP_CART})

    def test_param_only_in_queryString_keeps_legacy_value(self):
        # hand-built HARs (TestCase/comprehensive.har) list params without a query in the URL
        entry = {"request": {"url": "http://example.test/api/task", "method": "GET", "headers": [],
                             "cookies": [], "queryString": [{"name": "token", "value": "H4sI%2Fab"}]}}
        got = [(v["name"], v["value"]) for v in process(entry) if v["location"] == "url_param"]
        self.assertEqual(got, [("token", "H4sI%2Fab")])

    def test_param_in_both_url_and_queryString_is_not_duplicated(self):
        entry = {"request": {"url": "http://example.test/a?x=%2F", "method": "GET", "headers": [],
                             "cookies": [], "queryString": [{"name": "x", "value": "%2F"}]}}
        got = [(v["name"], v["value"]) for v in process(entry) if v["location"] == "url_param"]
        self.assertEqual(got, [("x", "/")])
