"""
Provenance / faithful-replay tests (Utility/transforms.py).

Root cause being locked down: the pipeline narrows a captured HTTP slot
(cookie / header / query / form param / raw body) to a candidate through
several steps, but used to remember only some of them, and only by name.
Replay then had to rebuild the request, and whenever a step was unknown it
silently sent the fragment in place of the whole slot. Same family of bugs:
  - Cookie header "a=1; ref_tag=X; b=2" overwritten by X alone,
  - form_body rebuilt as only "name=value" (other params dropped),
  - Jackson wrapper nested at ["channel"] of a JSON body: the gadget replaced
    the WHOLE body -> MismatchedInputException, PTV never reached,
  - base64url cookie re-wrapped with the standard alphabet + padding.

Invariant: undoing every step on an UNMODIFIED candidate must give back the
captured slot byte-for-byte (or an equivalent spelling for encodings that
have several), and any step that discarded information must make replay
refuse loudly instead of rebuilding a different request.
"""

import base64
import gzip
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Analyze.cleanfilter import cleanfilter
from Analyze.normalize import DataNormalizer
from Analyze.postfiltered import VectorFiltering
from Replay.replay_request import ReplayRequest
from Utility import transforms
from Utility.transforms import TransformError, apply_chain, rebuild

HERE = os.path.dirname(os.path.abspath(__file__))


def chain_to(slot: str, candidate_pick=0, location="raw_body", name="payload"):
    cleaned = cleanfilter([{"source": "t", "url": "http://x/", "method": "POST",
                            "location": location, "name": name, "value": slot}])._clean_all()[0]
    norm = DataNormalizer(cleaned["cleaned_value"])
    candidate = norm.normalize()[candidate_pick]
    return candidate, list(cleaned["clean_steps"]) + norm.get_transform_chain(candidate)


class TestEachStepRoundTripsExactly(unittest.TestCase):

    def assert_identity(self, slot):
        candidate, chain = chain_to(slot)
        self.assertEqual(apply_chain(slot, chain), candidate)
        self.assertEqual(rebuild(slot, chain, candidate), slot)
        return candidate, chain

    def test_base64url_without_padding_keeps_its_alphabet(self):
        slot = base64.urlsafe_b64encode(b'O:4:"User":1:{s:5:"admin";b:0;}???').decode().rstrip("=")
        self.assertIn("_", slot)
        _, chain = self.assert_identity(slot)
        self.assertEqual(chain[-1]["op"], "base64")
        self.assertTrue(chain[-1]["urlsafe"])
        self.assertFalse(chain[-1]["pad"])

    def test_standard_padded_base64(self):
        self.assert_identity(base64.b64encode(b'O:4:"User":1:{s:5:"admin";b:0;}').decode())

    def test_url_keeps_characters_the_original_left_raw(self):
        self.assert_identity('O%3A4%3A%22User%22%3A1%3A%7Bs%3A5%3A%22admin%22%3Bb%3A0%3B%7D+x')

    def test_lowercase_percent_hex_is_preserved(self):
        self.assert_identity('O%3a4%3a%22User%22%3a1%3a%7bs%3a5%3a%22admin%22%3bb%3a0%3b%7d')

    def test_hex_case_is_preserved(self):
        self.assert_identity('O:4:"User":1:{s:5:"admin";b:0;}'.encode().hex().upper())

    def test_jwt_signature_and_other_segments_untouched(self):
        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
        body = base64.urlsafe_b64encode(b'{"user":"O:4:\\"User\\":1:{s:5:\\"admin\\";b:0;}"}').decode().rstrip("=")
        self.assert_identity(f"{header}.{body}.SIGNATURE_PART_xyz")

    def test_gzip_base64_is_semantically_equivalent(self):
        slot = base64.b64encode(gzip.compress(b'O:4:"User":1:{s:5:"admin";b:0;}')).decode()
        candidate, chain = chain_to(slot)
        back = rebuild(slot, chain, candidate)
        self.assertEqual(apply_chain(back, chain), candidate)


class TestMutationLandsExactlyWhereTheCandidateCameFrom(unittest.TestCase):

    def test_jackson_wrapper_nested_in_json_body_keeps_siblings(self):
        body = ('{"label":"email alerts","channel":["com.webvulenv.javaapp.model.webhook.EmailChannel",'
                '{"address":"ops@acme-portal.test"}]}')
        candidate, chain = chain_to(body)
        self.assertEqual(json.loads(candidate)[0], "com.webvulenv.javaapp.model.webhook.EmailChannel")
        self.assertEqual(chain[-1]["path"], ["channel"])

        gadget = '["java.util.ArrayList<java.util.Date>",[12345]]'
        rebuilt = json.loads(rebuild(body, chain, gadget))
        self.assertEqual(rebuilt["label"], "email alerts")
        self.assertEqual(rebuilt["channel"], json.loads(gadget))

    def test_cookie_header_fallback_replaces_only_its_segment(self):
        inner = 'O:4:"User":1:{s:5:"admin";b:0;}'
        quoted = inner.replace(":", "%3A").replace('"', "%22").replace("{", "%7B").replace("}", "%7D").replace(";", "%3B")
        slot = f"lang=en; ref_tag={quoted}; theme=dark"
        candidate, chain = chain_to(slot, location="header", name="Cookie")
        self.assertEqual(candidate, inner)
        rebuilt = rebuild(slot, chain, inner.replace("b:0", "b:1"))
        self.assertTrue(rebuilt.startswith("lang=en; ref_tag="))
        self.assertTrue(rebuilt.endswith("; theme=dark"))
        self.assertIn("b%3A1", rebuilt)

    def test_base64url_mutation_stays_base64url(self):
        slot = base64.urlsafe_b64encode(b'O:4:"User":1:{s:5:"admin";b:0;}???').decode().rstrip("=")
        candidate, chain = chain_to(slot)
        rebuilt = rebuild(slot, chain, candidate.replace("b:0", "b:1") + "???")
        self.assertNotIn("+", rebuilt)
        self.assertNotIn("/", rebuilt)
        self.assertNotIn("=", rebuilt)


def _clean(value, location, name="payload"):
    return cleanfilter([{"source": "t", "url": "http://x/", "method": "POST",
                         "location": location, "name": name, "value": value}])._clean_all()


class TestCookieSplitOnlyAppliesToCookies(unittest.TestCase):
    """Bug D (2026-11-21): the '; ' Cookie-pair split ran on raw_body too. A node-serialize body
    `..."_$$ND_FUNC$$_function () { return 1; }"}` was cut at '; ', so replay kept the old tail
    after the payload (`{"rce":...}; }"}`) -> JSON parse error 500, blind sink lost its OOB."""

    NODE_BODY = '{"theme":"dark","lang":"en","render":"_$$ND_FUNC$$_function () { return 1; }"}'

    def test_raw_body_with_semicolon_space_is_kept_whole(self):
        out = _clean(self.NODE_BODY, "raw_body")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["cleaned_value"], self.NODE_BODY)
        self.assertEqual(out[0]["clean_steps"], [])

    def test_raw_body_trailing_quote_semicolon_not_trimmed(self):
        body = 's:5:"hello";'
        out = _clean(body, "raw_body")
        self.assertEqual(out[0]["cleaned_value"], body)
        self.assertEqual(out[0]["clean_steps"], [])

    def test_raw_body_payload_replaces_whole_body(self):
        out = _clean(self.NODE_BODY, "raw_body")[0]
        self.assertEqual(rebuild(self.NODE_BODY, out["clean_steps"], '{"rce":1}'), '{"rce":1}')

    def test_cookie_header_still_split_to_serialized_segment(self):
        header = 'a=1; session=O:4:"User":1:{s:5:"admin";b:0;}; theme=dark'
        out = _clean(header, "header", "Cookie")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["cleaned_value"], 'O:4:"User":1:{s:5:"admin";b:0;}')
        self.assertTrue(out[0]["clean_steps"])

    def test_cookie_value_quotes_still_trimmed(self):
        out = _clean('"O:4:"User":1:{s:5:"admin";b:0;}"', "cookie", "session")
        self.assertEqual(out[0]["cleaned_value"], 'O:4:"User":1:{s:5:"admin";b:0;}')


class TestLossyStepsAreRefusedNotGuessed(unittest.TestCase):

    def test_base64_over_text_that_is_not_base64_is_flagged_and_refused(self):
        slot = 'filename="Tzo0OiJVc2VyIjoyOntzOjg6InVzZXJuYW1lIjtzOjY6IndpZW5lciI7fQ=="'
        step = transforms.base64_step(slot)
        child = transforms.forward(step, slot)
        transforms.mark_if_lossy(step, slot, child)
        self.assertTrue(step.get("lossy"))
        with self.assertRaises(TransformError):
            rebuild(slot, [step], child)

    def test_unknown_op_is_refused(self):
        with self.assertRaises(TransformError):
            rebuild("abc", [{"op": "rot13"}], "x")

    def test_replay_skips_instead_of_overwriting_the_slot(self):
        mutation = {
            "url": "http://127.0.0.1:9/x", "method": "POST", "location": "raw_body", "name": "payload",
            "type": "t", "encoding": "base64", "payload": base64.b64encode(b"zzz").decode(),
            "slot_value": "abc", "transform_chain": [{"op": "base64", "lossy": True}],
        }
        result = ReplayRequest().replay(mutation)
        self.assertTrue(result.get("skipped"))
        self.assertIn("Cannot faithfully rebuild", result["reason"])


class TestSendSubstitutesIntoTheOriginalRequest(unittest.TestCase):

    def test_form_body_keeps_other_params_byte_identical(self):
        out = ReplayRequest._replace_pair("csrf=a%2Bb&data=OLD&next=%2Fhome", "data", "NEW")
        self.assertEqual(out, "csrf=a%2Bb&data=NEW&next=%2Fhome")

    def test_missing_param_is_appended(self):
        self.assertEqual(ReplayRequest._replace_pair("a=1", "b", "2"), "a=1&b=2")


class TestRoundTripInvariantOnCommittedHar(unittest.TestCase):
    """Every candidate of every vector in TestCase/comprehensive.har must either
    round-trip (exactly or equivalently) or be explicitly flagged lossy."""

    def test_no_candidate_is_silently_rebuilt_differently(self):
        from Scanner.har_loader import HarLoader
        har = os.path.join(HERE, "comprehensive.har")
        vectors = cleanfilter(VectorFiltering({"vectors": HarLoader(har).parse()}).filter())._clean_all()
        checked = 0
        for v in vectors:
            norm = DataNormalizer(v["cleaned_value"])
            for candidate in norm.normalize():
                chain = list(v.get("clean_steps") or []) + norm.get_transform_chain(candidate)
                slot = v["original_value"]
                self.assertEqual(apply_chain(slot, chain), candidate)
                checked += 1
                if any(s.get("lossy") for s in chain):
                    with self.assertRaises(TransformError):
                        rebuild(slot, chain, candidate)
                    continue
                back = rebuild(slot, chain, candidate)
                if back != slot:
                    self.assertEqual(apply_chain(back, chain), candidate,
                                     f"{v['location']}/{v['name']} rebuilt differently")
        self.assertGreater(checked, 50)


if __name__ == "__main__":
    unittest.main()
