"""Explicitly scoped production payment export through the existing GAS app.

This adapter leaves repair/pickup sync and the test-only sheet worker unchanged.
It exports only enrolled WB mappings to the pinned formal workbook's separate
payment tab. The core owns durable versions, pending records, and acknowledgments.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import uuid

from cloud_support import GoogleContentRedirect
from payment_sheet_transport import validate_payment


PRIMARY_SHEET_ID = '1C5gGI4cL4lgw-GqSXRcQuicM2e5FvDHp-bnfqpMcnqI'
SCHEMA = 'petpivot-payment-production-v1'
TAB_NAME = '付款狀態'
_ACK_FIELDS = {'ok', 'schema', 'sheetId', 'spreadsheetId', 'gid', 'caseId',
               'revision', 'status', 'action', 'payloadHash'}
_OWNERS, _OWNERS_LOCK = {}, threading.Lock()


def _case_id(value):
    try:
        if type(value) is not str or not value.startswith('WB-'):
            return False
        parsed = uuid.UUID(value[3:])
        return parsed.version == 4 and str(parsed) == value[3:]
    except (ValueError, TypeError, AttributeError):
        return False


def _settings(value):
    if type(value) is not dict:
        raise ValueError('正式付款同步設定未完成')
    endpoint, secret, sheet = (value.get(key) for key in
        ('googleSheetEndpoint', 'googleSheetSecret', 'googleSheetId'))
    parsed = urlsplit(endpoint) if type(endpoint) is str else None
    if (sheet != PRIMARY_SHEET_ID or parsed is None or parsed.scheme != 'https'
            or parsed.netloc != 'script.google.com' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/macros/s/[A-Za-z0-9_-]{20,300}/exec', parsed.path)
            or type(secret) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', secret)):
        raise ValueError('正式付款同步只允許既有正式工作簿及有效部署設定')
    return endpoint, secret, sheet


def payload_hash(record):
    # validate_payment returns the fixed 12-field canonical order used by GAS.
    canonical = validate_payment(record)
    body = json.dumps(canonical, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('invalid_ack')
        result[key] = value
    return result


def _valid_ack(ack, record):
    return (type(ack) is dict and set(ack) == _ACK_FIELDS and ack.get('ok') is True
        and ack.get('schema') == SCHEMA and ack.get('sheetId') == PRIMARY_SHEET_ID
        and ack.get('spreadsheetId') == PRIMARY_SHEET_ID
        and type(ack.get('gid')) is int and ack['gid'] >= 0
        and ack.get('caseId') == record['caseId']
        and type(ack.get('revision')) is int and ack['revision'] == record['revision']
        and ack.get('status') == record['status']
        and ack.get('action') in ('inserted', 'updated', 'unchanged')
        and type(ack.get('payloadHash')) is str
        and re.fullmatch(r'[0-9a-f]{64}', ack['payloadHash']) is not None
        and secrets.compare_digest(ack['payloadHash'], payload_hash(record)))


def send_production_payment(settings, record, *, opener=None):
    """No dynamic destinations, arbitrary ranges, browser status, or raw errors."""
    try:
        endpoint, secret, sheet_id = _settings(settings)
        payment = validate_payment(record)
        body = json.dumps({'secret': secret, 'sheetId': sheet_id, 'schema': SCHEMA,
            'operation': 'upsertPayment', 'payment': payment}, ensure_ascii=False,
            allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(body) > 32768:
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        return {'state': 'failed', 'code': 'invalid_settings'}
    request = urllib.request.Request(endpoint, data=body, method='POST',
        headers={'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'})
    try:
        transport = opener if opener is not None else urllib.request.build_opener(GoogleContentRedirect())
        with transport.open(request, timeout=25) as response:
            raw = response.read(8193)
            if response.status != 200 or len(raw) > 8192:
                raise ValueError()
            ack = json.loads(raw, object_pairs_hook=_unique,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        if not _valid_ack(ack, payment):
            return {'state': 'failed', 'code': 'invalid_ack'}
        return {'state': 'synced', 'ack': ack}
    except urllib.error.HTTPError as error:
        return {'state': 'failed', 'code': 'unauthorized' if error.code in (401, 403) else 'unavailable'}
    except Exception:
        return {'state': 'failed', 'code': 'unavailable'}


class ProductionPaymentSheet:
    def __init__(self, sync, config_getter, allowed_case_ids, *, opener=None,
                 interval_seconds=5, monotonic=time.monotonic):
        if (not callable(config_getter) or not callable(allowed_case_ids) or not callable(monotonic)
                or type(interval_seconds) is not int or not 1 <= interval_seconds <= 60
                or any(not callable(getattr(sync, name, None)) for name in ('enqueue', 'pending', 'ack', 'mark_failed'))):
            raise ValueError('正式付款同步服務設定不正確')
        self.sync, self.config_getter, self.allowed_case_ids = sync, config_getter, allowed_case_ids
        self.opener, self.interval, self.clock = opener, interval_seconds, monotonic
        self._stop, self._wake = threading.Event(), threading.Event()
        self._run_lock, self._status_lock = threading.Lock(), threading.Lock()
        self._thread, self._retry = None, {}
        self._state = {'lastError': '', 'lastSuccessAt': '', 'deliveredCount': 0, 'failedCount': 0, 'gid': None}

    def _scope(self):
        values = self.allowed_case_ids()
        if (not isinstance(values, (set, frozenset, list, tuple)) or len(values) > 100000
                or any(not _case_id(value) for value in values)):
            raise ValueError('正式付款同步必須使用伺服器已登錄的案件對照名單')
        return frozenset(values)

    def enqueue(self, case_id):
        if case_id not in self._scope():
            return {'queued': False, 'reason': 'not_in_payment_scope'}
        result = self.sync.enqueue(case_id)
        self.wake()
        return result

    def status(self):
        try:
            _settings(self.config_getter())
            configured = True
        except Exception:
            configured = False
        with self._status_lock:
            state = dict(self._state)
        running = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        return {'configured': configured, 'running': running,
            'automaticDeliveryEnabled': configured and running, 'environment': 'production',
            'sheetId': PRIMARY_SHEET_ID, 'sheetName': TAB_NAME,
            'sheetUrl': 'https://docs.google.com/spreadsheets/d/' + PRIMARY_SHEET_ID + '/edit' +
                ('#gid=' + str(state['gid']) if state['gid'] is not None else ''), **state}

    def run_once(self):
        with _OWNERS_LOCK:
            if _OWNERS.get(PRIMARY_SHEET_ID) not in (None, self):
                return {'state': 'busy', 'delivered': 0, 'failed': 0}
        if not self._run_lock.acquire(blocking=False):
            return {'state': 'busy', 'delivered': 0, 'failed': 0}
        delivered, failed, skipped = 0, 0, 0
        try:
            try:
                config = self.config_getter()
                _settings(config)
                allowed = self._scope()
            except Exception:
                with self._status_lock:
                    self._state['lastError'] = '正式付款同步設定需確認'
                return {'state': 'not_configured', 'delivered': 0, 'failed': 0}
            for job in self.sync.pending(100).get('rows', []):
                if delivered + failed >= 10:
                    break
                case_id, revision = job.get('caseId'), job.get('revision')
                if case_id not in allowed:
                    skipped += 1
                    continue
                now = self.clock()
                if now < self._retry.get(case_id, 0):
                    continue
                try:
                    refreshed = self.sync.enqueue(case_id)
                    if refreshed.get('queued') is not True:
                        continue
                    record = validate_payment(refreshed['row']['record'])
                    revision = refreshed['revision']
                    if record['revision'] != revision or case_id not in self._scope():
                        raise ValueError()
                    response = send_production_payment(config, record, opener=self.opener)
                    if response.get('state') != 'synced' or not _valid_ack(response.get('ack'), record):
                        raise ValueError()
                    acknowledgement = self.sync.ack(case_id, revision, response['ack'])
                    if acknowledgement.get('acked') is True:
                        delivered += 1
                        self._retry.pop(case_id, None)
                        with self._status_lock:
                            self._state.update(lastError='', lastSuccessAt=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
                                               gid=response['ack']['gid'])
                            self._state['deliveredCount'] += 1
                except Exception:
                    self.sync.mark_failed(case_id, revision)
                    self._retry[case_id] = now + min(3600, 10 * 2 ** min(int(job.get('attempts', 0)), 8))
                    failed += 1
                    with self._status_lock:
                        self._state['lastError'] = '正式付款同步失敗，可重試'
                        self._state['failedCount'] += 1
            return {'state': 'processed', 'delivered': delivered, 'failed': failed, 'skipped': skipped}
        finally:
            self._run_lock.release()

    def wake(self):
        self._wake.set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        with _OWNERS_LOCK:
            if _OWNERS.get(PRIMARY_SHEET_ID) not in (None, self):
                return False
            _OWNERS[PRIMARY_SHEET_ID] = self
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name='production-payment-sheet', daemon=True)
            self._thread.start()
        return True

    def _loop(self):
        try:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception:
                    with self._status_lock:
                        self._state['lastError'] = '正式付款同步失敗，可重試'
                self._wake.wait(self.interval)
                self._wake.clear()
        finally:
            with _OWNERS_LOCK:
                if _OWNERS.get(PRIMARY_SHEET_ID) is self:
                    _OWNERS.pop(PRIMARY_SHEET_ID, None)

    def stop(self, timeout=2):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread or not self._thread.is_alive()
