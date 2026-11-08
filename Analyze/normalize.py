import base64
import gzip
import json
import re
import urllib.parse
from collections import deque

from Utility import signatures
from Utility import transforms
from Utility.schemas import NormalizedCandidates


class DataNormalizer:
    MAX_JSON_NODES = 200

    def __init__(self, value:str, max_depth = 12, max_candidate = 40):
        self.data = value.strip()
        lead, trail = transforms.trim_of(value) if value.strip() else (0, 0)
        self._root_steps = [] if (lead, trail) == (0, 0) else [transforms.slice_step(lead, len(value) - trail)]
        self.max_depth = max_depth
        self.max_candidate = max_candidate
        self._parent_of: dict[str, tuple[dict, str]] = {}

    def normalize(self) -> NormalizedCandidates:
        seen = set()
        queue = deque([(self.data,0)])
        meaningfull_data = []
        all_layer = []
        children_of: dict[str, list[str]] = {}
        self._parent_of = {}
        while queue:
            current, depth = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            all_layer.append(current)
            if self._is_serialized_payload(current):
                meaningfull_data.append(current)
            if depth >= self.max_depth and len(seen) >= self.max_candidate:
                continue
            decodes = self._generate_decodes(current)
            children_of[current] = [v for _, v in decodes]
            for op_label, next_value in decodes:
                if not next_value:
                    continue
                if next_value != self.data and next_value not in self._parent_of:
                    self._parent_of[next_value] = (op_label, current)
                if next_value not in seen:
                    queue.append((next_value, depth+1))

        if meaningfull_data:
            meaningful_data_dedup = list(dict.fromkeys(meaningfull_data))
            score = {v: self._serialized_score(v) for v in meaningful_data_dedup}
            meaningful_set = set(meaningful_data_dedup)

            memo: dict[str, frozenset] = {}

            def collapse(value: str, in_progress: set[str]) -> frozenset:
                if value in memo:
                    return memo[value]
                if value in in_progress:
                    return frozenset()
                in_progress.add(value)
                downstream: set[str] = set()
                for child in children_of.get(value, []):
                    if child and child != value:
                        downstream |= collapse(child, in_progress)
                in_progress.discard(value)

                if value in meaningful_set:
                    total = sum(score[d] for d in downstream)
                    result = frozenset(downstream) if (downstream and total >= score[value]) else frozenset({value})
                else:
                    result = frozenset(downstream)

                memo[value] = result
                return result

            deduped = sorted(
                collapse(self.data, set()),
                key = lambda x: (-score[x],abs(len(x)-120),-x.count(':'))
            )
            return deduped

        return [self.data]

    def _is_serialized_payload(self, value: str) -> bool:
        if len(value) < 10:
            return False
        return signatures.looks_like_serialized(value)

    def _extract_json_nodes(self, obj, path: list | None = None, depth: int = 0, out: list | None = None) -> list:
        path = path or []
        out = [] if out is None else out
        if depth > 5 or len(out) >= self.MAX_JSON_NODES:
            return out
        children = obj.items() if isinstance(obj, dict) else enumerate(obj) if isinstance(obj, list) else []
        for key, child in children:
            child_path = path + [key]
            if isinstance(child, str):
                out.append((child_path, child))
            elif isinstance(child, (dict, list)):
                out.append((child_path, child))
                self._extract_json_nodes(child, child_path, depth + 1, out)
        return out

    @staticmethod
    def _trimmed(step: dict, raw: str) -> tuple[dict, str]:
        trim = transforms.trim_of(raw)
        if trim != [0, 0]:
            step["trim"] = trim
        return step, raw.strip()

    def _generate_decodes(self, value: str) -> list[tuple[dict, str]]:
        results: list[tuple[dict, str]] = []
        is_jwt_shaped = bool(re.match(r'^[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]*$', value))
        try:
            ud = urllib.parse.unquote(value, encoding='latin-1')
            if ud != value and ud.strip():
                results.append(self._trimmed(transforms.url_step(value), ud))
        except:
            pass
        if not is_jwt_shaped:
            try:
                val = value.replace('-', '+').replace('_', '/').rstrip('=')
                if len(val) % 4 != 0:
                    val += '=' * (4 - len(val) % 4)
                if len(val) >= 16:
                    decoded_bytes = base64.b64decode(val, validate=False)
                    if decoded_bytes.startswith(b'\x1f\x8b'):
                        try:
                            decompressed = gzip.decompress(decoded_bytes)
                            txt = decompressed.decode('latin-1')
                            if txt.strip():
                                results.append(self._trimmed(transforms.base64_step(value, gz=True), txt))
                        except:
                            pass
                    else:
                        try:
                            txt = decoded_bytes.decode('latin-1')
                            if txt.strip() and len(txt.strip()) >= 10:
                                results.append(self._trimmed(transforms.base64_step(value), txt))
                        except:
                            pass
            except:
                pass
        if re.fullmatch(r'^[0-9a-fA-F]+$', value) and len(value) % 2 == 0 and len(value) >= 16:
            try:
                txt = bytes.fromhex(value).decode('latin-1')
                if txt.strip():
                    results.append(self._trimmed(transforms.hex_step(value), txt))
            except:
                pass
        if is_jwt_shaped:
            for index, seg in enumerate(value.split('.')):
                if not seg:
                    continue
                try:
                    padded = seg + '=' * (-len(seg) % 4)
                    txt = base64.urlsafe_b64decode(padded).decode('latin-1')
                    if txt.strip():
                        results.append(self._trimmed(transforms.jwt_step(index), txt))
                except:
                    pass
        try:
            claims = json.loads(value)
            if isinstance(claims, (dict, list)):
                base_step = transforms.json_step(value, [])
                for path, node in self._extract_json_nodes(claims):
                    step = {**base_step, "path": path}
                    if isinstance(node, str):
                        if node.strip():
                            results.append(self._trimmed(step, node))
                    else:
                        results.append((step, json.dumps(node, separators=(",", ":"), ensure_ascii=False)))
        except:
            pass
        return [(transforms.mark_if_lossy(step, value, child), child) for step, child in results]

    def get_transform_chain(self, candidate: str) -> list[dict]:
        """Reversible steps from the normalizer's input value down to `candidate`
        (see Utility/transforms.py). Empty when candidate is the input itself."""
        chain: list[dict] = []
        current = candidate
        visited: set[str] = set()
        while current in self._parent_of and current not in visited:
            visited.add(current)
            step, parent = self._parent_of[current]
            chain.append(step)
            current = parent
        chain.reverse()
        return list(self._root_steps) + chain

    def get_encoding_chain(self, candidate: str) -> list[str]:
        return [step["op"] for step in self.get_transform_chain(candidate) if step["op"] != "slice"]

    def _serialized_score(self, value: str) -> float:
        score = 0.0

        raw = value.encode('latin-1', errors='ignore')
        if any(raw.startswith(m) for m in
               signatures.JAVA_MAGIC_BYTES + signatures.PICKLE_MAGIC_BYTES
               + signatures.RUBY_MAGIC_BYTES + signatures.DOTNET_MAGIC_BYTES):
            score += 12

        if 'java.' in value or 'org.apache' in value:
            score += 10
        if any(kw in value.lower() for kw in
            ['commonscollections', 'templatesimpl', 'gadget',
                'invoketransformer', 'urldns']):
            score += 8

        if re.search(r'O:\d+:"[^"]+":\d+:\{', value):
            score += 6

        if any(re.search(p, value) for p in signatures.JACKSON_PATTERNS):
            score += 8

        if any(re.search(p, value) for p in signatures.DOTNET_VIEWSTATE):
            score += 6
        if any(magic in value.encode('latin-1', errors='ignore') for magic in signatures.RUBY_MAGIC_BYTES):
            score += 6
        if any(re.search(p, value, re.IGNORECASE) for p in signatures.DOTNET_PATTERNS):
            score += 4
        if any(re.search(p, value, re.IGNORECASE) for p in signatures.RUBY_PATTERNS):
            score += 4
        if any(re.search(p, value, re.IGNORECASE) for p in signatures.NODEJS_PATTERNS):
            score += 4
        if any(w in value.lower() for w in signatures.WRAPPER_DANGEROUS):
            score += 4

        indicators = ['O:', 'rO0', 'ACED', '__class__', '!!', 'pickle']
        score += sum(value.count(ind) for ind in indicators)

        if not self._is_generic_json(value):
            score += value.count(':') * 0.5
            score += value.count('"') * 0.3

        if re.fullmatch(r'[A-Za-z0-9+/=\-_]{20,}', value.strip()):
            score -= 3

        return score

    def _is_generic_json(self, value: str) -> bool:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return False
        return isinstance(parsed, (dict, list))
