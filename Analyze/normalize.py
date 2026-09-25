import base64
import gzip
import json
import re
import urllib.parse
from collections import deque

from Utility import signatures
from Utility.schemas import NormalizedCandidates


class DataNormalizer:
    def __init__(self, value:str, max_depth = 12, max_candidate = 40):
        self.data = value.strip()
        self.max_depth = max_depth
        self.max_candidate = max_candidate

    def normalize(self) -> NormalizedCandidates:
        seen = set()
        queue = deque([(self.data,0)])
        meaningfull_data = []
        all_layer = []
        children_of: dict[str, list[str]] = {}
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
            children_of[current] = decodes
            for next_value in decodes:
                if next_value and next_value not in seen:
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

    def _extract_claim_strings(self, obj, depth: int = 0) -> list[str]:
        if depth > 5:
            return []
        if isinstance(obj, str):
            return [obj.strip()] if obj.strip() else []
        if isinstance(obj, dict):
            found = []
            for v in obj.values():
                found.extend(self._extract_claim_strings(v, depth + 1))
            return found
        if isinstance(obj, list):
            found = []
            for v in obj:
                found.extend(self._extract_claim_strings(v, depth + 1))
            return found
        return []

    def _generate_decodes(self, value: str) -> list[str]:
        results = []
        is_jwt_shaped = bool(re.match(r'^[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]*$', value))
        try:
            ud = urllib.parse.unquote(value)
            if ud != value and ud.strip():
                results.append(ud.strip())
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
                            txt = decompressed.decode('latin-1').strip()
                            if txt:
                                results.append(txt)
                        except:
                            pass
                    else:
                        try:
                            txt = decoded_bytes.decode('latin-1').strip()
                            if txt and len(txt) >= 10:
                                results.append(txt)
                        except:
                            pass
            except:
                pass
        if re.fullmatch(r'^[0-9a-fA-F]+$', value) and len(value) % 2 == 0 and len(value) >= 16:
            try:
                hex_bytes = bytes.fromhex(value)
                txt = hex_bytes.decode('latin-1').strip()
                if txt:
                    results.append(txt)
            except:
                pass
        if is_jwt_shaped:
            for seg in value.split('.'):
                if not seg:
                    continue
                try:
                    padded = seg + '=' * (-len(seg) % 4)
                    decoded_bytes = base64.urlsafe_b64decode(padded)
                    txt = decoded_bytes.decode('latin-1').strip()
                    if txt:
                        results.append(txt)
                except:
                    pass
        try:
            claims = json.loads(value)
            if isinstance(claims, (dict, list)):
                results.extend(self._extract_claim_strings(claims))
        except:
            pass
        return results

    def _serialized_score(self, value: str) -> float:
        score = 0.0

        if 'java.' in value or 'org.apache' in value:
            score += 10
        if any(kw in value.lower() for kw in
            ['commonscollections', 'templatesimpl', 'gadget',
                'invoketransformer', 'urldns']):
            score += 8

        if re.search(r'O:\d+:"[^"]+":\d+:\{', value):
            score += 6

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

        # Dau ':' / '"' la cu phap BAT BUOC cua JSON (moi cap key:value, moi
        # string deu can 1 cap dau nhay) - khong noi len gi ve exploit. Neu
        # cong diem theo mat do ':'/'"' ngay ca khi value la JSON hop le, 1
        # envelope JSON nhieu key vo hai (vd claim JWT sub/iat/exp/profile)
        # co the "vuot diem" 1 gadget PHP thuc nam long ben trong no - da
        # verify thuc te: envelope 17.3 > gadget rieng 14.9 diem, chi vi
        # JSON co nhieu key/string hon. Chi cong diem nay cho van ban KHONG
        # phai JSON (PHP serialize/Ruby Marshal text... - noi ':'/'"' day dac
        # THUC SU la tin hieu cau truc gadget).
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
