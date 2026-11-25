"""Bug M (2026-11-25): an OOB-confirmed finding must raise severity in every language, not
only Java (whose in-band markers are Java-only). Critical only when the token was carried
exclusively by command/code-execution canaries; mixed / lookup-only -> High; never lowers."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Replay import oob_confirm as oc  # noqa: E402


def _finding(severity, *types):
    return {"severity": severity, "severity_note": None, "evidence": "dynamic-weak",
            "indicators": [], "attempts": [{"payload_type": t, "signal": "weak"} for t in types]}


class TestEscalateOnOob(unittest.TestCase):
    def test_exec_only_canaries_raise_to_critical(self):
        for t in ("php_object_oob", "pickle_oob", "yaml_oob", "jsonpickle_oob",
                  "node_serialize_oob", "yaml_js_function_oob", "dotnet_jsonnet_oob",
                  "dotnet_ysonet_oob"):
            with self.subTest(t=t):
                f = _finding("High", "php_object", t)
                oc._escalate_on_oob(f)
                self.assertEqual(f["severity"], "Critical")
                self.assertIn("suspected RCE", f["severity_note"])
                self.assertTrue(f["severity_note"].startswith("raised from High"))

    def test_lookup_only_is_not_critical(self):
        for t in ("java_urldns", "fastjson_oob", "jackson_oob",
                  "oj_detection_oob", "yaml_detection_oob"):
            with self.subTest(t=t):
                f = _finding("High", t)
                oc._escalate_on_oob(f)
                self.assertEqual(f["severity"], "High")
                self.assertIsNone(f["severity_note"])

    def test_mixed_lookup_and_exec_cannot_attribute_hit(self):
        # Java native session: URLDNS + CC chains share one token -> hit not attributable
        f = _finding("High", "java_urldns", "java_rce_escalation")
        oc._escalate_on_oob(f)
        self.assertEqual(f["severity"], "High")

    def test_lookup_raises_low_or_medium_to_high(self):
        f = _finding("Medium", "oj_detection_oob")
        oc._escalate_on_oob(f)
        self.assertEqual(f["severity"], "High")
        self.assertIn("deserialized attacker-supplied input", f["severity_note"])

    def test_never_lowers_and_keeps_existing_note(self):
        f = _finding("Critical", "php_object_oob")
        f["severity_note"] = "raised from High — response leaked RCE evidence"
        oc._escalate_on_oob(f)
        self.assertEqual(f["severity"], "Critical")
        self.assertEqual(f["severity_note"], "raised from High — response leaked RCE evidence")

    def test_skipped_attempts_ignored(self):
        f = _finding("High", "php_object_oob")
        f["attempts"].append({"payload_type": "java_urldns", "skipped": True})
        oc._escalate_on_oob(f)
        self.assertEqual(f["severity"], "Critical")


class TestOobConfirmEscalates(unittest.TestCase):
    @mock.patch.object(oc, "get_oob_wait_seconds", return_value=0)
    @mock.patch.object(oc, "collector_probe", return_value=(True, None))
    @mock.patch.object(oc, "get_oob_collector_url", return_value="http://127.0.0.1:9000")
    def test_only_hit_findings_are_escalated(self, *_):
        hit = _finding("High", "php_object", "php_object_oob")
        miss = _finding("High", "php_object", "php_object_oob")
        with mock.patch.object(oc, "poll_oob", side_effect=lambda url, tok: 6 if tok == "a" else 0):
            st = oc.oob_confirm([hit, miss], {0: "a", 1: "b"}, "oob.test")
        self.assertEqual(st["confirmed"], 1)
        self.assertEqual(hit["severity"], "Critical")
        self.assertTrue(hit["oob_confirmed"])
        self.assertEqual(miss["severity"], "High")
        self.assertIsNone(miss["severity_note"])


if __name__ == "__main__":
    unittest.main()
