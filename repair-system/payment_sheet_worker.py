"""Explicitly started delivery of isolated payment projections to one test copy.

Importing this module starts no thread and discovers no configuration. Its only
permitted destination is the private cloud rehearsal workbook. Durable records
and retry counts belong to PaymentSheetSync; this worker owns no business data.
"""
from datetime import datetime, timedelta, timezone
import copy
import math
import re
import threading
import time
import urllib.parse
import uuid

from payment_sheet_transport import SCHEMA, send_payment, validate_payment


INTERNAL_TEST_SHEET_ID = '1hu5VVS3Ark9Iv-SD4JYFuBfEOqkUQrf7yMlUWuWi1R4'
_OWNERS_LOCK = threading.Lock()
_OWNERS = {}
_TAIPEI = timezone(timedelta(hours=8))


def _now():
    return datetime.now(_TAIPEI).isoformat(timespec='seconds')


def _case_id(value):
    if not isinstance(value, str) or not value.startswith('WB-'):
        return False
    try:
        parsed = uuid.UUID(value[3:])
        return parsed.version == 4 and str(parsed) == value[3:]
    except (ValueError, TypeError, AttributeError):
        return False


class PaymentSheetWorker:
    """Opt-in daemon; server hooks only enqueue and optionally call wake().

    Construction validates all settings without I/O. start() is idempotent for
    this instance and refuses a second owner of the test destination. run_once()
    is synchronous for maintenance/tests; HTTP handlers should never call it.
    """
    def __init__(self, sync, *, endpoint, secret, sheet_id, allowed_case_ids,
                 interval_seconds=5, batch_size=10, transport=send_payment,
                 monotonic=time.monotonic):
        parsed = urllib.parse.urlsplit(endpoint) if isinstance(endpoint, str) else None
        if (sheet_id != INTERNAL_TEST_SHEET_ID or parsed is None
                or parsed.scheme != 'https' or parsed.netloc != 'script.google.com'
                or parsed.query or parsed.fragment
                or re.fullmatch(r'/macros/s/[A-Za-z0-9_-]{20,300}/exec', parsed.path) is None
                or not isinstance(secret, str)
                or re.fullmatch(r'[A-Za-z0-9_-]{32,128}', secret) is None):
            raise ValueError('付款自動同步只允許已指定的雲端內測副本與有效設定')
        self._scope_reader = allowed_case_ids if callable(allowed_case_ids) else lambda: allowed_case_ids
        self._scope()
        if (isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float))
                or not math.isfinite(interval_seconds) or not 1 <= interval_seconds <= 60
                or type(batch_size) is not int or not 1 <= batch_size <= 20
                or not callable(transport) or not callable(monotonic)
                or any(not callable(getattr(sync, name, None))
                       for name in ('enqueue', 'pending', 'ack', 'mark_failed'))):
            raise ValueError('付款自動同步背景工作設定不正確')
        self._sync, self._endpoint, self._secret = sync, endpoint, secret
        self._sheet_id = sheet_id
        self._interval, self._batch_size = float(interval_seconds), batch_size
        self._transport, self._monotonic = transport, monotonic
        self._stop, self._wake = threading.Event(), threading.Event()
        self._state_lock, self._run_lock = threading.RLock(), threading.Lock()
        self._thread = None
        self._retry_after = {}
        self._state = {'lastSuccessAt': '', 'lastAttemptAt': '', 'lastError': '',
                       'deliveredCount': 0, 'failedCount': 0, 'skippedCount': 0,
                       'lastResult': 'idle', 'inFlight': False}

    def _scope(self):
        values = self._scope_reader()
        if (not isinstance(values, (set, frozenset, list, tuple))
                or not 1 <= len(values) <= 100 or not all(_case_id(value) for value in values)):
            raise ValueError('付款自動同步必須明確指定內部案件副本')
        return frozenset(values)

    def status(self):
        with self._state_lock:
            running = self._thread is not None and self._thread.is_alive() and not self._stop.is_set()
            return {'configured': True, 'automaticDeliveryEnabled': running,
                    'running': running, 'sheetId': self._sheet_id,
                    'allowedCaseCount': len(self._scope()), 'internalOnly': True,
                    'productionPaymentRecognized': False, 'releaseAllowed': False,
                    **self._state}

    def start(self):
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return not self._stop.is_set()
            with _OWNERS_LOCK:
                if _OWNERS.get(self._sheet_id) not in (None, self):
                    return False
                _OWNERS[self._sheet_id] = self
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(target=self._loop, name='payment-sheet-internal-copy', daemon=True)
            try:
                self._thread.start()
            except Exception:
                with _OWNERS_LOCK:
                    if _OWNERS.get(self._sheet_id) is self:
                        del _OWNERS[self._sheet_id]
                self._thread = None
                raise
            return True

    def stop(self, timeout=2):
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0 <= timeout <= 30):
            raise ValueError('付款同步停止等待時間不正確')
        self._stop.set()
        self._wake.set()
        with self._state_lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def wake(self):
        self._wake.set()

    def _loop(self):
        try:
            while not self._stop.is_set():
                self._wake.clear()
                self.run_once()
                self._wake.wait(self._interval)
        finally:
            with _OWNERS_LOCK:
                if _OWNERS.get(self._sheet_id) is self:
                    del _OWNERS[self._sheet_id]

    @staticmethod
    def _verified_ack(result, record, sheet_id):
        ack = result.get('ack') if isinstance(result, dict) else None
        return (isinstance(result, dict) and result.get('state') == 'synced' and type(ack) is dict
                and set(ack) == {'ok', 'sheetId', 'schema', 'caseId', 'revision', 'status', 'action'}
                and ack.get('ok') is True and ack.get('sheetId') == sheet_id
                and ack.get('schema') == SCHEMA and ack.get('caseId') == record['caseId']
                and type(ack.get('revision')) is int and ack['revision'] == record['revision']
                and ack.get('status') == record['status']
                and ack.get('action') in ('inserted', 'updated', 'unchanged'))

    def _failure(self, case_id, revision, attempts):
        # Provider exceptions can contain credentials or response bodies. Neither
        # diagnostics nor caller text is retained or returned to the browser.
        self._sync.mark_failed(case_id, revision)
        delay = min(300.0, self._interval * (2 ** min(max(attempts, 0) + 1, 8)))
        self._retry_after[case_id] = (revision, self._monotonic() + delay)
        with self._state_lock:
            self._state.update(lastError='同步失敗，可重試', lastResult='failed')
            self._state['failedCount'] += 1

    def run_once(self):
        """Consume a bounded batch; no caller-supplied status or receipt accepted."""
        if not self._run_lock.acquire(blocking=False):
            return {'state': 'busy', 'delivered': 0, 'failed': 0, 'skipped': 0}
        temporary_owner = False
        summary = {'state': 'idle', 'delivered': 0, 'failed': 0, 'skipped': 0}
        try:
            with _OWNERS_LOCK:
                if _OWNERS.get(self._sheet_id) not in (None, self):
                    return {'state': 'busy', 'delivered': 0, 'failed': 0, 'skipped': 0}
                if _OWNERS.get(self._sheet_id) is None:
                    _OWNERS[self._sheet_id] = self
                    temporary_owner = True
            rows = self._sync.pending(limit=100)['rows']
            eligible = 0
            for item in rows:
                if self._stop.is_set():
                    break
                case_id, revision = item.get('caseId'), item.get('revision')
                if case_id not in self._scope():
                    summary['skipped'] += 1
                    continue
                if eligible >= self._batch_size:
                    break
                retry = self._retry_after.get(case_id)
                if retry is not None and retry[0] == revision and self._monotonic() < retry[1]:
                    continue
                eligible += 1
                try:
                    # Refresh from the current server-owned quote/checks so a
                    # stale queued paid projection cannot overwrite a new quote.
                    projection = self._sync.enqueue(case_id)
                    if projection.get('queued') is not True:
                        continue
                    record = validate_payment(projection['row']['record'])
                    revision = projection['revision']
                    if record['revision'] != revision:
                        raise ValueError('invalid_revision')
                    sent_record = copy.deepcopy(record)
                    if case_id not in self._scope():
                        summary['skipped'] += 1
                        continue
                    with self._state_lock:
                        self._state.update(lastAttemptAt=_now(), inFlight=True)
                    result = self._transport(self._endpoint, self._secret, self._sheet_id,
                        sent_record, allowed_sheet_id=self._sheet_id)
                    if not self._verified_ack(result, record, self._sheet_id):
                        raise ValueError('unverified_delivery')
                    acked = self._sync.ack(case_id, revision, result['ack'])
                    if acked.get('acked') is True:
                        summary['delivered'] += 1
                        self._retry_after.pop(case_id, None)
                        with self._state_lock:
                            self._state.update(lastSuccessAt=_now(), lastError='', lastResult='synced')
                            self._state['deliveredCount'] += 1
                    elif acked.get('stale') is not True:
                        raise ValueError('unacknowledged_delivery')
                except Exception:
                    try:
                        self._failure(case_id, revision, item.get('attempts', 0))
                    except Exception:
                        with self._state_lock:
                            self._state.update(lastError='同步失敗，可重試', lastResult='failed')
                    summary['failed'] += 1
                finally:
                    with self._state_lock:
                        self._state['inFlight'] = False
            summary['state'] = 'failed' if summary['failed'] else 'synced' if summary['delivered'] else 'idle'
            with self._state_lock:
                self._state['skippedCount'] += summary['skipped']
            return summary
        except Exception:
            with self._state_lock:
                self._state.update(lastError='同步佇列暫時無法讀取', lastResult='failed', inFlight=False)
            return {**summary, 'state': 'failed'}
        finally:
            if temporary_owner:
                with _OWNERS_LOCK:
                    # A concurrent start may have promoted this instance from a
                    # maintenance cycle to a long-running owner.
                    if (_OWNERS.get(self._sheet_id) is self
                            and not (self._thread is not None and self._thread.is_alive())):
                        del _OWNERS[self._sheet_id]
            self._run_lock.release()
