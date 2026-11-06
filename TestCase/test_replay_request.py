"""
Unit test cho Replay/replay_request.py (ReplayRequest._compare()).

Regression: truoc fix, "likely_vulnerable" duoc tinh bang len(indicators) > 0
- tuc la BAT KY indicator nao (ke ca loai yeu nhat, "content differs in a
small way") cung lam likely_vulnerable=True, giong het nhu khi co bang chung
manh (status/error/time). Case thuc te gay nham lan: cookie `ref_tag` tren
java-vuln-app chi duoc PortalApiController.java doc + urlDecode() roi echo
thang ra JSON (KHONG he unserialize/ObjectInputStream) - nhung vi gia tri bi
doi van duoc echo lai, _compare() van sinh ra dung 1 indicator "content
differs in a small way", khien likely_vulnerable=True y het nhu case
`session` cookie (co ClassCastException + OOB callback xac nhan thuc).

Fix: tach rieng "co indicator" (de hien thi, van giu nguyen) voi
"strong_signal" (dung de quyet dinh likely_vulnerable) - content-similarity
diff mot minh KHONG du manh.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Replay.replay_request import ReplayRequest


def sample(status=200, elapsed_sec=0.01, length=100, body_sample="") -> dict:
    return {"status": status, "elapsed_sec": elapsed_sec, "length": length, "body_sample": body_sample}


class TestLikelyVulnerableWeighting(unittest.TestCase):
    def setUp(self):
        self.r = ReplayRequest()

    def test_identical_responses_produce_no_indicators_and_not_vulnerable(self):
        baseline = sample(body_sample="hello world")
        mutated = sample(body_sample="hello world")
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertEqual(indicators, [])
        self.assertFalse(strong)

    def test_weak_content_echo_alone_is_not_strong_signal(self):
        baseline = sample(body_sample='{"referral_tag":"organic","username":"wiener"}')
        mutated = sample(body_sample='{"referral_tag":"admin","username":"wiener"}')
        indicators, strong = self.r._compare(baseline, mutated, injected_value="admin")
        self.assertEqual(len(indicators), 1)
        self.assertIn("content differs in a small", indicators[0])
        self.assertFalse(strong, "Echo thuan cua chinh gia tri da inject thi KHONG duoc tinh la likely_vulnerable")

    def test_derived_value_not_matching_injected_payload_is_strong_signal(self):
        baseline = sample(body_sample='{"username":"wiener","role":"user"}')
        mutated = sample(body_sample='{"username":"wiener","role":"admin"}')
        injected = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:1;}'
        indicators, strong = self.r._compare(baseline, mutated, injected)
        self.assertTrue(strong, "Gia tri 'role':'admin' khong phai echo cua payload da gui -> phai la strong signal")

    def test_reflection_check_handles_json_escaped_quotes(self):
        injected = 'O:3:"Tag":1:{s:4:"name";s:5:"admin";}'
        baseline = sample(body_sample='{"referral_tag":"O:3:\\"Tag\\":1:{s:4:\\"name\\";s:7:\\"organic\\";}"}')
        mutated = sample(body_sample='{"referral_tag":"O:3:\\"Tag\\":1:{s:4:\\"name\\";s:5:\\"admin\\";}"}')
        indicators, strong = self.r._compare(baseline, mutated, injected)
        self.assertFalse(strong, "Echo thuan van la echo du body JSON co escape dau nhay kep")

    def test_reflection_check_handles_json_unicode_escaped_control_bytes(self):
        injected = (
            'O:32:"Monolog\\Handler\\SyslogUdpHandler":1:{s:9:"\x00*\x00socket";'
            'O:29:"Monolog\\Handler\\BufferHandler":7:{s:10:"\x00*\x00handler";'
            's:13:"\x00*\x00bufferSize";i:-1;s:6:"whoami";}}'
        )
        echoed = (
            injected.replace("\\", "\\\\").replace('"', '\\"').replace("\x00", "\\u0000")
        )
        baseline = sample(length=224, body_sample='{"referral_tag":"O:3:\\"Tag\\":1:{s:4:\\"name\\";s:7:\\"organic\\";}"}')
        mutated = sample(length=633, body_sample='{"referral_tag":"' + echoed + '"}')
        indicators, strong = self.r._compare(baseline, mutated, injected)
        self.assertTrue(any("length changed significantly" in i.lower() for i in indicators),
                        "length tang >50% phai sinh indicator length")
        self.assertFalse(strong, "Gadget to bi echo nguyen van (NUL->\\u0000) van la reflection -> KHONG strong")

    def test_status_code_change_is_strong_signal(self):
        baseline = sample(status=200)
        mutated = sample(status=500)
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Status code changed" in i for i in indicators))
        self.assertTrue(strong)

    def test_error_disclosure_is_strong_signal(self):
        baseline = sample(status=200, body_sample='{"role":"user"}')
        mutated = sample(
            status=500,
            body_sample='{"error":"failed to deserialize session via ObjectInputStream: java.lang.ClassCastException"}',
        )
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Error/exception disclosure" in i for i in indicators))
        self.assertTrue(strong)

    def test_significant_length_change_is_strong_signal(self):
        baseline = sample(length=35, body_sample="x" * 35)
        mutated = sample(length=170, body_sample="y" * 170)
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("length changed significantly" in i for i in indicators))
        self.assertTrue(strong)

    def test_time_based_delay_is_strong_signal(self):
        baseline = sample(elapsed_sec=0.01)
        mutated = sample(elapsed_sec=5.0)
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Time-based" in i for i in indicators))
        self.assertTrue(strong)

    def test_clean_4xx_rejection_without_exception_is_weak(self):
        baseline = sample(status=200, length=120, body_sample='{"username":"wiener","role":"user"}')
        mutated = sample(status=401, length=28, body_sample='{"error":"Not authenticated"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Status code changed" in i for i in indicators))
        self.assertFalse(strong, "4xx sach (khong lo exception) la tu choi phong thu, khong phai strong signal")

    def test_clean_4xx_rejection_secure_theme_is_weak(self):
        baseline = sample(status=200, length=101, body_sample='{"success":true,"name":"custom","backgroundType":"x"}')
        mutated = sample(status=400, length=25, body_sample='{"error":"Invalid theme"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertFalse(strong)

    def test_4xx_that_leaks_exception_is_still_strong(self):
        baseline = sample(status=200, length=100, body_sample='{"success":true}')
        mutated = sample(
            status=400, length=400,
            body_sample='{"error":"...com.fasterxml.jackson.databind.exc.InvalidTypeIdException: denied resolution"}',
        )
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Error/exception disclosure" in i for i in indicators))
        self.assertTrue(strong, "4xx co lo exception/stacktrace thi van la strong")

    def test_timestamp_only_diff_is_not_flagged(self):
        baseline = sample(status=404, length=100,
                          body_sample='{"timestamp":"2026-10-15T08:05:58.094+00:00","status":404,"error":"Not Found","path":"/favicon.ico"}')
        mutated = sample(status=404, length=100,
                         body_sample='{"timestamp":"2026-10-15T08:05:58.100+00:00","status":404,"error":"Not Found","path":"/favicon.ico"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertEqual(indicators, [], "Khac biet duy nhat la timestamp -> khong co indicator nao")
        self.assertFalse(strong)

    def test_minor_length_change_is_observation_not_strong(self):
        baseline = sample(status=200, length=3307, body_sample="A" * 100)
        mutated = sample(status=200, length=3376, body_sample="A" * 100)
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Observation: response length changed" in i for i in indicators))
        self.assertFalse(strong, "Thay doi length nho + same status = observation, khong auto-confirm")

    def test_deep_content_diff_beyond_body_sample_is_detected(self):
        head = "X" * 2500
        base_body = head + "<p>My Account: wiener</p>"
        mut_body = head + "<p>My Account: wiener</p><a href=/admin>Admin panel</a>"
        baseline = {"status": 200, "elapsed_sec": 0.01, "length": len(base_body),
                    "body_sample": base_body[:2000], "body_compare": base_body}
        mutated = {"status": 200, "elapsed_sec": 0.01, "length": len(mut_body),
                   "body_sample": mut_body[:2000], "body_compare": mut_body}
        injected = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:1;}'
        indicators, strong = self.r._compare(baseline, mutated, injected)
        self.assertTrue(any("content differs" in i.lower() for i in indicators))
        self.assertTrue(strong, "Diff sau 2000 ky tu (admin link) phai bat duoc qua body_compare")

    def test_control_probe_downgrades_generic_500(self):
        body500 = "<html><h1>Internal Server Error</h1></html>"
        baseline = sample(status=200, length=100, body_sample="<html>welcome</html>")
        mutated = sample(status=500, length=len(body500), body_sample=body500)
        control = sample(status=500, length=len(body500), body_sample=body500)
        indicators, strong = self.r._compare(baseline, mutated, control=control)
        self.assertFalse(strong, "500 giong het control rac -> downgrade")
        self.assertTrue(any("Control probe" in i for i in indicators))

    def test_control_probe_keeps_strong_when_deser_marker_present(self):
        baseline = sample(status=200, length=100, body_sample="<html>welcome</html>")
        mutated = sample(status=500, length=200,
                         body_sample="java.io.ObjectInputStream.readObject ClassCastException trace")
        control = sample(status=500, length=40, body_sample="<html>Internal Server Error</html>")
        indicators, strong = self.r._compare(baseline, mutated, control=control)
        self.assertTrue(strong, "500 co ObjectInputStream = bang chung deser that -> giu strong")

    def test_control_probe_clean_reject_keeps_strong(self):
        baseline = sample(status=200, length=100, body_sample="<html>welcome</html>")
        mutated = sample(status=500, length=120, body_sample="<html>oops page here</html>")
        control = sample(status=401, length=30, body_sample='{"msg":"unauthorized"}')
        indicators, strong = self.r._compare(baseline, mutated, control=control)
        self.assertTrue(strong, "Control 401 sach vs attack 500 -> giu strong")

    def test_strong_and_weak_indicators_can_coexist(self):
        baseline = sample(status=200, body_sample='{"role":"user"}')
        mutated = sample(status=500, body_sample='{"error":"exception: bad object"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertGreaterEqual(len(indicators), 1)
        self.assertTrue(strong)

    def test_reconstructed_object_repr_new_class_is_strong_signal(self):
        baseline = sample(length=69, body_sample='{"success":true,"restored":"{\\"theme\\"=>\\"dark\\"}"}')
        mutated = sample(length=70, body_sample='{"success":true,"restored":"#<Object:0x000075118edeb6c8 @cmd=\\"id\\">"}')
        indicators, strong = self.r._compare(baseline, mutated, injected_value=None)
        self.assertTrue(strong)
        self.assertTrue(any("reconstructed object" in i for i in indicators))

    def test_reconstructed_object_class_swap_is_strong_signal(self):
        baseline = sample(body_sample='{"restored":"#<OpenStruct theme=\\"dark\\", lang=\\"en\\">"}')
        mutated = sample(body_sample='{"restored":"#<Object:0x000075118ed56500>"}')
        indicators, strong = self.r._compare(baseline, mutated, injected_value=None)
        self.assertTrue(strong)
        self.assertTrue(any("reconstructed object" in i for i in indicators))

    def test_reconstructed_object_repr_python_object(self):
        baseline = sample(body_sample='{"restored":{"theme":"dark"}}')
        mutated = sample(body_sample='{"restored":"<__main__.Preferences object at 0x7f0012ab34cd>"}')
        indicators, strong = self.r._compare(baseline, mutated, injected_value=None)
        self.assertTrue(strong)
        self.assertTrue(any("reconstructed object" in i for i in indicators))

    def test_same_object_class_does_not_trigger_reconstructed_indicator(self):
        baseline = sample(body_sample='{"config":"#<OpenStruct theme=\\"dark\\">"}')
        mutated = sample(body_sample='{"config":"#<OpenStruct theme=\\"light\\">"}')
        indicators, _ = self.r._compare(baseline, mutated, injected_value=None)
        self.assertFalse(any("reconstructed object" in i for i in indicators))


class TestSendEncodesContextBodyAsUtf8(unittest.TestCase):
    """GAP A regression: captured request body is UTF-8 text (har_loader reads the HAR as
    UTF-8). Before the fix _send() re-encoded it with latin-1, so a genuine non-Latin-1 char
    in the recorded body (e.g. "ẻ" / U+1EBB on ruby-vuln /api/login) raised UnicodeEncodeError
    and every mutation on that vector was skipped. After the fix the body round-trips as UTF-8."""

    def test_context_body_with_vietnamese_char_is_sent_as_utf8_not_skipped(self):
        import urllib.request
        from unittest import mock

        captured = {}

        class _FakeResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"ok"

        def _fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            return _FakeResp()

        body = '{"username":"nguyẻn","password":"x"}'
        ctx = {"headers": {"Content-Type": "application/json"}, "cookies": {}, "body": body}

        r = ReplayRequest()
        with mock.patch.object(urllib.request, "urlopen", _fake_urlopen):
            out = r._send(
                "http://localhost/api/login", "POST", "cookie", "ref_tag",
                "TzozOiJUYWciOjE6e3M6NDoibmFtZSI7czo1OiJhZG1pbiI7fQ==", ctx,
            )

        self.assertEqual(out["status"], 200)
        self.assertEqual(captured["data"], body.encode("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
