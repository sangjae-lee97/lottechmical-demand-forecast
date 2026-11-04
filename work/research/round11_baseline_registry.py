"""Local human-decision v2 comparison baselines. Offline; no automatic approval."""
import argparse
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import round11_ecos_snapshot_pipeline as p

LOCAL = p.ROOT / 'work/data/local_only'
REGISTRY = LOCAL / 'round11_registry'
APPROVAL_ID = r'\d{6}_[0-9a-f]{12}'


def local_path(path):
    path = Path(path).resolve()
    p.check(path.is_relative_to(LOCAL.resolve()) and path != LOCAL.resolve(), 'LOCAL_ONLY_PATH_REQUIRED')
    return path


def registry_path(path):
    path = local_path(path)
    for protected in (p.STORE, p.REPROCESSED, p.LOCK, p.BASELINE.parent):
        protected = protected.resolve()
        p.check(not path.is_relative_to(protected) and not protected.is_relative_to(path), 'PROTECTED_REGISTRY_LOCATION')
    return path


def hex_digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def source_identity():
    return {'registry_code_sha256': p.sha(Path(__file__).read_bytes()),
            'pipeline_code_sha256': p.sha(Path(p.__file__).read_bytes())}


def snapshot(folder, expected_sha):
    folder = local_path(folder)
    p.check(hex_digest(expected_sha), 'EXPLICIT_SNAPSHOT_HASH_REQUIRED')
    p.check(not any(path.is_symlink() for path in [folder, *folder.rglob('*')]), 'SNAPSHOT_SYMLINK_REJECTED')
    verified = p.validate_run(folder.name, expected_sha, folder.parent)
    m = json.loads((folder / 'manifest.json').read_bytes())
    p.check(verified['normalization_version'] == 2, 'V2_APPROVAL_CANDIDATE_REQUIRED')
    p.check(verified['collection_passed'] and m['status'] in
            ('VALIDATED_SNAPSHOT_REVIEW_NOT_PROMOTED', 'REPROCESSED_NOT_PROMOTED'), 'FAILED_OR_QUARANTINED_CANDIDATE')
    p.check(not m['validation_issues'] and not any(m['counts'].get(k, 0) for k in
            ('MISSING_OR_REMOVED', 'INVALID_OR_UNVERIFIED')), 'INVALID_CANDIDATE')
    p.check(not any('quarantine' in path.parts for path in folder.rglob('*')), 'QUARANTINED_CANDIDATE')
    expected_files = {r['path'] for r in m['files']} | {'manifest.json', 'manifest.sha256'}
    tree = p.tree_fingerprint(folder)
    p.check(set(tree) == expected_files, 'SNAPSHOT_UNTRACKED_OR_MISSING_FILES')
    rows = json.loads((folder / 'normalized.json').read_bytes())
    periods = p.validate_dataset(rows, 'SNAPSHOT', fixed_point=True)
    # Legacy replay remains compatible, but its old comparison baseline must pass
    # the new gate before this snapshot can become an operational candidate.
    p.validate_dataset(p.baseline_rows((folder / 'baseline/normalized_snapshot.json').read_bytes(), 2), 'BASELINE')
    meta = {'run_id': folder.name, 'manifest_sha256': expected_sha,
            'normalized_sha256': p.sha((folder / 'normalized.json').read_bytes()),
            'normalization_version': 2, 'validation_policy_version': 2,
            'tree_sha256': p.sha(p.encoded(tree)), 'file_count': len(tree), 'row_count': len(rows),
            'first': periods['C3000'][0], 'last': periods['C3000'][-1],
            'snapshot_finished_at': m['finished_at'], 'snapshot_status': m['status'],
            'parent_manifest_sha256': m.get('parent_run', {}).get('manifest_sha256'),
            'raw_responses': [{'path': r['path'], 'sha256': r['sha256']} for r in m['files'] if r['kind'] == 'api_raw']}
    return rows, meta


def parse_decision(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            p.check(key not in out, 'DUPLICATE_DECISION_FIELD')
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise p.PipelineError('INVALID_DECISION_JSON') from None


def decision(raw, meta, previous_sha):
    d = parse_decision(raw)
    required = {'schema_version', 'decision', 'reviewer_id', 'approved_at', 'reason', 'scope',
                'snapshot_manifest_sha256', 'snapshot_run_id', 'previous_approval_sha256', 'evidence', 'remaining_limitations'}
    p.check(isinstance(d, dict) and set(d) == required, 'DECISION_SCHEMA_MISMATCH')
    p.check(type(d['schema_version']) is int and d['schema_version'] == 1 and d['decision'] == 'APPROVE'
            and d['scope'] == 'comparison_baseline_only', 'WRONG_APPROVAL_SCOPE')
    p.check(all(isinstance(d[k], str) and d[k].strip() for k in ('reviewer_id', 'approved_at', 'reason')), 'EMPTY_APPROVAL_IDENTITY_OR_REASON')
    p.check(d['snapshot_manifest_sha256'] == meta['manifest_sha256'] and d['snapshot_run_id'] == meta['run_id'], 'DECISION_SNAPSHOT_MISMATCH')
    p.check(d['previous_approval_sha256'] == previous_sha, 'STALE_APPROVAL_DECISION')
    try:
        approved = datetime.fromisoformat(d['approved_at'])
        finished = datetime.fromisoformat(meta['snapshot_finished_at'])
        p.check(approved.tzinfo is not None and finished.tzinfo is not None
                and finished <= approved <= datetime.now(p.KST), 'INVALID_APPROVAL_TIME')
    except (ValueError, TypeError):
        raise p.PipelineError('INVALID_APPROVAL_TIME') from None
    p.check(isinstance(d['evidence'], list) and bool(d['evidence']), 'APPROVAL_EVIDENCE_REQUIRED')
    for item in d['evidence']:
        p.check(isinstance(item, dict) and set(item) <= {'uri', 'sha256'}
                and (bool(item.get('uri')) or hex_digest(item.get('sha256'))), 'INVALID_APPROVAL_EVIDENCE')
        p.check('sha256' not in item or hex_digest(item['sha256']), 'INVALID_APPROVAL_EVIDENCE')
        p.check('uri' not in item or (isinstance(item['uri'], str) and bool(item['uri'].strip())), 'INVALID_APPROVAL_EVIDENCE')
    p.check(isinstance(d['remaining_limitations'], list) and bool(d['remaining_limitations'])
            and all(isinstance(v, str) and v.strip() for v in d['remaining_limitations']), 'LIMITATIONS_REQUIRED')
    return d


def pointer(record, record_sha):
    return {'approval_id': record['approval_id'], 'sequence': record['sequence'], 'record_sha256': record_sha,
            'snapshot_manifest_sha256': record['snapshot']['manifest_sha256']}


def verify_registry(root=None, expected_tip=None, *, writer_active=False, allow_pending=False):
    root = registry_path(REGISTRY if root is None else root)
    if not root.exists():
        p.check(expected_tip is None, 'REGISTRY_TIP_MISMATCH')
        return {'records': [], 'current': None, 'tip_sha256': None, 'state': 'EMPTY_NOT_INITIALIZED'}
    p.check(not any(path.is_symlink() for path in root.rglob('*')), 'REGISTRY_SYMLINK_REJECTED')
    p.check(not (root / '.writer.lock').exists() or writer_active, 'REGISTRY_INCOMPLETE_WRITER_LOCK')
    p.check(not list(root.glob('.current.*.tmp')), 'REGISTRY_INCOMPLETE_POINTER_WRITE')
    p.check({f.name for f in root.iterdir()} <= {'records', 'current.json', '.writer.lock'}, 'UNEXPECTED_REGISTRY_FILE')
    entries = sorted((root / 'records').iterdir()) if (root / 'records').exists() else []
    records, previous_id, previous_sha = [], None, None
    for sequence, folder in enumerate(entries, 1):
        p.check(folder.is_dir() and not folder.is_symlink() and re.fullmatch(APPROVAL_ID, folder.name) is not None, 'REGISTRY_INCOMPLETE_RECORD')
        p.check({x.name for x in folder.iterdir()} == {'record.json', 'record.sha256', 'decision.json', 'snapshot'}, 'REGISTRY_INCOMPLETE_RECORD')
        raw = (folder / 'record.json').read_bytes()
        record, record_sha = json.loads(raw), p.sha(raw)
        p.check(p.encoded(record) == raw and (folder / 'record.sha256').read_text().strip() == record_sha, 'APPROVAL_RECORD_HASH_MISMATCH')
        p.check(record['approval_id'] == folder.name and record['sequence'] == sequence
                and record['previous_approval_id'] == previous_id and record['previous_record_sha256'] == previous_sha, 'APPROVAL_CHAIN_MISMATCH')
        p.check(record['approval_scope'] == 'comparison_baseline_only' and record['model_input_promoted'] is False
                and record['vintage_verification_granted'] is False, 'APPROVAL_PERMISSION_ESCALATION')
        copied = p.safe_path(folder, record['snapshot_relative_path'])
        _, meta = snapshot(copied, record['snapshot']['manifest_sha256'])
        p.check(meta == record['snapshot'], 'APPROVED_SNAPSHOT_CHANGED')
        decision_raw = (folder / 'decision.json').read_bytes()
        p.check(p.sha(decision_raw) == record['decision_sha256'], 'APPROVAL_DECISION_HASH_MISMATCH')
        d = decision(decision_raw, meta, previous_sha)
        p.check(all(record[k] == d[k] for k in ('reviewer_id', 'approved_at', 'reason')), 'DECISION_RECORD_MISMATCH')
        records.append({'record': record, 'record_sha256': record_sha, 'folder': folder})
        previous_id, previous_sha = folder.name, record_sha
    current_path = root / 'current.json'
    current = json.loads(current_path.read_bytes()) if current_path.exists() else None
    if records:
        acceptable = [pointer(records[-1]['record'], records[-1]['record_sha256'])]
        if allow_pending:
            acceptable.append(pointer(records[-2]['record'], records[-2]['record_sha256']) if len(records) > 1 else None)
        p.check(current in acceptable, 'REGISTRY_INCOMPLETE_CURRENT_NOT_AT_TIP')
    else:
        p.check(current is None, 'CURRENT_WITHOUT_APPROVAL')
    p.check(expected_tip is None or expected_tip == previous_sha, 'REGISTRY_TIP_MISMATCH')
    return {'records': records, 'current': current, 'tip_sha256': previous_sha, 'state': 'VERIFIED' if records else 'EMPTY'}


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())


def check_candidate(folder, expected_sha, root=None):
    root = registry_path(REGISTRY if root is None else root)
    _, meta = snapshot(folder, expected_sha)
    state = verify_registry(root)
    return {'status': 'ELIGIBLE_V2_PENDING_EXPLICIT_HUMAN_DECISION', 'dry_run': True,
            'snapshot': meta, 'approval_count': len(state['records']), 'current': state['current'],
            'registry_exists': root.exists(), 'registry_changed': False, 'human_approved': False,
            'model_input_promoted': False, 'source': source_identity()}


def approve(folder, expected_sha, decision_file, root=None, *, execute=False):
    root = registry_path(REGISTRY if root is None else root)
    folder = local_path(folder)
    _, meta = snapshot(folder, expected_sha)
    state = verify_registry(root)
    decision_raw = Path(decision_file).read_bytes()
    d = decision(decision_raw, meta, state['tip_sha256'])
    if not execute:
        return {'status': 'DECISION_VALIDATED_DRY_RUN_ONLY', 'dry_run': True, 'registry_changed': False,
                'snapshot_manifest_sha256': expected_sha, 'decision_sha256': p.sha(decision_raw), 'human_approved': False}
    root.mkdir(parents=True, exist_ok=True)
    (root / 'records').mkdir(exist_ok=True)
    lock_path = root / '.writer.lock'
    try:
        write_new(lock_path, b'approval transaction in progress\n')
    except FileExistsError:
        raise p.PipelineError('REGISTRY_WRITER_LOCKED') from None
    try:
        state = verify_registry(root, writer_active=True)
        d = decision(decision_raw, meta, state['tip_sha256'])
        sequence = len(state['records']) + 1
        approval_id = f'{sequence:06d}_' + uuid.uuid4().hex[:12]
        entry = root / 'records' / approval_id
        entry.mkdir(exist_ok=False)
        write_new(entry / 'decision.json', decision_raw)
        relative = 'snapshot/' + folder.name
        destination = entry / relative
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                write_new(p.safe_path(destination, path.relative_to(folder).as_posix()), path.read_bytes())
        _, copied_meta = snapshot(destination, expected_sha)
        p.check(copied_meta == meta, 'SNAPSHOT_CHANGED_DURING_APPROVAL')
        record = {'schema_version': 1, 'approval_id': approval_id, 'sequence': sequence,
                  'previous_approval_id': state['current']['approval_id'] if state['current'] else None,
                  'previous_record_sha256': state['tip_sha256'], 'snapshot': meta,
                  'source_snapshot_path': folder.relative_to(p.ROOT).as_posix(), 'snapshot_relative_path': relative,
                  'decision_sha256': p.sha(decision_raw), 'reviewer_id': d['reviewer_id'], 'approved_at': d['approved_at'],
                  'reason': d['reason'], 'recorded_at': p.now(), 'approval_scope': 'comparison_baseline_only',
                  'vintage_verification_granted': False, 'model_input_promoted': False, 'execution_source': source_identity()}
        raw = p.encoded(record)
        write_new(entry / 'record.json', raw)
        write_new(entry / 'record.sha256', (p.sha(raw) + '\n').encode())
        # The new record is fully checked while the previous pointer remains active.
        verify_registry(root, writer_active=True, allow_pending=True)
        temporary = root / ('.current.' + uuid.uuid4().hex + '.tmp')
        write_new(temporary, p.encoded(pointer(record, p.sha(raw))))
        os.replace(temporary, root / 'current.json')
        final = verify_registry(root, writer_active=True)
        return {'status': 'HUMAN_DECISION_RECORDED', 'approval_id': approval_id,
                'record_sha256': p.sha(raw), 'tip_sha256': final['tip_sha256'], 'current': final['current'],
                'approval_scope': 'comparison_baseline_only', 'model_input_promoted': False}
    finally:
        lock_path.unlink()  # Only this transaction's ephemeral lock; history is never removed.


def compare_approved(folder, expected_sha, root=None, *, baseline_id=None, use_current=False, expected_tip=None):
    root = registry_path(REGISTRY if root is None else root)
    p.check(bool(baseline_id) != bool(use_current), 'EXPLICIT_APPROVED_BASELINE_SELECTION_REQUIRED')
    state = verify_registry(root, expected_tip)
    selected = state['current']['approval_id'] if use_current and state['current'] else baseline_id
    matches = [r for r in state['records'] if r['record']['approval_id'] == selected]
    p.check(len(matches) == 1, 'APPROVED_BASELINE_NOT_FOUND')
    selected = matches[0]
    record = selected['record']
    old, baseline = snapshot(p.safe_path(selected['folder'], record['snapshot_relative_path']), record['snapshot']['manifest_sha256'])
    new, candidate = snapshot(folder, expected_sha)
    windows = json.loads((Path(folder) / 'manifest.json').read_bytes())['query_windows']
    events = p.compare_strict(old, new, windows)
    payload = {'baseline_id': record['approval_id'], 'baseline_record_sha256': selected['record_sha256'],
               'baseline_manifest_sha256': baseline['manifest_sha256'], 'candidate_manifest_sha256': candidate['manifest_sha256'],
               'comparison_policy_version': 2, 'events': events}
    return {**payload, **p.summary(events, [], 2), 'comparison_sha256': p.sha(p.encoded(payload)),
            'registry_tip_sha256': state['tip_sha256'], 'execution_source': source_identity(),
            'baseline_selection': 'registry_current' if use_current else 'explicit_approval_id'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-candidate', action='store_true')
    mode.add_argument('--approve', action='store_true')
    mode.add_argument('--compare', action='store_true')
    mode.add_argument('--verify-registry', action='store_true')
    parser.add_argument('--snapshot-kind', choices=['collected', 'reprocessed'])
    parser.add_argument('--run-id')
    parser.add_argument('--expected-manifest-sha256')
    parser.add_argument('--registry', type=Path, default=REGISTRY)
    parser.add_argument('--decision-file', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--execute-human-approval', action='store_true')
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument('--baseline-id')
    baseline.add_argument('--registry-current', action='store_true')
    parser.add_argument('--expected-tip-sha256')
    args = parser.parse_args(argv)
    try:
        if args.verify_registry:
            state = verify_registry(args.registry, args.expected_tip_sha256)
            result = {'state': state['state'], 'approval_count': len(state['records']), 'current': state['current'], 'tip_sha256': state['tip_sha256']}
        else:
            p.check(args.snapshot_kind is not None and args.run_id is not None
                    and re.fullmatch(r'\d{8}T\d{12}_[0-9a-f]{12}', args.run_id) is not None, 'SNAPSHOT_SELECTION_REQUIRED')
            folder = (p.STORE if args.snapshot_kind == 'collected' else p.REPROCESSED) / args.run_id
            if args.check_candidate:
                p.check(not args.execute_human_approval, 'CHECK_CANNOT_APPROVE')
                result = check_candidate(folder, args.expected_manifest_sha256, args.registry)
            elif args.approve:
                p.check(args.decision_file is not None, 'EXPLICIT_DECISION_DOCUMENT_REQUIRED')
                p.check(args.dry_run != args.execute_human_approval, 'CHOOSE_DRY_RUN_OR_EXPLICIT_HUMAN_EXECUTION')
                result = approve(folder, args.expected_manifest_sha256, args.decision_file, args.registry, execute=args.execute_human_approval)
            else:
                result = compare_approved(folder, args.expected_manifest_sha256, args.registry,
                                          baseline_id=args.baseline_id, use_current=args.registry_current, expected_tip=args.expected_tip_sha256)
                result = {k: v for k, v in result.items() if k != 'events'}  # Never print observation values.
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except p.PipelineError as error:
        print(json.dumps({'status': 'REJECTED', 'error': str(error), 'registry_not_auto_repaired': True}))
    except Exception:
        print(json.dumps({'status': 'FAILED', 'error': 'REGISTRY_FAILURE_REDACTED'}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
