"""Fixed task evidence, full required content once, without a 24 KiB call gate."""
import difflib
from .worker_store import canonical, sha


def packet(turn, source_sha, snapshot, previous=None):
    old = previous.get('workspace', {}) if previous else {}
    old_files = old.get('files', {})
    changed = sorted(n for n in snapshot['files'].keys() | old_files.keys()
                     if snapshot['files'].get(n) != old_files.get(n))
    # A previous REWORK is context, never an approved baseline. Keep its issues
    # and all unchanged source in the bounded packet so the review is complete.
    changes = []
    for name in changed:
        if name not in old_files and name in snapshot['files']:
            # There is no prior source for a new file, including after REWORK.
            # A full addition
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
                 execution_settings={k:turn.get(k) for k in ('work_mode','service_tier','goal_objective','goal_state')},
                 host_contract={'handoff':'Final response or user-authorized artifact only. No extra handoff file under a restricted deliverable contract.',
                                'archive':'Host appends the required archive summary after review, outside task workspace. Do not require a workspace archive-body file or certify an unprovided external receipt.'},
                 previous_review=previous.get('review') if previous else None,
                 previous_binding=previous.get('binding_sha256') if previous else None,
                 external_evidence_verified=False)
    value['binding_sha256'] = sha(canonical(value))
    size = len(canonical(value))
    return value, size
