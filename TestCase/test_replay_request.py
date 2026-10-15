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
        # Dung dung case thuc te: /api/profile echo lai ref_tag, khong
        # unserialize - status/length giu nguyen, chi noi dung thay doi nhe,
        # va gia tri thay doi do CHINH LA gia tri da inject (echo thuan).
        baseline = sample(body_sample='{"referral_tag":"organic","username":"wiener"}')
        mutated = sample(body_sample='{"referral_tag":"admin","username":"wiener"}')
        indicators, strong = self.r._compare(baseline, mutated, injected_value="admin")
        self.assertEqual(len(indicators), 1)
        self.assertIn("content differs in a small", indicators[0])
        self.assertFalse(strong, "Echo thuan cua chinh gia tri da inject thi KHONG duoc tinh la likely_vulnerable")

    def test_derived_value_not_matching_injected_payload_is_strong_signal(self):
        # Regression quan trong: phat hien khi review PHP - session cookie
        # (PortSwigger-style privilege escalation that bang flip_boolean) cho
        # ra dung 1 indicator weak giong het ref_tag ("role":"user"->"admin",
        # status/length khong doi) - nhung day la processing THAT (server tu
        # tinh role tu du lieu da bi tamper), khong phai echo, vi chuoi
        # "admin" trong response KHONG nam trong payload da inject (payload la
        # ca 1 object PHP serialize, khong phai chuoi "admin" don le).
        baseline = sample(body_sample='{"username":"wiener","role":"user"}')
        mutated = sample(body_sample='{"username":"wiener","role":"admin"}')
        injected = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:1;}'
        indicators, strong = self.r._compare(baseline, mutated, injected)
        self.assertTrue(strong, "Gia tri 'role':'admin' khong phai echo cua payload da gui -> phai la strong signal")

    def test_reflection_check_handles_json_escaped_quotes(self):
        # Gia tri inject (PHP serialize) co dau nhay kep "..." - khi server
        # echo lai trong 1 chuoi JSON, cac dau nhay do bi JSON tu escape thanh
        # \" - _is_mere_reflection phai van nhan ra day la echo thuan.
        injected = 'O:3:"Tag":1:{s:4:"name";s:5:"admin";}'
        baseline = sample(body_sample='{"referral_tag":"O:3:\\"Tag\\":1:{s:4:\\"name\\";s:7:\\"organic\\";}"}')
        mutated = sample(body_sample='{"referral_tag":"O:3:\\"Tag\\":1:{s:4:\\"name\\";s:5:\\"admin\\";}"}')
        indicators, strong = self.r._compare(baseline, mutated, injected)
        self.assertFalse(strong, "Echo thuan van la echo du body JSON co escape dau nhay kep")

    def test_status_code_change_is_strong_signal(self):
        baseline = sample(status=200)
        mutated = sample(status=500)
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Status code changed" in i for i in indicators))
        self.assertTrue(strong)

    def test_error_disclosure_is_strong_signal(self):
        # Dung dung case thuc te: SessionCookieFilter.java echo
        # "...ObjectInputStream: ClassCastException..." vao body loi.
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
        # java-app-secure: mot session cookie bi tamper -> SessionCookieFilter tu
        # choi sach bang 401 "Not authenticated" (KHONG lo exception). Day la hanh
        # vi phong thu dung, khong phai lo hong -> status doi nhung KHONG strong.
        baseline = sample(status=200, length=120, body_sample='{"username":"wiener","role":"user"}')
        mutated = sample(status=401, length=28, body_sample='{"error":"Not authenticated"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Status code changed" in i for i in indicators))
        self.assertFalse(strong, "4xx sach (khong lo exception) la tu choi phong thu, khong phai strong signal")

    def test_clean_4xx_rejection_secure_theme_is_weak(self):
        # java-app-secure theme: payload gadget khong khop kieu Map -> 400
        # "Invalid theme" sach. Status + length doi nhung khong lo exception.
        baseline = sample(status=200, length=101, body_sample='{"success":true,"name":"custom","backgroundType":"x"}')
        mutated = sample(status=400, length=25, body_sample='{"error":"Invalid theme"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertFalse(strong)

    def test_4xx_that_leaks_exception_is_still_strong(self):
        # Doi lap: webhook VULN tra 400 NHUNG lo InvalidTypeIdException ->
        # error disclosure -> van phai strong (khong bi downgrade thanh clean).
        baseline = sample(status=200, length=100, body_sample='{"success":true}')
        mutated = sample(
            status=400, length=400,
            body_sample='{"error":"...com.fasterxml.jackson.databind.exc.InvalidTypeIdException: denied resolution"}',
        )
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertTrue(any("Error/exception disclosure" in i for i in indicators))
        self.assertTrue(strong, "4xx co lo exception/stacktrace thi van la strong")

    def test_timestamp_only_diff_is_not_flagged(self):
        # False-positive that tren /favicon.ico: 2 response 404 giong het nhau
        # tru truong "timestamp" cua trang loi Spring -> KHONG duoc coi la
        # content diff co y nghia.
        baseline = sample(status=404, length=100,
                          body_sample='{"timestamp":"2026-10-15T08:05:58.094+00:00","status":404,"error":"Not Found","path":"/favicon.ico"}')
        mutated = sample(status=404, length=100,
                         body_sample='{"timestamp":"2026-10-15T08:05:58.100+00:00","status":404,"error":"Not Found","path":"/favicon.ico"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertEqual(indicators, [], "Khac biet duy nhat la timestamp -> khong co indicator nao")
        self.assertFalse(strong)

    def test_strong_and_weak_indicators_can_coexist(self):
        # Neu CA error disclosure VA content-diff deu xay ra (hiem, nhung co
        # the), strong_signal phai la True vi co it nhat 1 bang chung manh -
        # khong bi weak indicator "pha" ket qua.
        baseline = sample(status=200, body_sample='{"role":"user"}')
        mutated = sample(status=500, body_sample='{"error":"exception: bad object"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertGreaterEqual(len(indicators), 1)
        self.assertTrue(strong)


if __name__ == "__main__":
    unittest.main(verbosity=2)
