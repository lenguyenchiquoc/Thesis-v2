"""
Unit test cho Analyze/normalize.py (class DataNormalizer).

Nguyen tac xay dung test o file nay: KHONG suy ra input/output tu viec doc
code co san (se chi khang dinh lai dung nhung gi code dang lam, ke ca neu no
dang sai). Thay vao do, moi test-vector deu lay tu 1 nguon THAM CHIEU BEN
NGOAI, co the kiem chung doc lap:
  - RFC 4648 (Base16/32/64 Data Encodings)      - vector test chinh thuc
  - RFC 1952 (GZIP file format specification)   - magic bytes/cau truc header
  - RFC 8259 (JSON)                             - quy tac escape dau "
  - RFC 7519 (JSON Web Token) + PortSwigger/Auth0/Invicti - JWT alg:none
  - PortSwigger Web Security Academy            - payload PHP serialize THAT
    tu cac lab cong khai (khong tu bia)
"""

import base64
import gzip
import json
import sys
import os
import unittest
import urllib.parse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Analyze.normalize import DataNormalizer


class TestBasicBase64RFC4648(unittest.TestCase):
    """https://www.rfc-editor.org/rfc/rfc4648.html#section-10 - Test Vectors
    chinh thuc cua chuan Base64 (BASE64("") .. BASE64("foobar"))."""

    OFFICIAL_VECTORS = ["Zg==", "Zm8=", "Zm9v", "Zm9vYg==", "Zm9vYmE=", "Zm9vYmFy"]

    def test_official_short_vectors_are_below_the_length_gate(self):
        # Ca 6 vector chinh thuc cua RFC deu < 16 ky tu sau khi chuan hoa padding
        # -> _generate_decodes() co nguong len(val) >= 16 nen se KHONG thu decode
        # -> normalize() phai fallback tra nguyen ban goc, khong duoc bien mat/loi.
        for b64 in self.OFFICIAL_VECTORS:
            with self.subTest(b64=b64):
                result = DataNormalizer(b64).normalize()
                self.assertEqual(result, [b64])

    def test_longer_vector_decodes_to_the_exact_original_bytes(self):
        # Cau pangram tieng Anh noi tieng (chua tat ca 26 chu cai) - de bat ky
        # ai cung co the tu ma hoa lai bang tool base64 doc lap va doi chieu.
        plaintext = "The quick brown fox jumps over the lazy dog"
        encoded = base64.b64encode(plaintext.encode()).decode()
        self.assertGreaterEqual(len(encoded), 16)
        candidates = DataNormalizer(encoded)._generate_decodes(encoded)
        self.assertIn(plaintext, candidates)

    def test_base64url_variant_dash_underscore_decodes_correctly(self):
        # RFC 4648 section 5: bien the "URL and Filename Safe" dung '-'/'_'
        # thay cho '+'/'/'  va thuong bo padding.
        plaintext = b"\xfb\xff\xbf\x00\x01\x02\x03\x04\x05\x06\x07\x08"
        b64url = base64.urlsafe_b64encode(plaintext).decode().rstrip("=")
        candidates = DataNormalizer(b64url)._generate_decodes(b64url)
        self.assertIn(plaintext.decode("latin-1"), candidates)


class TestGzipRFC1952(unittest.TestCase):
    """https://www.rfc-editor.org/rfc/rfc1952.html - GZIP file format:
    ID1=0x1f, ID2=0x8b, CM=8 (deflate)."""

    def test_python_gzip_module_matches_rfc1952_magic_bytes(self):
        raw = gzip.compress(b"hello world")
        self.assertEqual(raw[0], 0x1F, "ID1 phai la 0x1f theo RFC 1952")
        self.assertEqual(raw[1], 0x8B, "ID2 phai la 0x8b theo RFC 1952")
        self.assertEqual(raw[2], 8, "CM phai la 8 (deflate) theo RFC 1952")

    def test_gzip_then_base64_wrapped_text_decompresses(self):
        original = "The quick brown fox jumps over the lazy dog. " * 3
        original = original.strip()
        b64 = base64.b64encode(gzip.compress(original.encode())).decode()
        candidates = DataNormalizer(b64)._generate_decodes(b64)
        self.assertIn(original, candidates)


class TestRealPortSwiggerPayloads(unittest.TestCase):
    """Payload lay dung nguyen van tu tai lieu cong khai PortSwigger Web
    Security Academy (khong tu bia trong session nay):
    - https://portswigger.net/web-security/deserialization/exploiting/lab-deserialization-arbitrary-object-injection-in-php
    - https://portswigger.net/web-security/deserialization/exploiting/lab-deserialization-developing-a-custom-gadget-chain-for-php-deserialization
    """

    def test_arbitrary_object_injection_lab_payload_shape(self):
        payload = ('O:4:"User":2:{s:8:"username";s:6:"wiener";'
                   's:12:"access_token";s:32:"deadbeefdeadbeefdeadbeefdeadbeef";}')
        b64_and_urlencoded = urllib.parse.quote(base64.b64encode(payload.encode()).decode())
        result = DataNormalizer(b64_and_urlencoded).normalize()
        self.assertIn(payload, result)

    def test_custom_gadget_chain_lab_payload_shape(self):
        payload = ('O:14:"CustomTemplate":2:{s:17:"default_desc_type";'
                   's:26:"rm /home/carlos/morale.txt";s:4:"desc";'
                   'O:10:"DefaultMap":1:{s:8:"callback";s:4:"exec";}}')
        b64 = base64.b64encode(payload.encode()).decode()
        result = DataNormalizer(b64).normalize()
        self.assertIn(payload, result)


class TestAdvancedEncodingLayers(unittest.TestCase):
    """Cac ky thuat lop-hoa nhieu tang de qua mat scanner don gian - pho bien
    trong thuc te (double encoding la ky thuat evasion duoc OWASP/nhieu writeup
    security nhac toi thuong xuyen)."""

    PAYLOAD = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:1;}'

    def test_double_base64_encoded_payload(self):
        once = base64.b64encode(self.PAYLOAD.encode()).decode()
        twice = base64.b64encode(once.encode()).decode()
        result = DataNormalizer(twice).normalize()
        self.assertIn(self.PAYLOAD, result, "Phai decode xuyen 2 lop base64 lien tiep (BFS da tang)")

    def test_hex_encoded_payload(self):
        hexed = self.PAYLOAD.encode().hex()
        result = DataNormalizer(hexed).normalize()
        self.assertIn(self.PAYLOAD, result)

    def test_url_encoded_wrapping_base64_payload(self):
        b64 = base64.b64encode(self.PAYLOAD.encode()).decode()
        wrapped = urllib.parse.quote(b64, safe="")
        result = DataNormalizer(wrapped).normalize()
        self.assertIn(self.PAYLOAD, result)

    def test_jwt_alg_none_with_embedded_gadget_rfc7519(self):
        # RFC 7519 dinh nghia "none" la mot alg hop le (Unsecured JWT) - JWT
        # dang nay co chu ky RONG: "header.payload." - da duoc PortSwigger/
        # Auth0/Invicti tai lieu hoa nhu 1 ky thuat tan cong that.
        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
        payload_obj = {"sub": self.PAYLOAD}
        payload = base64.urlsafe_b64encode(json.dumps(payload_obj).encode()).decode().rstrip("=")
        token = f"{header}.{payload}."
        result = DataNormalizer(token).normalize()
        self.assertIn(self.PAYLOAD, result)


class TestBfsTraversalBehavior(unittest.TestCase):
    """Hanh vi cua thuat toan BFS multi-layer trong normalize() (queue, seen-set,
    gioi han max_depth/max_candidate, sort theo diem nhung KHONG cat bot candidate)."""

    def test_plain_text_with_no_encoding_falls_back_unchanged(self):
        text = "just a normal short piece of text, nothing dangerous here"
        result = DataNormalizer(text).normalize()
        self.assertEqual(result, [text])

    def test_empty_string_does_not_crash(self):
        result = DataNormalizer("").normalize()
        self.assertEqual(result, [""])

    def test_no_hard_cap_all_independent_gadgets_survive(self):
        # Truoc day normalize() cat cung con [:2], lam mat cac candidate doc lap
        # (vd 2 gadget PHP khac nhau nam trong 2 claim JWT khac nhau). Da bo cap,
        # gio phai giu du ca 3 candidate doc lap, khong chi giu 2.
        def php_gadget(tag: str) -> str:
            return f'O:19:"Monolog\\Handler\\X":1:{{s:7:"Monolog";s:{len(tag)}:"{tag}";}}'

        claims = {"sub": php_gadget("payloadA"), "role": php_gadget("payloadB"),
                  "session": php_gadget("payloadC")}
        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
        payload_b64 = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        token = f"{header}.{payload_b64}."

        result = DataNormalizer(token).normalize()
        self.assertIn(php_gadget("payloadA"), result)
        self.assertIn(php_gadget("payloadB"), result)
        self.assertIn(php_gadget("payloadC"), result)

    def test_deep_chain_within_max_depth_still_resolves(self):
        # Boc 5 lop base64 lien tiep - van trong gioi han max_depth mac dinh (12).
        value = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:1;}'
        for _ in range(5):
            value = base64.b64encode(value.encode()).decode()
        result = DataNormalizer(value).normalize()
        self.assertIn('O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:1;}', result)


class TestThresholdGapFixed(unittest.TestCase):
    """Regression test cho bug da fix: khoang trong giua Gate 1
    (_generate_decodes() dong 91: len(txt) >= 10) va Gate 2 cu
    (_is_serialized_payload() dong 43: len(value) < 12). Da dong bo ca 2 ve
    cung nguong 10 - test nay dam bao khong ai vo tinh nang nguong Gate 2
    len tro lai > 10 khien khoang trong tai xuat hien."""

    def test_11_byte_decoded_payload_is_no_longer_lost(self):
        target = "i:12345678;"  # PHP serialize so nguyen, dung 11 ky tu
        self.assertEqual(len(target), 11)
        encoded = base64.b64encode(target.encode()).decode()
        result = DataNormalizer(encoded).normalize()
        self.assertIn(target, result)

    def test_10_byte_boundary_also_recognized(self):
        target = "i:1234567;"  # dung 10 ky tu - dung bien duoi cua Gate 1
        self.assertEqual(len(target), 10)
        encoded = base64.b64encode(target.encode()).decode()
        result = DataNormalizer(encoded).normalize()
        self.assertIn(target, result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
