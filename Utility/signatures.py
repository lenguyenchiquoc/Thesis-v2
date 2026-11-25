import base64
import json
import re
import urllib.parse

PHP_STRONG = [
    r'O:\d+:"[^"]+":\d+:\{',
    r'C:\d+:"[^"]+":\d+:\{',
]
PHP_MEDIUM = [
    r'a:\d+:\{(?:s:|i:|O:|b:|d:)',
]
PHP_WEAK = [
    r's:\d+:"',
    r'i:\d+;',
    r'd:\d+\.\d+;',
    r'b:[01];',
]
PHP_GADGET_CHAINS = [
    "monolog", "guzzle", "swiftmailer",
    "phpggc", "laravel", "symfony",
    "__wakeup", "__destruct", "__toString",
    "__call", "__get", "__set",
]

JAVA_MAGIC_B64 = [
    'rO0AB',
    'rO0A',
]
JAVA_MAGIC_BYTES = [
    b'\xac\xed\x00\x05',
    b'\xac\xed\x00\x04',
]
JAVA_GADGET_CHAINS = [
    "templatesimpl", "commonscollections", "urldns",
    "invoketransformer", "annotationinvocationhandler",
    "ysoserial", "jdk7u21", "spring", "hibernatevalidator",
    "rome", "beanshell", "clojure", "groovy",
]

PICKLE_MAGIC_BYTES = [
    b'\x80\x02',
    b'\x80\x03',
    b'\x80\x04',
    b'\x80\x05',
]
PICKLE_TEXT_INDICATORS = [
    'c__builtin__', 'cposix', 'csubprocess',
    'cos\nsystem', 'cbuiltins\nexec',
    '__reduce__', '__reduce_ex__',
    'ctypes\nFunctionType',
]
PICKLE_GADGET = [
    'os.system', 'subprocess.check_output',
    'eval', 'exec', '__import__',
]
JSONPICKLE_PATTERNS = [
    r'"py/object"\s*:',
    r'"py/reduce"\s*:',
    r'"py/type"\s*:',
    r'"py/function"\s*:',
    r'"py/newargs(?:ex)?"\s*:',
]

YAML_STRONG = [
    r'!!python/object/apply',
    r'!!python/object:',
    r'!!python/module:',
    r'!!javax\.script',
    r'!!com\.sun',
    r'!!java\.lang',
    r'!<tag:yaml\.org,2002:python',
]
YAML_MEDIUM = [
    r'%YAML\s+\d+\.\d+',
    r'!<tag:yaml\.org',
]
YAML_WEAK = [
    r'!!',
    r'!<',
]

DOTNET_PATTERNS = [
    r'<SOAP-ENV:Envelope',
    r'<System\.Runtime\.Serialization',
    r'__type.*System\.',
    r'"\$type"\s*:\s*"',
    r'AAEAAAD/////',
    r'"@class"\s*:\s*"[^"]*"',
    r'TypeObject.*mscorlib',
    r'BinaryFormatter',
    r'ObjectStateFormatter',
    r'LosFormatter',
    r'NetDataContractSerializer',
]
DOTNET_VIEWSTATE = [
    r'^/wEy',
    r'^/wEx',
    r'^/wEP',
]

NODEJS_PATTERNS = [
    r'_proto_\s*:',
    r'"__proto__"\s*:',
    r'"constructor"\s*:\s*\{',
    r'node-serialize',
    r'"rce"\s*:\s*"_\$\$ND_FUNC\$\$_',
    r'_\$\$ND_FUNC\$\$_function',
]

JACKSON_PATTERNS = [
    r'\[\s*"(?:[a-z][\w$]*\.)+[A-Z][\w$]*"\s*,',
    r'"@class"\s*:\s*"(?:[a-z][\w$]*\.)+[A-Z][\w$]*"',
    r'"@type"\s*:\s*"(?:[a-z][\w$]*\.)+[A-Z][\w$]*"',
    r'\[\s*"(?:[a-z][\w$]*\.)+[A-Z][\w$]*<[^"]*>"\s*,',
    r'"@class"\s*:\s*"(?:[a-z][\w$]*\.)+[A-Z][\w$]*<[^"]*>"',
    r'"@type"\s*:\s*"(?:[a-z][\w$]*\.)+[A-Z][\w$]*<[^"]*>"',
]
JACKSON_DANGEROUS_CLASSES = [
    "jdbcrowsetimpl",
    "templatesimpl",
    "propertypathfactorybean",
    "simplejndibeanfactory",
    "wrapperconnectionpooldatasource",
    "jndirefforwardingdatasource",
    "c3p0",
    "defaultbeanfactorypointcutadvisor",
]

# Fastjson 1.x AutoType — a PLAIN JSON object whose first key is "@type" naming a Java class:
# {"@type":"com.sun.rowset.JdbcRowSetImpl",...}. Distinct from Jackson default typing, which uses
# WRAPPER_ARRAY ["com.X",{...}] or the "@class" marker. The leading "{" anchor keeps this from
# matching Jackson's array form; _detect_java checks Fastjson BEFORE the Jackson structural
# patterns so a @type object is labelled Fastjson AutoType, not Jackson.
FASTJSON_PATTERNS = [
    r'\{\s*"@type"\s*:\s*"(?:[a-z][\w$]*\.)+[A-Za-z_$][\w$.]*"',
]

RUBY_PATTERNS = [
    r'\\x04\\x08',
    r'BAhv',
    r'BAh[0-9A-Za-z+/]',
    r'\\u0004\\b',
]
RUBY_MAGIC_BYTES = [
    b'\x04\x08',
]
DOTNET_MAGIC_BYTES = [
    # MS-NRBF SerializationHeaderRecord: RecordType 0x00 + RootId=1 + HeaderId=-1.
    # Every default BinaryFormatter.Serialize stream (and all ysoserial.net/ysonet
    # output) begins with these 9 bytes; base64("\x00\x01\x00\x00\x00\xff\xff\xff\xff")
    # == "AAEAAAD/////", the string form already in DOTNET_PATTERNS.
    b'\x00\x01\x00\x00\x00\xff\xff\xff\xff',
]
OJ_PATTERNS = [
    r'"\^o"\s*:',
    r'"\^c"\s*:',
    r'"\^u"\s*:',
]
RUBY_YAML_PATTERNS = [
    r'!ruby/object:',
    r'!ruby/hash',
    r'!ruby/struct',
    r'!ruby/array',
    r'!ruby/string',
    r'!ruby/marshalable',
]

WRAPPER_DANGEROUS = [
    "phar://", "expect://", "gopher://",
    "glob://", "zlib://", "bzip2://",
]
WRAPPER_MODERATE = [
    "file://", "data://", "php://",
    "compress.zlib://", "compress.bzip2://",
]

GADGET_KEYWORDS = [
    'TemplatesImpl', 'InvokerTransformer', 'CommonsCollections',
    'ysoserial', 'Monolog', 'Guzzle', 'SwiftMailer',
    'os.system', 'subprocess', '__wakeup', '__destruct',
    'AnnotationInvocationHandler', 'URLDNS', 'phpggc',
    'marshalsec', 'jndi:', 'ldap://', 'rmi://',
    'commons.collections',
    'commons-collections',
    'org.apache.commons',
    'com.sun.org.apache',
    'org.apache.xalan',
    'com.sun.org.apache.xalan',
    'transletbytecodes',
    'sun.reflect.annotation',
    'java.lang.reflect.proxy',
    'com.sun.jndi',
    'javax.naming',
    'org.springframework',
    'springframework.core',
    'groovy.lang',
    'org.codehaus.groovy',
    'bsh.interpreter',
    'com.sun.syndication',
    'java.lang.runtime',
    'java.lang.reflect',
    'java.net.urlclassloader',
    'java.rmi.server',
    'gadgets',
]


def is_nodejs_prototype_pollution(text: str) -> bool:
    return '__proto__' in text or ('constructor' in text and 'prototype' in text)


TYPED_JSON_DECODED_PATTERNS = (
    [r'"\$type"\s*:\s*"', r'_\$\$ND_FUNC\$\$_function']
    + JACKSON_PATTERNS + FASTJSON_PATTERNS + JSONPICKLE_PATTERNS + OJ_PATTERNS
)


def _decoded_bytes_look_serialized(raw: bytes, _depth: int = 0) -> bool:
    if len(raw) < 4:
        return False
    if raw[:2] in (b'\x1f\x8b', b'\x78\x9c', b'\x78\x01', b'\x78\xda'):
        return True
    if any(raw.startswith(m) for m in
           JAVA_MAGIC_BYTES + PICKLE_MAGIC_BYTES + RUBY_MAGIC_BYTES + DOTNET_MAGIC_BYTES):
        return True
    txt = raw.decode('latin-1', 'ignore')
    low = txt.lower()
    if re.search(r'O:\d+:"', txt) or re.search(r'a:\d+:\{', txt):
        return True
    if any(y in txt for y in ["!!python/", "!!java", "!!map", "!<tag:yaml.org", "%YAML"]):
        return True
    if any(p in txt for p in PICKLE_TEXT_INDICATORS):
        return True
    if any(re.search(p, txt) for p in TYPED_JSON_DECODED_PATTERNS):
        return True
    if any(k in low for k in ["java.lang", "java.util", "commonscollections",
                              "templatesimpl", "__reduce__", "__wakeup", "__destruct",
                              "gadget", "objectdataprovider", "system.windows",
                              "system.data"]):
        return True
    if _depth < 5:
        stripped = txt.strip()
        clean = stripped.replace('-', '+').replace('_', '/').rstrip('=')
        if len(clean) >= 16 and re.fullmatch(r'[A-Za-z0-9+/]+', clean):
            try:
                inner = base64.b64decode(clean + '=' * (-len(clean) % 4), validate=True)
                if _decoded_bytes_look_serialized(inner, _depth + 1):
                    return True
            except Exception:
                pass
        if len(stripped) >= 16 and len(stripped) % 2 == 0 and re.fullmatch(r'[0-9a-fA-F]+', stripped):
            try:
                if _decoded_bytes_look_serialized(bytes.fromhex(stripped), _depth + 1):
                    return True
            except ValueError:
                pass
    return False


def looks_like_serialized(value: str) -> bool:
    if len(value) < 10:
        return False

    value_lower = value.lower()

    try:
        decoded_value = urllib.parse.unquote(value)
        decoded_lower = decoded_value.lower()
    except Exception:
        decoded_value = value
        decoded_lower = value_lower

    bin_data = value.encode('latin-1', errors='ignore')
    if any(bin_data.startswith(magic) for magic in
           JAVA_MAGIC_BYTES + PICKLE_MAGIC_BYTES + RUBY_MAGIC_BYTES + DOTNET_MAGIC_BYTES):
        return True

    if any(re.search(p, value) or re.search(p, decoded_value) for p in PHP_STRONG + PHP_WEAK):
        return True
    if re.search(r'(?i)Tzo[0-9]+[A-Za-z0-9+/=]*', value) or re.search(r'(?i)Tzo[0-9]+[A-Za-z0-9+/=]*', decoded_value):
        return True

    if value.startswith("rO0") or "rO0AB" in value or value.startswith("ACED") or "ACED" in value.upper():
        return True
    if "ysoserial" in decoded_lower or "commonscollections" in decoded_lower or "urlclassloader" in decoded_lower or "templatesimpl" in decoded_lower:
        return True
    if "application/x-java-serialized-object" in value_lower:
        return True
    if any(y in value for y in ["!!", "!<!", "%YAML", "!<tag:yaml.org"]):
        return True

    if any(p in decoded_value for p in PICKLE_TEXT_INDICATORS):
        return True

    if any(re.search(p, value) or re.search(p, decoded_value) for p in JSONPICKLE_PATTERNS):
        return True

    if any(re.search(p, value) or re.search(p, decoded_value) for p in DOTNET_VIEWSTATE):
        return True
    if any(re.search(p, value, re.IGNORECASE) or re.search(p, decoded_value, re.IGNORECASE) for p in DOTNET_PATTERNS):
        return True

    if any(re.search(p, value) or re.search(p, decoded_value) for p in RUBY_PATTERNS):
        return True
    if any(re.search(p, value) or re.search(p, decoded_value) for p in OJ_PATTERNS):
        return True
    if any(re.search(p, value) or re.search(p, decoded_value) for p in RUBY_YAML_PATTERNS):
        return True

    if is_nodejs_prototype_pollution(decoded_lower):
        return True
    if any(re.search(p, value, re.IGNORECASE) or re.search(p, decoded_value, re.IGNORECASE) for p in NODEJS_PATTERNS):
        return True

    if any(re.search(p, value) or re.search(p, decoded_value) for p in JACKSON_PATTERNS):
        return True

    if value.startswith(("{", "[")) and len(value) > 100:
        if any(k in decoded_lower for k in ["__class__", "__wakeup", "__destruct", "java.lang", "java.util", "gadget", "phar"]):
            return True

    value_clean = decoded_value.replace('-', '+').replace('_', '/').rstrip('=')
    if len(value_clean) >= 20 and re.match(r'^[A-Za-z0-9+/]{20,}$', value_clean):
        padded = value_clean + '=' * (-len(value_clean) % 4)
        try:
            raw = base64.b64decode(padded, validate=True)
        except Exception:
            raw = None
        if raw is not None and _decoded_bytes_look_serialized(raw):
            return True

    if re.match(r'^[0-9a-fA-F]{30,}$', value) and len(value) % 2 == 0:
        try:
            if _decoded_bytes_look_serialized(bytes.fromhex(value)):
                return True
        except ValueError:
            pass

    if any(kw in decoded_lower for kw in ["phar://", "gopher://", "expect://", "php://", "file://", "data://", "serialize", "unserialize", "pickle", "marshal", "jndi:", "ldap://", "rmi://"]):
        return True

    # A serialized value nested as a STRING inside a JSON body is quote-escaped there
    # (`{"backup":"O:11:\"Preferences\"…"}`), so every `"`-anchored pattern above misses it.
    # Re-check each JSON string leaf on its unescaped form (bug N, 2026-11-25) — the same
    # json.loads unescape normalize.py already applies (JWT-claim fix). Each leaf is judged by
    # this very gate, so it can only pass if it would pass when sent on its own.
    if any(looks_like_serialized(s) for s in _json_string_leaves(value)):
        return True

    return False


def _json_string_leaves(value: str, limit: int = 200) -> list:
    """String leaves (values and keys) of a JSON object/array body; [] when not JSON."""
    if not value.lstrip().startswith(("{", "[")):
        return []
    try:
        root = json.loads(value)
    except ValueError:
        return []
    out, stack = [], [root]
    while stack and len(out) < limit:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                out.append(k)
                stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str) and node != value:
            out.append(node)
    return [s for s in out if isinstance(s, str) and len(s) >= 10]
