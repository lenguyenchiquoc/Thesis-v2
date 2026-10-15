import re

from Utility import signatures
from Utility.schemas import CleanedVector, ScanVector
from Utility.transforms import slice_step

class cleanfilter:

    PREFIX_PATTERNS = [
        r'^(session|PHPSESSID|JSESSIONID|sid|__Host-session|user|auth|token|data|payload)\s*=\s*',
        r'^Bearer\s+',
        r'^[\w-]{1,32}\s*=\s*',
        r'^Cookie:\s*',
        r'^Set-Cookie:\s*',
    ]

    COOKIE_HEADER_NAMES = {"cookie", "set-cookie"}
    AUTH_HEADER_NAMES = {"authorization"}

    def __init__(self, filter_output: list[ScanVector]):
        self.data = filter_output
    # Trailing '=' is NOT stripped: it is base64 padding far more often than junk,
    # and dropping it made the replayed value differ from what was captured.
    LEAD_JUNK = '= \t\n\r;,"'
    TRAIL_JUNK = ' \t\n\r;,"'

    @staticmethod
    def _strip_span(value: str, start: int, end: int, lead_chars: str | None = None,
                    trail_chars: str | None = None) -> tuple[int, int]:
        while start < end and (value[start].isspace() if lead_chars is None else value[start] in lead_chars):
            start += 1
        while end > start and (value[end - 1].isspace() if trail_chars is None else value[end - 1] in trail_chars):
            end -= 1
        return start, end

    def _clean_spans(self, value: str, location: str | None, name: str | None) -> list[tuple[int, int]]:
        # Every operation here only narrows the value, so each result is an exact
        # [start:end] span of the original - recorded as a reversible slice step.
        start, end = self._strip_span(value, 0, len(value))
        cleaned = value[start:end]

        spans = [(start, end)]
        if '; ' in cleaned:
            segment_spans = []
            pos = start
            for seg in cleaned.split('; '):
                segment_spans.append(self._strip_span(value, pos, pos + len(seg)))
                pos += len(seg) + 2
            suspicious = [s for s in segment_spans if signatures.looks_like_serialized(value[s[0]:s[1]])]
            spans = suspicious if suspicious else [segment_spans[0]]

        is_prefixed_header = (
            isinstance(location, str) and location.lower() == "header"
            and isinstance(name, str) and name.lower() in (self.COOKIE_HEADER_NAMES | self.AUTH_HEADER_NAMES)
        )

        results = []
        for a, b in spans:
            if is_prefixed_header:
                changed = True
                while changed:
                    changed = False
                    for pattern in self.PREFIX_PATTERNS:
                        m = re.match(pattern, value[a:b], flags=re.IGNORECASE)
                        if m and m.end() > 0:
                            a, b = self._strip_span(value, a + m.end(), b)
                            changed = True
            results.append(self._strip_span(value, a, b, self.LEAD_JUNK, self.TRAIL_JUNK))
        return results

    def _clean(self, value: str, location: str | None = None, name: str | None = None) -> list[str]:
        return [cleaned for cleaned, _ in self._clean_with_steps(value, location, name)]

    def _clean_with_steps(self, value, location: str | None = None,
                          name: str | None = None) -> list[tuple[str, list]]:
        if not isinstance(value, str) or not value.strip():
            return [(value, [])]
        results = []
        for a, b in self._clean_spans(value, location, name):
            steps = [] if (a, b) == (0, len(value)) else [slice_step(a, b)]
            results.append((value[a:b], steps))
        return results

    def _clean_all(self) -> list[CleanedVector]:
        cleaned_vector: list[CleanedVector] = []
        for vector in self.data:
            original_value = vector.get('value','')
            for clean_value, steps in self._clean_with_steps(original_value, vector.get('location'), vector.get('name')):
                new_vector: CleanedVector = {
                    **vector,
                    "original_value": original_value,
                    "cleaned_value": clean_value,
                    "clean_steps": steps,
                }
                cleaned_vector.append(new_vector)

        return cleaned_vector
    
    def clean_and_output(self):
        cleaned = self._clean_all()
        print(f"Found {len(cleaned)} cleaned vectors:")
        for i, vec in enumerate(cleaned, 1):
            orig = vec.get('original_value', '')
            cln = vec.get('cleaned_value', '')
            print(f"\n[{i}] Location: {vec.get('location')} | Name: {vec.get('name')}")
            print(f"   Original: {orig}")
            print(f"   Cleaned : {cln}")