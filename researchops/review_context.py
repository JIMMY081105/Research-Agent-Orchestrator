"""Deterministic review selection, immutable baseline binding and fail-closed byte budgets."""
import difflib
import json
import re
from pathlib import Path, PurePosixPath

from .dashboard_bundle import safe_path, canonical, digest, read_small_json

SKILLS = ('skills/diff-review.md', 'skills/risk-aware-review.md', 'skills/token-budget.md')
UI_ELIGIBLE = frozenset(('researchops/mission_web.py', 'researchops/dashboard_web.py', 'native/SceneControl.cs',
                        'tools/verify_mission_ui.py', 'tools/verify_desktop.py'))
REQUIRED_UI_CONTEXT = UI_ELIGIBLE
LIMIT = 2 * 1024 * 1024
SENSITIVE = re.compile(r'/api/|approval|permission|sandbox|csrf|credential|fetch\s*\(|Process\.Start|navigation|webmessage|hostobject', re.I)


def ui_change(name, old, new):
    if old is None or new is None:
        return False
    a, b = old.decode('utf-8-sig'), new.decode('utf-8-sig')
    if name == 'native/SceneControl.cs':
        pattern = r'(private const string Probe = @")(.*?)(";)'
        left, right = re.search(pattern,a,re.S), re.search(pattern,b,re.S)
        if not left or not right or a[:left.start(2)] != b[:right.start(2)] or a[left.end(2):] != b[right.end(2):]:
            return False
    lines = difflib.ndiff(a.splitlines(),b.splitlines())
    return not any(SENSITIVE.search(line[2:]) for line in lines if line.startswith(('+ ','- ')))


def relative(name):
    parts = name.split('/') if type(name) is str else []
    if (not parts or any(p in ('', '.', '..', '.runtime', '.venv', '.git') for p in parts)
            or '\\' in name or ':' in name or PurePosixPath(name).is_absolute()
            or any(p.lower().startswith(('.env', 'credentials', 'auth.json', 'id_rsa', 'id_ed25519')) for p in parts)
            or Path(name).suffix.lower() in ('.key', '.pem', '.pfx', '.p12')):
        raise ValueError('REVIEW_UNSAFE_SOURCE_PATH')
    return name


def read_sources(root, manifest):
    if (type(manifest) is not dict or type(manifest.get('files')) is not dict
            or digest(canonical(manifest['files'])) != manifest.get('sha256')):
        raise ValueError('REVIEW_MANIFEST_INVALID')
    names = [relative(n) for n in manifest['files']]  # Vet all paths before any content.
    values = {}
    for name in names:
        path = safe_path(Path(root) / name)
        with path.open('rb') as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT or digest(raw) != manifest['files'][name]:
            raise ValueError('REVIEW_SOURCE_BINDING_CHANGED')
        raw.decode('utf-8-sig')
        values[name] = raw
    return values


def baseline(snapshot, review_path):
    """Verify historical manifests independently of today's expanded source file list."""
    snapshot, review_path = safe_path(snapshot), safe_path(review_path)
    manifest = read_small_json(snapshot / 'manifest.json')
    with review_path.open('rb') as stream:
        proof_raw=stream.read(LIMIT+1)
    if len(proof_raw)>LIMIT:raise ValueError('REVIEW_BASELINE_NOT_APPROVED')
    proof = json.loads(proof_raw)
    if (manifest.get('owner') != 'BGV.Windows.SceneControl.Desktop.v1'
            or type(manifest.get('files')) is not dict
            or digest(canonical(manifest['files'])) != manifest.get('sha256')
            or snapshot.name != manifest['sha256']
            or proof.get('owner') != manifest['owner'] or proof.get('status') != 'PASS'
            or proof.get('verdict') != 'PASS' or proof.get('issues') != []
            or proof.get('tools_disabled') is not True
            or proof.get('evidence', {}).get('exit_code') != 0
            or proof.get('bundle_sha256') != manifest['sha256']):
        raise ValueError('REVIEW_BASELINE_NOT_APPROVED')
    files = {}
    for path, sha in manifest['files'].items():
        relative(path)
        if path.startswith('source/') and path != 'source/config/live.json' and not path.startswith('source/assets/'):
            files[path[7:]] = sha
    source = dict(files=files, sha256=digest(canonical(files)))
    if source['sha256'] != manifest.get('source_sha256') or proof.get('source_sha256') != source['sha256']:
        raise ValueError('REVIEW_BASELINE_BINDING_INVALID')
    contents = read_sources(snapshot / 'source', source)
    return source, contents, dict(source_sha256=source['sha256'], bundle_sha256=manifest['sha256'],
                                 review_sha256=digest(proof_raw))


def compact_tests(tests, raw_sha, source_sha):
    if (tests.get('source_sha256') != source_sha or tests.get('success') is not True
            or tests.get('source_unchanged') is not True or type(tests.get('tests_run')) is not int
            or tests['tests_run'] < 1 or type(tests.get('discovered')) is not int or tests.get('discovered') != tests['tests_run']
            or any(tests.get(k) != [] for k in ('errors', 'failures', 'skipped'))):
        raise ValueError('REVIEW_CURRENT_TESTS_REQUIRED')
    result = {k: tests[k] for k in ('source_sha256', 'source_unchanged', 'success', 'tests_run', 'discovered', 'errors', 'failures', 'skipped')}
    result['evidence_sha256'] = raw_sha
    result['native_checks'] = [dict(scope=v.get('scope'), success=v.get('success'),
                                    checks_passed=sum(x is True for x in v.get('checks', {}).values()),
                                    checks_total=len(v.get('checks', {})))
                              for v in tests.get('native_fixture_verifications', []) if type(v) is dict]
    result['limits'] = 'Fixture results do not prove installed service, natural scheduling or scientific readiness.'
    return result


def prepare(root, source, tests_path, *, snapshot=None, review_path=None, scope='auto', include=(), rules_root=None):
    if scope not in ('auto', 'full', 'delta'):
        raise ValueError('REVIEW_SCOPE_INVALID')
    current = read_sources(root, source)
    rules = {n:current[n] for n in (*SKILLS,'config/review-context.json')} if rules_root is None else {}
    if rules_root is not None:
        for name in (*SKILLS,'config/review-context.json'):
            with safe_path(Path(rules_root)/name).open('rb') as stream:
                raw=stream.read(16385)
            if len(raw)>16384:raise ValueError('REVIEW_CONTEXT_POLICY_INVALID')
            rules[name]=raw
    policy = json.loads(rules['config/review-context.json'])
    if (policy.get('schema') != 1 or policy.get('skills') != list(SKILLS)
            or type(policy.get('ui_paths')) is not list or type(policy.get('ui_context')) is not list
            or type(policy.get('max_packet_bytes')) is not int or not 8192 <= policy['max_packet_bytes'] <= 262144
            or type(policy.get('max_full_packet_bytes')) is not int or not 8192 <= policy['max_full_packet_bytes'] <= LIMIT):
        raise ValueError('REVIEW_CONTEXT_POLICY_INVALID')
    for name in policy.get('ui_paths', []) + policy.get('ui_context', []):
        relative(name)
    if not set(policy['ui_paths']) <= UI_ELIGIBLE or not REQUIRED_UI_CONTEXT <= set(policy['ui_context']):
        raise ValueError('REVIEW_CONTEXT_POLICY_INVALID')
    before, proof = {}, None
    if snapshot is not None or review_path is not None:
        if snapshot is None or review_path is None:
            raise ValueError('REVIEW_BASELINE_REQUIRED')
        _, before, proof = baseline(snapshot, review_path)
    elif scope == 'delta':
        raise ValueError('REVIEW_BASELINE_REQUIRED')
    changed = sorted(n for n in current.keys() | before.keys() if current.get(n) != before.get(n))
    if proof is not None and not changed and scope != 'full':
        raise ValueError('REVIEW_NO_SOURCE_CHANGE')
    ui_only = (proof is not None and bool(changed) and set(changed) <= set(policy['ui_paths'])
               and all(ui_change(n,before.get(n),current.get(n)) for n in changed))
    if scope == 'delta' and not ui_only:
        raise ValueError('REVIEW_FULL_SCOPE_REQUIRED')
    delta = scope != 'full' and ui_only
    selected = set(changed) | (set(policy['ui_context']) & current.keys()) if delta else set(current)
    for name in include:
        relative(name)
        if name not in current:
            raise ValueError('REVIEW_CONTEXT_FILE_UNKNOWN')
        selected.add(name)
    changes = []
    for name in changed:
        old, new = before.get(name, b''), current.get(name, b'')
        changes.append(dict(path=name, operation='DELETE' if name not in current else 'ADD' if name not in before else 'MODIFY',
            before_sha256=digest(old) if name in before else None, after_sha256=digest(new) if name in current else None,
            diff=''.join(difflib.unified_diff(old.decode('utf-8-sig').splitlines(keepends=True),
                 new.decode('utf-8-sig').splitlines(keepends=True), fromfile='before/'+name, tofile='after/'+name, n=5))))
    tests_path = safe_path(tests_path)
    with tests_path.open('rb') as stream:
        tests_raw = stream.read(LIMIT + 1)
    if len(tests_raw) > LIMIT:
        raise ValueError('REVIEW_TEST_EVIDENCE_TOO_LARGE')
    packet = dict(protocol=2, scope='DELTA_WITH_CONTEXT' if delta else 'FULL_SOURCE',
                  source_sha256=source['sha256'], source_manifest=source, baseline=proof,
                  changed_paths=changed, selected_paths=sorted(selected),
                  omitted_paths=sorted(set(current)-selected),
                  selection_reason='Fixed UI cross-language context and complete differences' if delta else 'Initial or sensitive/unknown change requires full source',
                  changes=changes if proof is not None else [],
                  contents={n:current[n].decode('utf-8-sig') for n in sorted(selected) if n in current},
                  tests=compact_tests(json.loads(tests_raw),digest(tests_raw),source['sha256']))
    criteria = '\n\n'.join(rules[n].decode('utf-8-sig') for n in SKILLS)
    packet['review_rules'] = {n:digest(raw) for n,raw in rules.items()}
    packet['preprocessor_sha256'] = digest(Path(__file__).read_bytes())
    packet['criteria_sha256'] = digest(criteria.encode())
    limit = policy['max_packet_bytes'] if delta else policy['max_full_packet_bytes']
    size = len(canonical(packet)) + len(criteria.encode())
    if size > limit:
        raise ValueError('REVIEW_CONTEXT_LIMIT_NEEDS_CONTEXT_PLAN')
    return packet, criteria, dict(packet_bytes=size, max_packet_bytes=limit, estimated_tokens=None,
                                 actual_tokens='UNAVAILABLE_UNTIL_PROVIDER_RESPONSE')
