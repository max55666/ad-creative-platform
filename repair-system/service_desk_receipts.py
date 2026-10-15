"""Durable, opt-in payment confirmations for the isolated customer workbench.

Only authoritative server projections may enroll a confirmation. Provider calls
run outside SQLite locks; retries retain the original LINE retry UUID. Starting
this worker never backfills previously paid cases: the first initialization
records a baseline, which an explicit operator request may enroll once.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import re
import sqlite3
import threading
import time
import uuid


FLAGS = {'internalOnly': True, 'realPayment': False, 'releaseAllowed': False,
         'productionPaymentRecognized': False, 'providerWritesEnabled': False}
RETRY_WINDOW = 24 * 3600
MAX_ATTEMPTS = 10
_ACTIVE = ('pending', 'retry', 'sending')
_RUNNING, _RUNNING_LOCK = {}, threading.Lock()
_TAIPEI = timezone(timedelta(hours=8))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _id(value, prefix):
    try:
        if type(value) is not str or not value.startswith(prefix):
            return False
        parsed = uuid.UUID(value[len(prefix):])
        return parsed.version == 4 and str(parsed) == value[len(prefix):]
    except (ValueError, AttributeError):
        return False


def _text(value, maximum):
    return (type(value) is str and 1 <= len(value) <= maximum and value.strip()
            and not any(ord(ch) < 32 or ord(ch) == 127 or 0xD800 <= ord(ch) <= 0xDFFF for ch in value))


def _stamp(value):
    return datetime.fromtimestamp(value, _TAIPEI).isoformat(timespec='seconds') if value else ''


class ServiceDeskReceipts:
    def __init__(self, connection_factory, *, quote_reader, payment_reader, sender,
                 allowed_case_ids, enabled=False, clock=time.time, interval_seconds=5):
        if (not callable(connection_factory) or not callable(quote_reader) or not callable(payment_reader)
                or not callable(getattr(sender, 'send_receipt', None)) or not callable(clock)
                or type(enabled) is not bool or type(interval_seconds) is not int
                or not 1 <= interval_seconds <= 60):
            raise ValueError('內測付款確認通知的服務設定不正確')
        self.factory, self.quote_reader, self.payment_reader = connection_factory, quote_reader, payment_reader
        self.sender, self.scope_reader = sender, allowed_case_ids if callable(allowed_case_ids) else lambda: allowed_case_ids
        self.enabled, self.clock, self.interval = enabled, clock, interval_seconds
        self._scope()
        self._cycle = threading.Lock()
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread, self._db_key, self._last_error = None, None, ''

    def _scope(self):
        values = self.scope_reader()
        if (not isinstance(values, (set, frozenset, list, tuple)) or not 1 <= len(values) <= 100
                or any(not _id(value, 'WB-') for value in values)):
            raise ValueError('付款確認通知必須使用有限的內測案件名單')
        return frozenset(values)

    @contextmanager
    def _db(self, write=False):
        with self.factory() as c:
            if not isinstance(c, sqlite3.Connection):
                raise ValueError('付款確認通知資料庫連線不正確')
            c.row_factory = sqlite3.Row
            for row in c.execute('PRAGMA database_list'):
                if row['name'] not in ('main', 'temp'):
                    raise ValueError('付款確認通知不得連接外部資料庫')
                if row['file']:
                    absolute, resolved = os.path.abspath(row['file']), os.path.realpath(row['file'])
                    if (os.path.normcase(absolute) != os.path.normcase(resolved)
                            or os.path.basename(resolved).lower() in ('repairs.db', 'payment-lab.db')
                            or os.stat(resolved).st_nlink > 1):
                        raise ValueError('付款確認通知必須使用獨立客服資料庫')
            with c:
                if write and not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                tables = {row['name'] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if not {'wb_cases', 'wb_quotes'} <= tables or any(not name.startswith('wb_') for name in tables):
                    raise ValueError('付款確認通知不得使用正式或其他業務資料庫')
                yield c

    def _current(self, case_id):
        if not _id(case_id, 'WB-') or case_id not in self._scope():
            return None, 'not_allowed'
        wrapper, projection = self.quote_reader(case_id), self.payment_reader(case_id)
        if type(wrapper) is not dict or type(projection) is not dict:
            return None, 'not_paid'
        case, quote = wrapper.get('case'), wrapper.get('quote')
        if type(case) is not dict or type(quote) is not dict:
            return None, 'not_paid'
        for part in (wrapper, case, quote):
            if any(part.get(key) is not val for key, val in (('internalOnly', True), ('simulation', True),
                                                          ('realPayment', False), ('releaseAllowed', False))):
                return None, 'invalid_payment_proof'
        total, version, order = quote.get('total'), quote.get('version'), projection.get('paymentOrderNumber')
        if (case.get('id') != case_id or case.get('source') not in ('snapshot', 'test_intake')
                or not _id(quote.get('id'), 'WQ-') or quote.get('caseId') != case_id
                or quote.get('status') != 'active' or quote.get('paymentStatus') != 'awaiting_payment'
                or quote.get('acceptedOrderId') or type(case.get('latestQuote')) is not dict
                or case['latestQuote'].get('id') != quote['id']
                or type(version) is not int or not 1 <= version <= 1000000 or case.get('version') != version
                or type(total) is not int or not 1 <= total <= 100350 or quote.get('currency') != 'TWD'
                or not _text(case.get('name'), 100) or case.get('name') != quote.get('name')
                or type(case.get('caseNumber')) is not str or not re.fullmatch(r'R[0-9]{8}-[0-9]{4,8}', case['caseNumber'])
                or case['caseNumber'] != quote.get('caseNumber')
                or projection.get('caseId') != case_id or projection.get('caseNumber') != case['caseNumber']
                or projection.get('name') != case['name'] or type(projection.get('quoteVersion')) is not int
                or projection['quoteVersion'] != version or projection.get('paymentStatus') != '已付款'
                or projection.get('source') not in ('shopline_api_completed', 'shopline_api_manual_completed')
                or type(projection.get('amountDue')) is not int or projection['amountDue'] != total
                or type(projection.get('amountPaid')) is not int or projection['amountPaid'] != total
                or type(order) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', order) is None):
            return None, 'not_paid'
        paid_at = projection.get('paidAt', '')
        if type(paid_at) is not str or len(paid_at) > 64 or any(ord(ch) < 32 for ch in paid_at):
            return None, 'invalid_payment_proof'
        return {'id': quote['id'], 'caseId': case_id, 'caseNumber': case['caseNumber'],
            'name': case['name'], 'version': version, 'total': total, 'currency': 'TWD',
            'orderNumber': order, 'paidAt': paid_at, 'source': projection['source'],
            'internalOnly': True, 'simulation': True, 'realPayment': False, 'releaseAllowed': False}, ''

    def init(self):
        with self._db(True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS wb_receipt_outbox (
                id TEXT PRIMARY KEY,case_id TEXT NOT NULL,quote_id TEXT NOT NULL,
                quote_version INTEGER NOT NULL,order_number TEXT NOT NULL UNIQUE,
                request_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,first_attempt REAL NOT NULL DEFAULT 0,
                last_attempt REAL NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',recipient_label TEXT NOT NULL DEFAULT '',
                accepted_at REAL NOT NULL DEFAULT 0,created_at REAL NOT NULL,updated_at REAL NOT NULL,
                UNIQUE(case_id,quote_id,order_number))''')
            c.execute('CREATE TABLE IF NOT EXISTS wb_receipt_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            row = c.execute("SELECT file FROM pragma_database_list WHERE name='main'").fetchone()
            self._db_key = os.path.normcase(os.path.realpath(row['file'])) if row and row['file'] else id(self.factory)
            baseline = c.execute("SELECT 1 FROM wb_receipt_meta WHERE key='baseline_initialized'").fetchone()
        if not baseline:
            rows = self.payment_reader(None)
            if type(rows) is not list or len(rows) > 1000:
                raise ValueError('無法確認內測既有付款基準，未啟用付款確認通知')
            allowed, receipts = self._scope(), []
            for row in rows:
                if type(row) is dict and row.get('caseId') in allowed and row.get('paymentStatus') == '已付款':
                    receipt, reason = self._current(row['caseId'])
                    if receipt is None:
                        raise ValueError('內測既有付款證據不完整，未啟用付款確認通知')
                    receipts.append(receipt)
            with self._db(True) as c:
                if not c.execute("SELECT 1 FROM wb_receipt_meta WHERE key='baseline_initialized'").fetchone():
                    for receipt in receipts:
                        self._insert(c, receipt, 'baseline_skipped', self.clock())
                    c.execute("INSERT INTO wb_receipt_meta VALUES('baseline_initialized','1')")
        return self.status()

    @staticmethod
    def _insert(c, receipt, status, now):
        c.execute('''INSERT OR IGNORE INTO wb_receipt_outbox(id,case_id,quote_id,quote_version,
            order_number,request_id,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            ('WR-' + str(uuid.uuid4()), receipt['caseId'], receipt['id'], receipt['version'],
             receipt['orderNumber'], str(uuid.uuid4()), _json(receipt), status, now, now))

    def enqueue(self, case_id, force=False):
        if type(force) is not bool or not _id(case_id, 'WB-'):
            raise ValueError('付款確認通知案件或選項不正確')
        base = {**FLAGS, 'caseId': case_id, 'queued': False}
        if not self.enabled:
            return {**base, 'code': 'disabled'}
        try:
            receipt, reason = self._current(case_id)
        except Exception:
            return {**base, 'code': 'current_payment_unavailable'}
        with self._db(True) as c:
            if receipt is None:
                c.execute("UPDATE wb_receipt_outbox SET status='cancelled',last_error=?,updated_at=? WHERE case_id=? AND status IN ('pending','retry','sending')",
                          (reason, self.clock(), case_id))
                return {**base, 'code': reason}
            base.update(quoteId=receipt['id'], orderNumber=receipt['orderNumber'])
            c.execute("UPDATE wb_receipt_outbox SET status='cancelled',last_error='superseded_payment',updated_at=? WHERE case_id=? AND (quote_id<>? OR order_number<>?) AND status IN ('pending','retry','sending')",
                      (self.clock(), case_id, receipt['id'], receipt['orderNumber']))
            self._insert(c, receipt, 'pending', self.clock())
            row = c.execute('SELECT * FROM wb_receipt_outbox WHERE order_number=?', (receipt['orderNumber'],)).fetchone()
            if (row['case_id'], row['quote_id'], row['payload']) != (case_id, receipt['id'], _json(receipt)):
                return {**base, 'code': 'payment_binding_conflict'}
            if row['status'] == 'baseline_skipped' and force:
                c.execute("UPDATE wb_receipt_outbox SET status='pending',updated_at=? WHERE id=?", (self.clock(), row['id']))
                return {**base, 'queued': True, 'code': 'queued'}
            code = ('already_accepted' if row['status'] == 'accepted' else 'already_queued' if row['status'] in _ACTIVE
                    else row['status'])
            return {**base, 'queued': row['status'] in _ACTIVE, 'code': code}

    def status(self):
        with self._db() as c:
            rows = c.execute('SELECT * FROM wb_receipt_outbox ORDER BY rowid DESC LIMIT 100').fetchall()
        running = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        return {**FLAGS, 'configured': True, 'enabled': self.enabled, 'running': running,
            'lastError': self._last_error, 'quotes': [{'caseId': row['case_id'], 'quoteId': row['quote_id'],
                'orderNumber': row['order_number'], 'status': row['status'], 'attempts': row['attempts'],
                'lastError': row['last_error'], 'recipientLabel': row['recipient_label'],
                'acceptedAt': _stamp(row['accepted_at'])} for row in rows]}

    def _cancel(self, row, reason):
        with self._db(True) as c:
            c.execute("UPDATE wb_receipt_outbox SET status='cancelled',last_error=?,updated_at=? WHERE id=? AND status IN ('pending','retry','sending')",
                      (reason, self.clock(), row['id']))

    def run_once(self):
        if not self.enabled or not self._cycle.acquire(blocking=False):
            return {**FLAGS, 'processed': False}
        try:
            now = self.clock()
            with self._db() as c:
                row = c.execute("SELECT * FROM wb_receipt_outbox WHERE status IN ('pending','retry','sending') AND next_attempt<=? ORDER BY rowid LIMIT 1", (now,)).fetchone()
            if row is None:
                return {**FLAGS, 'processed': False}
            try:
                current, reason = self._current(row['case_id'])
                valid = current is not None and _json(current) == row['payload']
            except Exception:
                with self._db(True) as c:
                    c.execute("UPDATE wb_receipt_outbox SET status='retry',last_error='current_payment_unavailable',next_attempt=?,updated_at=? WHERE id=? AND status IN ('pending','retry','sending')",
                              (now + 60, now, row['id']))
                return {**FLAGS, 'processed': True, 'deferred': True}
            if not valid:
                self._cancel(row, reason or 'superseded_payment')
                return {**FLAGS, 'processed': True, 'cancelled': True}
            with self._db(True) as c:
                fresh = c.execute('SELECT * FROM wb_receipt_outbox WHERE id=?', (row['id'],)).fetchone()
                if fresh['status'] not in _ACTIVE or fresh['next_attempt'] > now:
                    return {**FLAGS, 'processed': False}
                if (fresh['attempts'] >= MAX_ATTEMPTS or (fresh['attempts'] and now - fresh['first_attempt'] >= RETRY_WINDOW)):
                    c.execute("UPDATE wb_receipt_outbox SET status='needs_review',last_error='retry_expired',updated_at=? WHERE id=?", (now, row['id']))
                    return {**FLAGS, 'processed': True}
                first = fresh['first_attempt'] if fresh['attempts'] else now
                attempt = fresh['attempts'] + 1
                c.execute("UPDATE wb_receipt_outbox SET status='sending',attempts=?,first_attempt=?,last_attempt=?,next_attempt=?,updated_at=? WHERE id=?",
                          (attempt, first, now, now + 60, now, row['id']))
            # Re-check after the durable claim. No SQLite transaction is held
            # while the sender resolves identity or performs the provider call.
            try:
                current, reason = self._current(row['case_id'])
                if current is None or _json(current) != row['payload']:
                    self._cancel(row, reason or 'superseded_payment')
                    return {**FLAGS, 'processed': True, 'cancelled': True}
                result = self.sender.send_receipt(current, row['request_id'])
                if (type(result) is not dict or any(result.get(key) is not value for key, value in
                        (('internalOnly', True), ('realPayment', False), ('releaseAllowed', False)))):
                    raise ValueError()
                state, code = result.get('state'), result.get('code')
                accepted = state == 'accepted' or (state == 'duplicate' and code in
                    ('already_accepted', 'retry_key_accepted', 'api_previously_accepted', 'already_sent'))
                retry = not accepted and state == 'needs_review' and result.get('retryable') is True
                label = result.get('recipientLabel', '')
                label = label if _text(label, 100) and not re.fullmatch(r'U[0-9a-fA-F]{32}', label) else ''
                safe_codes = {'send_busy', 'send_cooldown', 'retry_cooldown', 'network_unknown',
                    'not_configured', 'test_disabled', 'unverified_test_recipient', 'recipient_changed',
                    'request_conflict', 'invalid_quote', 'invalid_receipt', 'session_limit',
                    'api_rejected', 'api_unauthorized', 'api_rate_limited', 'retry_expired'}
                error = '' if accepted else code if code in safe_codes else 'send_unconfirmed' if retry else 'send_failed'
            except Exception:
                accepted, retry, label, error = False, True, '', 'network_unknown'
            with self._db(True) as c:
                c.execute('''UPDATE wb_receipt_outbox SET status=?,last_error=?,recipient_label=?,
                    accepted_at=?,next_attempt=?,updated_at=? WHERE id=? AND status='sending' ''',
                    ('accepted' if accepted else 'retry' if retry else 'failed', error, label,
                     now if accepted else 0, now + min(1800, 60 * 2 ** min(attempt - 1, 5)), now, row['id']))
            return {**FLAGS, 'processed': True, 'accepted': accepted}
        finally:
            self._cycle.release()

    def wake(self):
        self._wake.set()

    def start(self):
        if not self.enabled:
            return False
        if self._db_key is None:
            raise ValueError('付款確認通知尚未初始化')
        with _RUNNING_LOCK:
            if self._thread and self._thread.is_alive():
                return True
            if self._db_key in _RUNNING and _RUNNING[self._db_key] is not self:
                return False
            _RUNNING[self._db_key] = self
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='internal-payment-receipts', daemon=True)
            self._thread.start()
        return True

    def _run(self):
        try:
            while not self._stop.is_set():
                try:
                    self.run_once()
                    self._last_error = ''
                except Exception:
                    self._last_error = 'receipt_worker_failed'
                self._wake.wait(self.interval)
                self._wake.clear()
        finally:
            with _RUNNING_LOCK:
                if _RUNNING.get(self._db_key) is self:
                    _RUNNING.pop(self._db_key, None)

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
