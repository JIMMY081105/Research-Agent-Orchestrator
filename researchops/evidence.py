"""Hash-bound research gates. This module never launches research or trusts model PASS text.

TrustedRun objects and checker functions must be registered by the owning controller,
after its process/ledger validation. They are not fields accepted from a model/goal JSON.
Without a registered checker or trusted run, native physics/navigation/behavior remain
UNVERIFIED/BLOCKED. A successful JSON file is not itself proof of a scientific result.
"""
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Callable, Mapping

LAYERS = ("STATIC_GEOMETRY", "NATIVE_RUNTIME_COLLISION", "BODY_RADIUS_NAVIGATION", "ROBOT_BEHAVIOR", "BATCH_COMPLETENESS")
SCIENCE_LAYERS = LAYERS[:-1]
STATUSES = ("READY", "FAIL", "BLOCKED", "UNVERIFIED")
CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
INFRA_REASONS = {"EMPTY_SEEDS", "EMPTY_CASES", "MISSING_FILE", "TOOL_ERROR", "TOOL_CRASH", "AUTH", "NETWORK", "QUOTA", "OOM", "TIMEOUT", "INVALID_RESULT", "DEPENDENCY_MISSING"}
FORBIDDEN_NAMES = {".env", "auth.json", "credentials.json", "machine.json", ".netrc", ".npmrc", ".pypirc", ".git-credentials"}
FORBIDDEN_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".ppk", ".kdbx", ".jks", ".keystore")
FORBIDDEN_PREFIXES = (".env.", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
FORBIDDEN_PARTS = {".git", ".venv", "venv", "env", "__pycache__"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


EVALUATOR_SHA256 = digest(Path(__file__).read_bytes())
_ISSUER = object()


class Assessment(dict):
    """Controller-memory result, not constructible from model/persisted JSON alone."""
    def __init__(self, issuer, value):
        if issuer is not _ISSUER:
            raise ValueError("Assessments are issued only after evaluation")
        super().__init__(value)
        self._issuer = issuer
        self._content_sha256 = digest(canonical(value))


def issued_assessment(value):
    try:
        return (type(value) is Assessment and value._issuer is _ISSUER
                and value._content_sha256 == digest(canonical(value)))
    except (ValueError, TypeError):
        return False


def _assess(value):
    return Assessment(_ISSUER, value)


class EvidenceError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class FileRef:
    path: str
    sha256: str

    def as_dict(self):
        return {"path": self.path, "sha256": self.sha256}


class EvidenceStore:
    """Only explicitly selected files below this system's runtime. Never a directory pack."""
    def __init__(self, runtime):
        self.runtime = Path(os.path.abspath(runtime))
        self._no_links(self.runtime)
        if not self.runtime.is_dir():
            raise EvidenceError("RUNTIME_MISSING")

    @staticmethod
    def _no_links(path):
        for item in (path, *path.parents):
            if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
                raise EvidenceError("UNSAFE_REPARSE_PATH")

    def path(self, relative):
        if type(relative) is not str or not relative or any(c in relative for c in ('\\', ':', '\x00', '\n', '\r', '`', '<', '>', '[', ']', '(', ')', '"', '|', '?', '*')):
            raise EvidenceError("UNSAFE_PATH")
        parts = relative.split("/")
        if any(p in ("", ".", "..") for p in parts) or PurePosixPath(relative).is_absolute():
            raise EvidenceError("UNSAFE_PATH")
        for part in parts:
            name = part.lower()
            if name in FORBIDDEN_NAMES or name in FORBIDDEN_PARTS or name.startswith(FORBIDDEN_PREFIXES) or name.endswith(FORBIDDEN_SUFFIXES):
                raise EvidenceError("SENSITIVE_PATH_REFUSED")
        path = self.runtime.joinpath(*parts)
        self._no_links(path)
        if not path.resolve().is_relative_to(self.runtime.resolve()):
            raise EvidenceError("UNSAFE_PATH")
        return path

    def fingerprint(self, relative):
        path = self.path(relative)
        if not path.is_file():
            raise EvidenceError("MISSING_FILE")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        return FileRef(relative, h.hexdigest())

    def verify(self, ref):
        if not isinstance(ref, FileRef) or type(ref.sha256) is not str or not SHA.fullmatch(ref.sha256):
            raise EvidenceError("INVALID_FILE_REFERENCE")
        if self.fingerprint(ref.path) != ref:
            raise EvidenceError("STALE_FILE_HASH")

    def json(self, ref, limit=1024 * 1024):
        self.verify(ref)
        path = self.path(ref.path)
        if path.stat().st_size > limit:
            raise EvidenceError("EVIDENCE_TOO_LARGE")
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError):
            raise EvidenceError("INVALID_RESULT")


@dataclass(frozen=True)
class Binding:
    source: tuple[FileRef, ...]
    inputs: tuple[FileRef, ...]
    artifacts: tuple[FileRef, ...]

    def as_dict(self):
        return {role: [r.as_dict() for r in getattr(self, role)] for role in ("source", "inputs", "artifacts")}

    @property
    def sha256(self):
        return digest(canonical(self.as_dict()))

    def verify(self, store):
        for role in ("source", "inputs", "artifacts"):
            values = getattr(self, role)
            if not values or len({r.path for r in values}) != len(values):
                raise EvidenceError("INCOMPLETE_" + role.upper() + "_BINDING")
            for ref in values:
                store.verify(ref)


@dataclass(frozen=True)
class TrustedRun:
    """Controller-verified receipt, supplied out of band from model-controlled evidence.

    `receipt` is hash-bound. Controller ownership/session/PID/ledger verification must
    precede registration; arbitrary JSON cannot mint a TrustedRun through evaluate_gate.
    """
    run_id: str
    tool_id: str
    receipt: FileRef
    binding: Binding
    case_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    control_role: str  # target, positive, negative
    completed: bool
    exit_code: int
    process_verified: bool


@dataclass(frozen=True)
class Observation:
    outcome: str  # PASS, FAIL, BLOCKED, UNKNOWN (scientific outcome, not process exit)
    reason: str


@dataclass(frozen=True)
class RegisteredChecker:
    checker_id: str
    function: Callable[[EvidenceStore, TrustedRun], Observation]
    source: FileRef
    layers: tuple[str, ...] = ("STATIC_GEOMETRY",)
    scientific_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateContract:
    gate_id: str
    sample_id: str
    layer: str
    checker_id: str
    target: TrustedRun
    positive: TrustedRun
    negative: TrustedRun
    negative_reason: str
    case_ids: tuple[str, ...]
    seed_policy: str = "seeded"
    seeds: tuple[int, ...] = ()


def verdict(status, reason, *, layer=None, sample_id=None, refs=(), **extra):
    if status not in STATUSES or not CODE.fullmatch(reason):
        raise ValueError("Invalid fixed verdict")
    value = {"status": status, "reason": reason, "evidence": [r.as_dict() for r in refs]}
    if layer is not None:
        value["layer"] = layer
    if sample_id is not None:
        value["sample_id"] = sample_id
    return {**value, **extra}


def evaluate_gate(store: EvidenceStore, contract: GateContract, trusted_runs: Mapping[str, TrustedRun],
                  checkers: Mapping[str, RegisteredChecker]):
    """Check controls before classifying the target. Nothing is executed or auto-imported.

    An infrastructure failure blocks measurement. Only valid controls plus a registered
    scientific checker can produce READY/FAIL. Counterexamples must fail for the exact
    predeclared scientific reason, never missing files, empty seeds or broken tools.
    """
    if not isinstance(contract, GateContract):
        return _assess(verdict("BLOCKED", "INVALID_GATE_CONTRACT"))
    layer, sample = contract.layer, contract.sample_id
    def result(status, reason, **extra):
        return _assess(verdict(status, reason, layer=layer, sample_id=sample, **extra))
    if (layer not in SCIENCE_LAYERS or type(contract.gate_id) is not str or type(sample) is not str
            or not IDENTIFIER.fullmatch(contract.gate_id) or not IDENTIFIER.fullmatch(sample)):
        return result("BLOCKED", "INVALID_GATE_CONTRACT")
    if (not contract.case_ids or len(contract.case_ids) > 10000 or not all(type(c) is str and IDENTIFIER.fullmatch(c) for c in contract.case_ids)
            or len(set(contract.case_ids)) != len(contract.case_ids)):
        return result("UNVERIFIED", "EMPTY_OR_DUPLICATE_CASE_SET")
    if contract.seed_policy == "seeded":
        if (not contract.seeds or len(contract.seeds) > 10000 or any(type(s) is not int for s in contract.seeds)
                or len(set(contract.seeds)) != len(contract.seeds)):
            return result("UNVERIFIED", "EMPTY_OR_INVALID_SEED_SET")
    elif contract.seed_policy != "deterministic" or contract.seeds or layer == "ROBOT_BEHAVIOR":
        return result("UNVERIFIED", "SEED_POLICY_UNVERIFIED")
    if type(contract.negative_reason) is not str or not CODE.fullmatch(contract.negative_reason) or contract.negative_reason in INFRA_REASONS:
        return result("BLOCKED", "INVALID_NEGATIVE_CONTROL_REASON")
    checker = checkers.get(contract.checker_id)
    if checker is None:
        return result("UNVERIFIED", "CHECKER_NOT_AVAILABLE")
    if not isinstance(checker, RegisteredChecker) or layer not in checker.layers:
        return result("UNVERIFIED", "CHECKER_NOT_REGISTERED_FOR_LAYER")
    if not checker.scientific_reasons:
        return result("UNVERIFIED", "SCIENTIFIC_REASONS_NOT_CONFIGURED")
    if contract.negative_reason not in checker.scientific_reasons:
        return result("BLOCKED", "UNREGISTERED_NEGATIVE_CONTROL_REASON")
    runs = (contract.target, contract.positive, contract.negative)
    if not all(isinstance(run, TrustedRun) for run in runs) or len({run.run_id for run in runs}) != 3:
        return result("BLOCKED", "CONTROL_RUNS_NOT_DISTINCT")
    try:
        observations = {}
        source = contract.target.binding.source
        if not isinstance(checker, RegisteredChecker) or checker.checker_id != contract.checker_id or checker.source not in source:
            raise EvidenceError("UNBOUND_CHECKER_SOURCE")
        store.verify(checker.source)
        actual_checker = inspect.getsourcefile(checker.function)
        if not actual_checker or Path(actual_checker).resolve() != store.path(checker.source.path).resolve():
            raise EvidenceError("CHECKER_SOURCE_ORIGIN_MISMATCH")
        for role, run in zip(("target", "positive", "negative"), runs):
            if not IDENTIFIER.fullmatch(run.run_id) or trusted_runs.get(run.run_id) != run:
                raise EvidenceError("UNTRUSTED_RUN")
            if run.control_role != role or run.tool_id != contract.checker_id or run.binding.source != source:
                raise EvidenceError("RUN_CONTRACT_MISMATCH")
            if run.case_ids != contract.case_ids or run.seeds != contract.seeds:
                raise EvidenceError("RUN_CASE_OR_SEED_MISMATCH")
            if run.completed is not True or type(run.exit_code) is not int or run.exit_code != 0 or run.process_verified is not True:
                raise EvidenceError("RUN_NOT_SUCCESSFULLY_MEASURED")
            store.verify(run.receipt)
            run.binding.verify(store)
            observation = checker.function(store, run)
            if not isinstance(observation, Observation) or not CODE.fullmatch(observation.reason):
                raise EvidenceError("INVALID_CHECKER_RESULT")
            if (observation.outcome in ("UNKNOWN", "BLOCKED") or observation.reason in INFRA_REASONS
                    or observation.reason not in checker.scientific_reasons):
                raise EvidenceError("MEASUREMENT_INFRASTRUCTURE_FAILURE")
            if observation.outcome not in ("PASS", "FAIL"):
                raise EvidenceError("INVALID_CHECKER_RESULT")
            observations[role] = observation
        # An earlier target/control may have changed while another checker ran.
        for run in runs:
            store.verify(run.receipt)
            run.binding.verify(store)
    except EvidenceError as error:
        return result("BLOCKED", error.reason)
    except Exception:
        return result("BLOCKED", "CHECKER_EXCEPTION")
    if observations["positive"].outcome != "PASS":
        return result("BLOCKED", "POSITIVE_CONTROL_FAILED")
    if observations["negative"].outcome != "FAIL":
        return result("BLOCKED", "NEGATIVE_CONTROL_NOT_REJECTED")
    if observations["negative"].reason != contract.negative_reason:
        return result("BLOCKED", "NEGATIVE_CONTROL_REASON_MISMATCH")
    target = observations["target"]
    refs = tuple(run.receipt for run in runs)
    return result("READY" if target.outcome == "PASS" else "FAIL", target.reason, refs=refs,
                  gate_id=contract.gate_id, binding_sha256=contract.target.binding.sha256,
                  evaluator_sha256=EVALUATOR_SHA256,
                  binding=contract.target.binding.as_dict(),
                  control_bindings={"positive": contract.positive.binding.as_dict(), "negative": contract.negative.binding.as_dict()},
                  controls={"positive": "PASS", "negative": "EXPECTED_FAIL", "negative_reason": contract.negative_reason},
                  case_count=len(contract.case_ids), seeds=list(contract.seeds), seed_policy=contract.seed_policy,
                  scope="SINGLE_SAMPLE_SINGLE_LAYER")


def summarize_sample(sample_id, results):
    """All four scientific layers are needed for full READY; static alone stays scoped."""
    rows = list(results)
    if any(not issued_assessment(row) for row in rows):
        return _assess(verdict("BLOCKED", "UNISSUED_LAYER_ASSESSMENT", sample_id=sample_id))
    if type(sample_id) is not str or not IDENTIFIER.fullmatch(sample_id) or any(r.get("sample_id") != sample_id or r.get("layer") not in SCIENCE_LAYERS for r in rows):
        return _assess(verdict("BLOCKED", "SAMPLE_ID_OR_LAYER_MISMATCH", sample_id=sample_id))
    if len({r["layer"] for r in rows}) != len(rows):
        return _assess(verdict("BLOCKED", "DUPLICATE_LAYER_EVIDENCE", sample_id=sample_id))
    by_layer = {r["layer"]: r for r in rows}
    missing = [layer for layer in SCIENCE_LAYERS if layer not in by_layer]
    states = [r.get("status") for r in rows]
    if any(s not in STATUSES for s in states):
        return _assess(verdict("BLOCKED", "INVALID_LAYER_VERDICT", sample_id=sample_id))
    if "FAIL" in states:
        status, reason = "FAIL", "SCIENTIFIC_GATE_FAILED"
    elif "BLOCKED" in states:
        status, reason = "BLOCKED", "MEASUREMENT_BLOCKED"
    elif missing or "UNVERIFIED" in states:
        status, reason = "UNVERIFIED", "REQUIRED_LAYER_EVIDENCE_MISSING"
    else:
        status, reason = "READY", "ALL_SCIENTIFIC_LAYERS_PASSED"
    return _assess(verdict(status, reason, sample_id=sample_id, layers=by_layer, missing_layers=missing,
                          scope="SINGLE_SAMPLE_ALL_SCIENTIFIC_LAYERS"))


def summarize_batch(expected_ids, sample_results, declared_total):
    expected, rows = list(expected_ids), list(sample_results)
    def answer(status, reason, **extra):
        return _assess(verdict(status, reason, layer="BATCH_COMPLETENESS", scope="EXACT_DECLARED_BATCH", **extra))
    if not expected or any(type(x) is not str or not IDENTIFIER.fullmatch(x) for x in expected) or len(set(expected)) != len(expected):
        return answer("BLOCKED", "INVALID_BATCH_ID_CONTRACT")
    if type(declared_total) is not int or declared_total != len(expected):
        return answer("BLOCKED", "BATCH_DENOMINATOR_MISMATCH")
    if any(not issued_assessment(row) for row in rows):
        return answer("BLOCKED", "UNISSUED_SAMPLE_ASSESSMENT")
    found = [r.get("sample_id") for r in rows]
    if len(set(found)) != len(found):
        return answer("BLOCKED", "BATCH_DUPLICATE_SAMPLE_ID")
    if set(found) - set(expected):
        return answer("BLOCKED", "BATCH_UNEXPECTED_SAMPLE_ID")
    missing = sorted(set(expected) - set(found))
    counts = {status: sum(r.get("status") == status for r in rows) for status in STATUSES}
    if any(r.get("status") not in STATUSES or r.get("scope") != "SINGLE_SAMPLE_ALL_SCIENTIFIC_LAYERS" for r in rows):
        return answer("BLOCKED", "INVALID_BATCH_SAMPLE_RESULT")
    if missing:
        status, reason = "UNVERIFIED", "BATCH_MISSING_SAMPLE_IDS"
    elif counts["FAIL"]:
        status, reason = "FAIL", "BATCH_SCIENTIFIC_FAILURES"
    elif counts["BLOCKED"]:
        status, reason = "BLOCKED", "BATCH_MEASUREMENT_BLOCKED"
    elif counts["UNVERIFIED"]:
        status, reason = "UNVERIFIED", "BATCH_HAS_UNVERIFIED_SAMPLES"
    else:
        status, reason = "READY", "EXACT_BATCH_COMPLETE"
    return answer(status, reason, expected_ids=expected, denominator=len(expected), observed_count=len(rows),
                  ready_count=counts["READY"], counts=counts, missing_ids=missing, samples=rows)


def reference_only(store, sample_id, layer, refs, reason="HISTORICAL_REFERENCE_NOT_REEVALUATED"):
    """Expose real retained files without minting any new scientific PASS or native claim."""
    if not IDENTIFIER.fullmatch(sample_id) or layer not in SCIENCE_LAYERS:
        raise EvidenceError("INVALID_REFERENCE_SCOPE")
    for ref in refs:
        store.verify(ref)
    return _assess(verdict("UNVERIFIED", reason, layer=layer, sample_id=sample_id, refs=tuple(refs),
                          scope="SINGLE_SAMPLE_SINGLE_LAYER"))


def accepted_static_reference(store, task_id):
    """Recheck a retained CPU stair acceptance; do not invent new controls/runtime tests.

    The old ACCEPTED task remains unchanged. Its accepted static result is preserved as
    history, while this new multi-layer contract stays UNVERIFIED until actual controls
    and higher-layer probes are registered and executed under separate authorization.
    """
    import uuid
    if type(task_id) is not str or str(uuid.UUID(task_id)) != task_id:
        raise EvidenceError("INVALID_TASK_ID")
    prefix = "tasks/" + task_id + "/"
    refs = [store.fingerprint(prefix+name) for name in ("spec.json", "artifact.json", "acceptance.json", "writer.json", "review.json")]
    spec, artifact, acceptance, writer, review = (store.json(ref) for ref in refs)
    sha = spec["source"]["sha256"]
    binding = digest(canonical({"spec": spec, "artifact": artifact}))
    if (spec.get("action") != "scene_stair_workflow" or spec.get("id") != task_id
            or digest(canonical(spec["input"])) != spec["input_sha256"]
            or artifact.get("task_id") != task_id or artifact.get("input_sha256") != spec["input_sha256"]
            or artifact.get("source_sha256") != sha or acceptance.get("source_sha256") != sha
            or acceptance.get("artifact_sha256") != digest(canonical(artifact))
            or acceptance.get("binding_sha256") != binding
            or review.get("review") != {"task_id": task_id, "binding_sha256": binding, "verdict": "PASS", "issues": []}
            or review.get("call_id") != acceptance.get("review_call")
            or writer.get("engine") != "codex" or writer.get("evidence", {}).get("exit_code") != 0
            or review.get("evidence", {}).get("engine") != "claude" or review.get("evidence", {}).get("exit_code") != 0
            or not artifact.get("checks") or not all(v is True for v in artifact["checks"].values())):
        raise EvidenceError("RETAINED_STATIC_ACCEPTANCE_INVALID")
    source_rows = spec["source"]["files"]
    if not SHA.fullmatch(sha) or digest(canonical(source_rows)) != sha:
        raise EvidenceError("RETAINED_SOURCE_MANIFEST_INVALID")
    for relative, value in source_rows.items():
        ref = FileRef("snapshots/"+sha+"/source/"+relative, value)
        store.verify(ref)
        refs.append(ref)
    runs = artifact.get("tool_runs", [])
    if [r.get("tool") for r in runs] != ["scene.room_meshes", "stair.candidates", "stair.build_usd", "stair.check_usd"]:
        raise EvidenceError("RETAINED_STATIC_TOOL_SET_INVALID")
    has_usd = False
    for run in runs:
        if run.get("ok") is not True or run.get("exit_code") != 0 or not run.get("outputs"):
            raise EvidenceError("RETAINED_STATIC_TOOL_FAILED")
        for relative, value in run["outputs"].items():
            ref = FileRef(prefix+"work/"+relative, value)
            store.verify(ref)
            refs.append(ref)
            has_usd |= ref.path.endswith("/stair.usda")
    if not has_usd:
        raise EvidenceError("RETAINED_STATIC_ASSET_MISSING")
    return _assess(verdict("UNVERIFIED", "RETAINED_STATIC_ACCEPTANCE_ONLY", layer="STATIC_GEOMETRY", sample_id=task_id,
                          refs=tuple(refs), scope="SINGLE_SAMPLE_SINGLE_LAYER", legacy_static_accepted=True))
