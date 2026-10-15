"""One reviewed, offline cleanup; never import the app or perform network I/O.

Run before app/worker imports. Both databases are locked and committed through
one attached rollback-journal transaction. Public results contain counts, fixed
case numbers and hashes only. Private backups retain the original evidence.
"""
import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import uuid


SCHEMA = 'petpivot-test-case-cleanup-v1'
KEEP = 'R20261014-0009'
APPROVED_IDS = tuple(['R20261014-%04d' % n for n in range(1, 9)] +
                     ['R20261015-%04d' % n for n in range(1, 6)])
APPROVAL_FILENAME = '.test-case-cleanup-approval.json'
COMPLETED_FILENAME = '.test-case-cleanup-completed.json'
RECOVERY_FILENAME = '.test-case-cleanup-recovery-required.json'
LOCK_FILENAME = '.test-case-cleanup.lock'
CASE = re.compile(r'R([0-9]{8})-([0-9]{4,})\Z')
CASE_IN_TEXT = re.compile(r'(?<![A-Za-z0-9])R[0-9]{8}-[0-9]{4,}(?![0-9])')
REPAIR_CHILDREN = ('line_receipts', 'line_handshakes', 'cloud_outbox', 'cloud_sync_runs',
    'pickup_outbox', 'pickup_sync_runs', 'pickup_notification_outbox',
    'pickup_dispatch_outbox', 'pickup_dispatch_events')
PAYMENT_DELETE_ORDER = ('wb_prod_messages', 'wb_notifications', 'wb_real_manual_approvals',
    'wb_refund_followups', 'wb_real_order_checks', 'wb_payment_sheet_outbox',
    'wb_payment_sheet_state', 'wb_requests', 'wb_audit', 'wb_orders',
    'wb_quotes', 'wb_cases', 'wb_prod_links')
PAYMENT_KEYS = {name: 'id' for name in PAYMENT_DELETE_ORDER}
PAYMENT_KEYS.update(wb_real_manual_approvals='quote_id', wb_refund_followups='quote_id',
    wb_payment_sheet_outbox='case_id', wb_payment_sheet_state='case_id', wb_prod_links='real_id')
PROTECTED_REPAIR = ('line_entry_tickets', 'line_webhook_events', 'line_outbox',
    'pickup_notification_groups', 'pickup_notification_settings',
    'pickup_notification_events', 'dispatch_workflow_settings', 'sqlite_sequence')
PENDING = ('pending', 'working', 'failed', 'needs_review', 'ready', 'responding')


class CleanupError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _need(condition, code):
    if not condition:
        raise CleanupError(code)


def _dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_dump(value).encode('utf-8')).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_json_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(CleanupError('invalid_json')))
    except (ValueError, TypeError, RecursionError):
        raise CleanupError('invalid_json') from None


def _folder(value):
    path = Path(value)
    _need(path.is_absolute() and not path.is_symlink() and path.is_dir(), 'data_directory_invalid')
    _need(os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(path.resolve())), 'data_directory_invalid')
    return path.resolve()


def _regular(path):
    _need(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1, 'file_scope_invalid')
    return path


def _read_json(path):
    _regular(path)
    _need(0 < path.stat().st_size <= 65536, 'marker_size_invalid')
    return _json(path.read_text(encoding='utf-8'))


def _atomic_json(path, value):
    _need(not path.is_symlink(), 'file_scope_invalid')
    temporary = path.with_name('.cleanup-write-' + secrets.token_hex(8))
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as file:
            file.write(_dump(value))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _tables(c, db):
    return {row['name'] for row in c.execute('SELECT name FROM ' + db + ".sqlite_master WHERE type='table'")}


def _rows(c, db, table):
    if table not in _tables(c, db):
        return []
    return [dict(row) for row in c.execute('SELECT * FROM ' + db + '."' + table.replace('"', '""') + '"')]


def _stable_rows(rows):
    return sorted(rows, key=_dump)


@contextmanager
def _connection(data_dir, write=False):
    directory = _folder(data_dir)
    paths = [_regular(directory / name) for name in ('repairs.db', 'payments.db')]
    c = sqlite3.connect(str(paths[0]) if write else paths[0].as_uri() + '?mode=ro',
                        uri=not write, isolation_level=None, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        c.execute('ATTACH DATABASE ? AS pay', (str(paths[1]) if write else paths[1].as_uri() + '?mode=ro',))
        c.execute('PRAGMA foreign_keys=ON')
        for db in ('main', 'pay'):
            _need(c.execute('PRAGMA ' + db + '.quick_check').fetchone()[0] == 'ok', 'database_integrity_failed')
            _need(not c.execute('SELECT 1 FROM ' + db + ".sqlite_master WHERE type='trigger' LIMIT 1").fetchone(), 'unexpected_database_trigger')
            if write:
                # A super-journal makes the attached on-disk DB commit atomic.
                # WAL/OFF/MEMORY do not offer that guarantee; never downgrade
                # a live journal setting silently to make cleanup proceed.
                _need(c.execute('PRAGMA ' + db + '.journal_mode').fetchone()[0] in ('delete', 'persist', 'truncate'), 'rollback_journal_required')
                c.execute('PRAGMA ' + db + '.synchronous=FULL')
        _need('cases' in _tables(c, 'main') and
              {'wb_cases', 'wb_quotes', 'wb_prod_links', 'wb_prod_settings'} <= _tables(c, 'pay'), 'database_schema_invalid')
        c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield c
    finally:
        if c.in_transaction:
            c.rollback()
        c.close()


def _payment_graph(c, case_ids):
    case_ids = set(case_ids)
    links, all_cases = _rows(c, 'pay', 'wb_prod_links'), _rows(c, 'pay', 'wb_cases')
    selected_links = [row for row in links if row['real_id'] in case_ids]
    wb_ids = {row['wb_id'] for row in selected_links}
    for row in all_cases:
        data = _json(row['data'])
        _need(type(data) is dict, 'payment_case_data_invalid')
        if data.get('caseNumber') in case_ids:
            wb_ids.add(row['id'])
    for link in links:
        _need(link['wb_id'] not in wb_ids or link['real_id'] in case_ids, 'payment_cross_scope_reference')
    for row in all_cases:
        if row['id'] in wb_ids:
            _need(_json(row['data']).get('caseNumber') in case_ids, 'payment_cross_scope_reference')
    graph = {'wb_prod_links': selected_links,
             'wb_cases': [row for row in all_cases if row['id'] in wb_ids]}
    graph['wb_quotes'] = [row for row in _rows(c, 'pay', 'wb_quotes') if row['case_id'] in wb_ids]
    quotes = {row['id'] for row in graph['wb_quotes']}
    for table in ('wb_orders', 'wb_real_order_checks', 'wb_real_manual_approvals', 'wb_refund_followups'):
        selected = []
        for row in _rows(c, 'pay', table):
            belongs = row['case_id'] in wb_ids or row['quote_id'] in quotes or row.get('bound_quote_id', '') in quotes
            if belongs:
                _need(row['case_id'] in wb_ids and row['quote_id'] in quotes
                      and (not row.get('bound_quote_id') or row['bound_quote_id'] in quotes), 'payment_cross_scope_reference')
                selected.append(row)
        graph[table] = selected
    for table in ('wb_audit', 'wb_payment_sheet_state', 'wb_payment_sheet_outbox'):
        graph[table] = [row for row in _rows(c, 'pay', table) if row['case_id'] in wb_ids]
    for table in ('wb_notifications', 'wb_prod_messages'):
        graph[table] = [row for row in _rows(c, 'pay', table) if row['quote_id'] in quotes]
    orders = {row['id'] for row in graph['wb_orders']}
    owned_ids = wb_ids | quotes | orders
    operations = ({'approve_quote:' + ident for ident in wb_ids}
        | {prefix + ident for prefix in ('notify:', 'simulate:') for ident in quotes}
        | {'bind:' + ident for ident in orders})
    graph['wb_requests'] = []
    for row in _rows(c, 'pay', 'wb_requests'):
        if row['result_id'] in owned_ids or row['operation'] in operations:
            _need(row['result_id'] in owned_ids, 'payment_request_cross_scope_reference')
            graph['wb_requests'].append(row)
    # A newly introduced case-bound table must be explicitly reviewed before
    # a cleanup can claim it removed the complete target graph.
    for table in _tables(c, 'pay') - set(PAYMENT_DELETE_ORDER) - {'wb_prod_settings', 'sqlite_sequence', 'wb_intake_sequence'}:
        for row in _rows(c, 'pay', table):
            _need(row.get('case_id') not in wb_ids and row.get('quote_id') not in quotes, 'unreviewed_case_bound_table')
    return {name: _stable_rows(rows) for name, rows in graph.items()}


def _repair_graph(c, case_ids):
    ids = set(case_ids)
    graph = {'cases': [row for row in _rows(c, 'main', 'cases') if row['id'] in ids]}
    for table in REPAIR_CHILDREN:
        graph[table] = [row for row in _rows(c, 'main', table) if row['case_id'] in ids]
    reviewed = set(REPAIR_CHILDREN) | set(PROTECTED_REPAIR) | {'cases', 'case_number_sequences',
        'deleted_case_requests', 'dispatch_daily_jobs', 'dispatch_query_events',
        'dispatch_query_snapshots', 'dispatch_workflow_push', 'test_case_cleanup_runs'}
    for table in _tables(c, 'main') - reviewed:
        for row in _rows(c, 'main', table):
            _need(row.get('case_id') not in ids, 'unreviewed_case_bound_table')
    return {name: _stable_rows(rows) for name, rows in graph.items()}


def _graphs(c, ids):
    return {'repairs.db': _repair_graph(c, ids), 'payments.db': _payment_graph(c, ids)}


def _protected(c):
    return {'repairs.db': {table: _stable_rows(_rows(c, 'main', table)) for table in PROTECTED_REPAIR},
            'payments.db': {table: _stable_rows(_rows(c, 'pay', table)) for table in ('wb_prod_settings', 'sqlite_sequence', 'wb_intake_sequence')}}


def _has_target(value):
    if type(value) is str:
        return bool(set(CASE_IN_TEXT.findall(value)) & set(APPROVED_IDS))
    if type(value) is list:
        return any(_has_target(item) for item in value)
    if type(value) is dict:
        return any(_has_target(item) for item in value.values())
    return False


def _cache_plan(c):
    snapshots = [row['id'] for row in _rows(c, 'main', 'dispatch_query_snapshots') if _has_target(_json(row['case_ids']))]
    job_keys = {row['job_key'] for row in _rows(c, 'main', 'dispatch_workflow_push')
                if _has_target(_json(row['case_ids'])) or _has_target(_json(row['messages']))}
    events = []
    for row in _rows(c, 'main', 'dispatch_query_events'):
        args = _json(row['args'])
        if _has_target(args) or type(args) is dict and args.get('snapshot') in snapshots:
            events.append(row['event_id'])
    return {'snapshots': snapshots, 'job_keys': sorted(job_keys), 'events': events}


def _plan(c):
    rows = _rows(c, 'main', 'cases')
    ids = {row['id'] for row in rows}
    _need(KEEP in ids, 'retained_case_missing')
    target = _graphs(c, APPROVED_IDS)
    keep_hash = _hash(_graphs(c, {KEEP}))
    cache = _cache_plan(c)
    identity = {'schema': SCHEMA, 'keepCaseId': KEEP, 'keepGraphHash': keep_hash,
        'approvedCaseIds': list(APPROVED_IDS), 'targetCases': target['repairs.db']['cases'],
        'targetMappings': target['payments.db']['wb_prod_links'],
        'targetPaymentCaseIds': sorted(row['id'] for row in target['payments.db']['wb_cases'])}
    report = {'schema': SCHEMA, 'state': 'dry_run', 'keepCaseId': KEEP,
        'approvedCaseIds': list(APPROVED_IDS), 'existingTargetCaseIds': sorted(ids & set(APPROVED_IDS)),
        'keepGraphHash': keep_hash, 'planHash': _hash(identity),
        'deleteCounts': {db: {table: len(values) for table, values in graph.items()} for db, graph in target.items()},
        'cacheActions': {'snapshotDeletes': len(cache['snapshots']), 'pushJobsRedacted': len(cache['job_keys']),
                         'queryEventsRedacted': len(cache['events'])},
        'unapprovedCaseCountPreserved': len(ids - set(APPROVED_IDS) - {KEEP}),
        'sharedEphemeralCachesExcludedFromKeepGraph': True,
        'networkRequests': 0}
    return report, target, cache


def dry_run(data_dir):
    """Only read the two local databases; no backup, marker or DB writes."""
    with _connection(data_dir) as c:
        return _plan(c)[0]


def _approval(value):
    fields = {'schema', 'operation', 'keepCaseId', 'approvedCaseIds', 'keepGraphHash', 'planHash', 'approvalId'}
    _need(type(value) is dict and set(value) == fields and value.get('schema') == SCHEMA
        and value.get('operation') == 'apply' and value.get('keepCaseId') == KEEP, 'approval_invalid')
    ids = value['approvedCaseIds']
    _need(type(ids) is list and all(type(ident) is str for ident in ids)
        and len(ids) == len(APPROVED_IDS) and len(set(ids)) == len(ids)
        and set(ids) == set(APPROVED_IDS), 'approval_case_scope_invalid')
    for key in ('keepGraphHash', 'planHash'):
        _need(type(value[key]) is str and re.fullmatch(r'[0-9a-f]{64}', value[key]), 'approval_hash_invalid')
    try:
        parsed = uuid.UUID(value['approvalId'])
        _need(parsed.version == 4 and str(parsed) == value['approvalId'], 'approval_id_invalid')
    except (ValueError, TypeError, AttributeError):
        raise CleanupError('approval_id_invalid') from None
    return {**value, 'approvedCaseIds': list(APPROVED_IDS)}


def _file_hash(path):
    digest = hashlib.sha256()
    with _regular(path).open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _backup(directory, approval, report):
    root = directory / 'operator-backups'
    _need(not root.is_symlink(), 'backup_scope_invalid')
    root.mkdir(exist_ok=True, mode=0o700)
    destination = root / ('test-case-cleanup-' + approval['approvalId'])
    _need(not destination.exists(), 'backup_already_exists_review_required')
    destination.mkdir(mode=0o700)
    files = {}
    for name in ('repairs.db', 'payments.db'):
        target = destination / name
        with closing(sqlite3.connect((directory / name).as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(target)) as backup:
                source.backup(backup)
                _need(backup.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'backup_integrity_failed')
        os.chmod(target, 0o600)
        with target.open('r+b') as file:
            os.fsync(file.fileno())
        files[name] = {'sha256': _file_hash(target), 'quickCheck': 'ok'}
    manifest = {'schema': SCHEMA, 'approvalId': approval['approvalId'], 'state': 'prepared',
        'createdAt': _now(), 'files': files, 'plan': report,
        'restore': 'Stop all app processes, then call restore_backup(data_dir, manifest_path). Never restore one database alone.'}
    _atomic_json(destination / 'manifest.json', manifest)
    return destination, manifest


def _seed_and_tombstone(c, target_rows):
    c.execute('''CREATE TABLE IF NOT EXISTS deleted_case_requests (
        user_id TEXT NOT NULL,request_id TEXT NOT NULL,case_id TEXT NOT NULL,deleted_at TEXT NOT NULL,
        PRIMARY KEY(user_id,request_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS case_number_sequences (
        day TEXT PRIMARY KEY,last_number INTEGER NOT NULL CHECK(typeof(last_number)='integer' AND last_number>=0))''')
    for row in target_rows:
        old = c.execute('SELECT case_id FROM deleted_case_requests WHERE user_id=? AND request_id=?',
                        (row['user_id'], row['request_id'])).fetchone()
        _need(not old or old['case_id'] == row['id'], 'tombstone_identity_conflict')
        c.execute('INSERT OR IGNORE INTO deleted_case_requests VALUES(?,?,?,?)',
                  (row['user_id'], row['request_id'], row['id'], _now()))
    maxima = {}
    for row in c.execute('SELECT id FROM cases UNION ALL SELECT case_id AS id FROM deleted_case_requests'):
        match = CASE.fullmatch(row['id'])
        if match:
            maxima[match[1]] = max(maxima.get(match[1], 0), int(match[2]))
    for day, number in maxima.items():
        c.execute('''INSERT INTO case_number_sequences VALUES(?,?) ON CONFLICT(day)
            DO UPDATE SET last_number=excluded.last_number WHERE excluded.last_number>case_number_sequences.last_number''', (day, number))


def _clear_caches(c, cache):
    for ident in cache['snapshots']:
        c.execute('DELETE FROM dispatch_query_snapshots WHERE id=?', (ident,))
    for ident in cache['events']:
        c.execute("""UPDATE dispatch_query_events SET args='{}',reply_token='',
            state=CASE WHEN state IN ('pending','working','responding','failed') THEN 'cancelled' ELSE state END,
            last_error='test_case_cleaned' WHERE event_id=?""", (ident,))
    for key in cache['job_keys']:
        c.execute("""UPDATE dispatch_workflow_push SET messages='[]',case_ids='[]',
            state=CASE WHEN state IN ('pending','working','failed','needs_review') THEN 'cancelled' ELSE state END,
            last_error='test_case_cleaned' WHERE job_key=?""", (key,))
        c.execute("""UPDATE dispatch_daily_jobs SET state='cancelled',last_error='test_case_cleaned'
            WHERE job_key=? AND state IN ('pending','working','ready','failed')""", (key,))


def _mutate(c, target, cache):
    _seed_and_tombstone(c, target['repairs.db']['cases'])
    for table in PAYMENT_DELETE_ORDER:
        key = PAYMENT_KEYS[table]
        for row in target['payments.db'][table]:
            c.execute('DELETE FROM pay.' + table + ' WHERE ' + key + '=?', (row[key],))
    _clear_caches(c, cache)
    for table in REPAIR_CHILDREN:
        if table in _tables(c, 'main'):
            for number in APPROVED_IDS:
                c.execute('DELETE FROM ' + table + ' WHERE case_id=?', (number,))
    for number in APPROVED_IDS:
        c.execute('DELETE FROM cases WHERE id=?', (number,))


def _ledger(c):
    if 'test_case_cleanup_runs' not in _tables(c, 'main'):
        return None
    rows = list(c.execute('SELECT * FROM test_case_cleanup_runs'))
    _need(len(rows) <= 1, 'cleanup_ledger_invalid')
    return dict(rows[0]) if rows else None


def _completed(c, approval):
    prior = _ledger(c)
    if not prior:
        return None
    _need(prior['approval_hash'] == _hash(approval), 'cleanup_already_completed_with_other_approval')
    report = _json(prior['report'])
    _need(type(report) is dict and report.get('state') == 'completed', 'cleanup_ledger_invalid')
    return {**report, 'alreadyCompleted': True}


def apply_cleanup(data_dir, approval):
    """Offline only: consistent backups, exact scope, atomic two-DB cleanup."""
    directory, approval = _folder(data_dir), _approval(approval)
    _need(not (directory / RECOVERY_FILENAME).exists(), 'cleanup_restore_required')
    lock_path = directory / LOCK_FILENAME
    try:
        lock = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise CleanupError('cleanup_lock_requires_operator_review') from None
    os.close(lock)
    try:
        with _connection(directory, write=True) as c:
            prior = _completed(c, approval)
            if prior:
                c.rollback()
                _atomic_json(directory / COMPLETED_FILENAME, prior)
                return prior
            _need(not (directory / COMPLETED_FILENAME).exists(), 'completion_marker_without_ledger')
            report, target, cache = _plan(c)
            _need(report['keepGraphHash'] == approval['keepGraphHash'], 'retained_graph_changed')
            _need(report['planHash'] == approval['planHash'], 'reviewed_plan_changed')
            original_ids = {row['id'] for row in _rows(c, 'main', 'cases')}
            preserved_ids = original_ids - set(APPROVED_IDS)
            preserve_hash, protected_hash = _hash(_graphs(c, preserved_ids)), _hash(_protected(c))
            old_tombstones = _rows(c, 'main', 'deleted_case_requests')
            old_sequences = {r['day']: r['last_number'] for r in _rows(c, 'main', 'case_number_sequences')}
            archive, manifest = _backup(directory, approval, report)
            _mutate(c, target, cache)
            _need(_hash(_graphs(c, {KEEP})) == approval['keepGraphHash'], 'retained_graph_changed')
            _need(_hash(_graphs(c, preserved_ids)) == preserve_hash and _hash(_protected(c)) == protected_hash,
                  'unapproved_records_changed')
            _need(not any(_graphs(c, APPROVED_IDS)[db][table] for db in target for table in target[db]), 'target_rows_remain')
            _need(_cache_plan(c) == {'snapshots': [], 'job_keys': [], 'events': []}, 'target_cache_payload_remains')
            for old in old_tombstones:
                new = c.execute('SELECT * FROM deleted_case_requests WHERE user_id=? AND request_id=?',
                                (old['user_id'], old['request_id'])).fetchone()
                _need(new and dict(new) == old, 'existing_tombstone_changed')
            for day, number in old_sequences.items():
                _need(c.execute('SELECT last_number FROM case_number_sequences WHERE day=?', (day,)).fetchone()[0] >= number,
                      'case_sequence_decreased')
            for db in ('main', 'pay'):
                _need(c.execute('PRAGMA ' + db + '.quick_check').fetchone()[0] == 'ok'
                    and not c.execute('PRAGMA ' + db + '.foreign_key_check').fetchone(), 'post_cleanup_integrity_failed')
            result = {**report, 'state': 'completed', 'completedAt': _now(), 'approvalId': approval['approvalId'],
                'backupId': archive.name, 'keepGraphUnchanged': True, 'unapprovedGraphsUnchanged': True,
                'settingsAndGlobalDeduplicationUnchanged': True, 'alreadyCompleted': False}
            c.execute('''CREATE TABLE test_case_cleanup_runs (
                approval_id TEXT PRIMARY KEY,approval_hash TEXT NOT NULL,report TEXT NOT NULL)''')
            c.execute('INSERT INTO test_case_cleanup_runs VALUES(?,?,?)', (approval['approvalId'], _hash(approval), _dump(result)))
            c.commit()
            manifest.update(state='completed', completedAt=result['completedAt'])
            _atomic_json(archive / 'manifest.json', manifest)
            _atomic_json(directory / COMPLETED_FILENAME, result)
            return result
    except CleanupError:
        raise
    except Exception:
        raise CleanupError('offline_cleanup_failed_startup_stopped') from None
    finally:
        lock_path.unlink()


def run_on_start(data_dir):
    """No marker = no DB access; failures must propagate and prevent startup."""
    candidate = Path(data_dir)
    if candidate.is_absolute() and not candidate.exists():
        _need(not candidate.is_symlink() and
            os.path.normcase(os.path.abspath(candidate)) == os.path.normcase(str(candidate.resolve())),
            'data_directory_invalid')
        # Existing startup creates a fresh data directory later. An absent
        # directory cannot contain an approval; do not create or inspect a DB.
        return {'state': 'not_requested'}
    directory = _folder(data_dir)
    _need(not (directory / RECOVERY_FILENAME).exists(), 'cleanup_restore_required')
    marker = directory / APPROVAL_FILENAME
    if not marker.exists():
        _need(not marker.is_symlink(), 'file_scope_invalid')
        return {'state': 'not_requested'}
    return apply_cleanup(directory, _read_json(marker))


def restore_backup(data_dir, manifest_path):
    """Explicit offline restoration of BOTH DBs. A crash blocks app startup."""
    directory = _folder(data_dir)
    path = Path(manifest_path)
    expected_root = directory / 'operator-backups'
    _need(path.name == 'manifest.json' and path.is_absolute() and
        path.parent.parent == expected_root and not expected_root.is_symlink()
        and not path.parent.is_symlink() and path.resolve().parent == path.parent,
        'restore_scope_invalid')
    manifest = _read_json(path)
    _need(type(manifest) is dict and manifest.get('schema') == SCHEMA
        and set(manifest.get('files', {})) == {'repairs.db', 'payments.db'}, 'restore_manifest_invalid')
    for name, facts in manifest['files'].items():
        backup = path.parent / name
        _need(_file_hash(backup) == facts.get('sha256'), 'restore_backup_hash_invalid')
        with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as c:
            _need(c.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'restore_backup_integrity_failed')
    _atomic_json(directory / RECOVERY_FILENAME, {'schema': SCHEMA, 'state': 'restoring_both_databases'})
    try:
        for name in ('repairs.db', 'payments.db'):
            _regular(directory / name)
            _need(not (directory / (name + '-wal')).exists() and not (directory / (name + '-journal')).exists(), 'restore_sidecar_requires_review')
            temporary = directory / ('.cleanup-restore-' + name)
            _need(not temporary.exists() and not temporary.is_symlink(), 'restore_temporary_exists')
            shutil.copyfile(path.parent / name, temporary)
            os.chmod(temporary, 0o600)
            with temporary.open('r+b') as file:
                os.fsync(file.fileno())
            os.replace(temporary, directory / name)
            _fsync_directory(directory)
        approval = directory / APPROVAL_FILENAME
        if approval.exists():
            os.replace(_regular(approval), directory / (APPROVAL_FILENAME + '.restored-' + str(uuid.uuid4())))
        completed = directory / COMPLETED_FILENAME
        if completed.exists():
            _regular(completed).unlink()
        (directory / RECOVERY_FILENAME).unlink()
        return {'schema': SCHEMA, 'state': 'both_databases_restored', 'approvalDisabled': True, 'networkRequests': 0}
    except Exception:
        # Keep the recovery barrier until the operator restores both files.
        raise CleanupError('restore_incomplete_startup_blocked') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline exact-scope repair test cleanup; default preview only')
    parser.add_argument('--data-dir', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run', action='store_true')
    modes.add_argument('--apply-marker', action='store_true')
    modes.add_argument('--restore-manifest', type=Path)
    args = parser.parse_args(argv)
    try:
        result = (restore_backup(args.data_dir, args.restore_manifest) if args.restore_manifest else
                  run_on_start(args.data_dir) if args.apply_marker else dry_run(args.data_dir))
        print(_dump(result))
        return 0
    except CleanupError as error:
        print(_dump({'schema': SCHEMA, 'state': 'blocked', 'error': error.code, 'networkRequests': 0}))
        return 2
    except Exception:
        print(_dump({'schema': SCHEMA, 'state': 'blocked', 'error': 'offline_cleanup_failed_startup_stopped', 'networkRequests': 0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
