"""
Unit test: replay thresholds read from config.json "replay" (tool_config.get_replay_settings)
and applied by ReplayRequest (2026-11-28). The user edits thresholds (e.g. time-based 4s -> 6s)
in config.json instead of the code; missing/invalid keys must fall back to the built-in
defaults so a config without the section behaves exactly as before.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tool_config
from Replay.replay_request import ReplayRequest

DEFAULTS = {
    "time_delay_threshold_sec": 4.0,
    "content_similarity_threshold": 0.8,
    "length_change_ratio": 0.5,
    "request_timeout_sec": 10.0,
}


def sample(status=200, elapsed_sec=0.01, length=100, body_sample=""):
    return {"status": status, "elapsed_sec": elapsed_sec, "length": length, "body_sample": body_sample}


class _ConfigFile(unittest.TestCase):
    """Points ETHICALQUOC_CONFIG at a temp config.json for the duration of one test."""

    def setUp(self):
        self._old = os.environ.get("ETHICALQUOC_CONFIG")
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.environ["ETHICALQUOC_CONFIG"] = self.path

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ETHICALQUOC_CONFIG", None)
        else:
            os.environ["ETHICALQUOC_CONFIG"] = self._old
        os.remove(self.path)

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def settings(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            s = tool_config.get_replay_settings()
        return s, out.getvalue()


class TestReplaySettings(_ConfigFile):
    def test_no_replay_section_gives_defaults(self):
        self.write({"oob_wait_seconds": 6})
        s, log = self.settings()
        self.assertEqual(s, DEFAULTS)
        self.assertEqual(log, "")

    def test_shipped_config_json_equals_defaults(self):
        """The repo's config.json must not change detection: its replay section == defaults."""
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "config.json"), encoding="utf-8") as f:
            shipped = json.load(f).get("replay", {})
        self.assertEqual({k: float(v) for k, v in shipped.items()}, DEFAULTS)

    def test_custom_values_are_used(self):
        self.write({"replay": {"time_delay_threshold_sec": 6, "request_timeout_sec": 15}})
        s, log = self.settings()
        self.assertEqual(s["time_delay_threshold_sec"], 6.0)
        self.assertEqual(s["request_timeout_sec"], 15.0)
        self.assertEqual(s["content_similarity_threshold"], 0.8)
        self.assertEqual(log, "")

    def test_invalid_values_fall_back_to_default_with_warning(self):
        self.write({"replay": {
            "time_delay_threshold_sec": "6",           # string
            "content_similarity_threshold": 1.5,      # out of (0, 1]
            "length_change_ratio": -1,                # not > 0
            "request_timeout_sec": True,              # bool is not a number here
        }})
        s, log = self.settings()
        self.assertEqual(s, DEFAULTS)
        for key in DEFAULTS:
            self.assertIn(f"replay.{key}", log)

    def test_unknown_key_ignored_with_warning(self):
        self.write({"replay": {"time_dealy_threshold_sec": 6}})   # typo
        s, log = self.settings()
        self.assertEqual(s, DEFAULTS)
        self.assertIn("unknown key", log)

    def test_non_object_section_gives_defaults(self):
        self.write({"replay": 6})
        s, log = self.settings()
        self.assertEqual(s, DEFAULTS)
        self.assertIn("must be an object", log)

    def test_threshold_not_below_timeout_warns(self):
        self.write({"replay": {"time_delay_threshold_sec": 12, "request_timeout_sec": 10}})
        s, log = self.settings()
        self.assertEqual(s["time_delay_threshold_sec"], 12.0)
        self.assertIn("can never fire", log)


class TestReplayRequestUsesConfig(_ConfigFile):
    def make(self, replay, **kw):
        self.write({"replay": replay})
        with contextlib.redirect_stdout(io.StringIO()):
            return ReplayRequest(**kw)

    def test_time_threshold_from_config(self):
        r = self.make({"time_delay_threshold_sec": 6, "request_timeout_sec": 15})
        _, strong = r._compare(sample(elapsed_sec=0.01), sample(elapsed_sec=5.0))
        self.assertFalse(strong, "5s slower must NOT fire when the threshold is 6s")
        indicators, strong = r._compare(sample(elapsed_sec=0.01), sample(elapsed_sec=6.5))
        self.assertTrue(strong)
        self.assertTrue(any("Time-based" in i for i in indicators))

    def test_length_ratio_from_config(self):
        base, mut = sample(length=100), sample(length=140)         # +40%
        _, strong_default = self.make({})._compare(base, mut)
        self.assertFalse(strong_default, "40% is below the default 50% ratio")
        indicators, strong = self.make({"length_change_ratio": 0.3})._compare(base, mut)
        self.assertTrue(strong)
        self.assertTrue(any("length changed significantly" in i for i in indicators))

    def test_similarity_threshold_from_config(self):
        r = self.make({"content_similarity_threshold": 0.95})
        self.assertEqual(r.CONTENT_DIFF_SIMILARITY_THRESHOLD, 0.95)

    def test_timeout_from_config_and_explicit_arg_wins(self):
        self.assertEqual(self.make({"request_timeout_sec": 20}).timeout, 20.0)
        self.assertEqual(self.make({"request_timeout_sec": 20}, timeout=3).timeout, 3)

    def test_instances_do_not_share_settings(self):
        a = self.make({"time_delay_threshold_sec": 9, "request_timeout_sec": 15})
        b = self.make({})
        self.assertEqual(a.TIME_DELAY_THRESHOLD_SEC, 9.0)
        self.assertEqual(b.TIME_DELAY_THRESHOLD_SEC, 4.0)

    def test_defaults_live_only_in_tool_config(self):
        """No second copy of the replay defaults on the class (they would drift)."""
        for attr in ("TIME_DELAY_THRESHOLD_SEC", "CONTENT_DIFF_SIMILARITY_THRESHOLD", "LENGTH_CHANGE_RATIO"):
            self.assertNotIn(attr, vars(ReplayRequest), attr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
