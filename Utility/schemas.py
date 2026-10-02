from typing import TypedDict


class ScanVector(TypedDict):
    source: str
    url: str
    method: str
    location: str
    name: str
    value: str


class CleanedVectorRequired(TypedDict):
    original_value: str
    cleaned_value: str


class CleanedVector(ScanVector, CleanedVectorRequired):
    pass


NormalizedCandidates = list[str]


class FingerprintResult(TypedDict):
    value: str
    type: str
    confidence: str
    risk_level: str
    subtype: str | None
    gadget_detected: bool
    gadget_hints: list[str]
    all_candidates: dict[str, int]


class ExploitResult(TypedDict):
    exploitable: bool
    exploit_type: str | None
    score: int
    severity: str
    confidence_source: str
    confirmation_status: str
    display_severity: str
    suggested_probe: str
    notes: str


class ConfirmedExploitResultExtra(TypedDict, total=False):
    replay_note: str
    confirmed_indicators: list[str]
    oracle_probe: dict


class ConfirmedExploitResult(ExploitResult, ConfirmedExploitResultExtra):
    pass


class MutationVector(TypedDict):
    source: str
    url: str
    method: str
    location: str
    name: str
    value: str
    original_value: str
    cleaned_value: str
    encoding_chain: list[str]


class MutationPayloadCore(TypedDict):
    type: str
    chain: str | None
    command: str | None
    payload: str
    payload_urlencoded: str
    location: str
    name: str
    url: str
    method: str
    encoding: str
    encoding_chain: list[str]


class MutationPayloadExtra(TypedDict, total=False):
    payload_raw: str
    note: str


class MutationPayload(MutationPayloadCore, MutationPayloadExtra):
    pass


class MutationErrorRequired(TypedDict):
    error: str
    hint: str


class MutationErrorExtra(TypedDict, total=False):
    command: str


class MutationError(MutationErrorRequired, MutationErrorExtra):
    pass


Mutation = MutationPayload | MutationError
Mutations = list[Mutation]


class OracleUnsupported(TypedDict):
    supported: bool
    reason: str


class OracleNotRun(TypedDict):
    supported: bool
    ran: bool
    reason: str


class OracleRan(TypedDict):
    supported: bool
    ran: bool
    technique: str
    indicators: list[str]
    target_parses_payload: bool


OracleProbeResult = OracleUnsupported | OracleNotRun | OracleRan


class HttpProbeSample(TypedDict):
    status: int
    elapsed_sec: float
    length: int
    body_sample: str


class ReplaySkipped(TypedDict):
    url: str | None
    location: str | None
    name: str | None
    payload_type: str | None
    skipped: bool
    reason: str
    likely_vulnerable: bool


class ReplaySuccess(TypedDict):
    url: str
    method: str
    location: str
    name: str
    payload_type: str | None
    baseline: HttpProbeSample
    mutated: HttpProbeSample
    indicators: list[str]
    likely_vulnerable: bool


ReplayResult = ReplaySkipped | ReplaySuccess


class AnalyzeVectorSummary(TypedDict):
    url: str
    method: str
    location: str
    name: str
    original_value: str


class AnalyzeEntry(TypedDict):
    vector: AnalyzeVectorSummary
    normalized: NormalizedCandidates
    fingerprint: FingerprintResult
    exploit_analysis: ExploitResult
    mutations: Mutations


class AssessEntry(TypedDict):
    exploit_analysis: ConfirmedExploitResult
    mutation: Mutation
    replay: ReplayResult
