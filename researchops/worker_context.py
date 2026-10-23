"""Bounded task evidence; every omission is explicit and oversize never calls a model."""
import difflib
from .worker_store import WorkerError, canonical, sha

MAX_PACKET_BYTES = 24576


def packet(turn, source_sha, snapshot, previous=None):
    old = previous.get('workspace', {}) if previous else {}
    old_files = old.get('files', {})
    changed = sorted(n for n in snapshot['files'].keys() | old_files.keys()
                     if snapshot['files'].get(n) != old_files.get(n))
    # A previous REWORK is context, never an approved baseline. Keep its issues
    # and all unchanged source in the bounded packet so the review is complete.
    changes = []
    for name in changed:
        if previous is None:
            # There is no prior source on the first review. A full addition
            # diff would duplicate the exact complete content already carried
            # in workspace.contents. Bind the addition and refer to that copy.
            changes.append({'path': name, 'change': 'added',
                            'after': snapshot['files'][name],
                            'content_ref': 'workspace.contents' if name in snapshot['contents'] else None})
            continue
        a, b = old.get('contents', {}).get(name, ''), snapshot['contents'].get(name, '')
        changes.append({'path': name, 'diff': ''.join(difflib.unified_diff(
            a.splitlines(True), b.splitlines(True), fromfile='before/'+name, tofile='after/'+name))})
    value = dict(scope='LOCAL_OWNED_WORKSPACE_ONLY', request=turn['prompt'],
                 task=turn['id'], attempt=turn.get('reworks', 0), source_sha256=source_sha,
                 final_response=turn['response'], workspace=snapshot, changes=changes,
                 previous_review=previous.get('review') if previous else None,
                 previous_binding=previous.get('binding_sha256') if previous else None,
                 external_evidence_verified=False)
    value['binding_sha256'] = sha(canonical(value))
    size = len(canonical(value))
    if size > MAX_PACKET_BYTES:
        raise WorkerError('REVIEW_CONTEXT_LIMIT_NEEDS_CONTEXT')
    return value, size
