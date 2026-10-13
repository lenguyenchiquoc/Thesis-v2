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
        # unserialize - status/length giu nguyen, chi noi dung thay doi nhe.
        baseline = sample(body_sample='{"referral_tag":"organic","username":"wiener"}')
        mutated = sample(body_sample='{"referral_tag":"admin","username":"wiener"}')
        indicators, strong = self.r._compare(baseline, mutated)
        self.assertEqual(len(indicators), 1)
        self.assertIn("content differs in a small", indicators[0])
        self.assertFalse(strong, "Chi co content-diff yeu thi KHONG duoc tinh la likely_vulnerable")

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
