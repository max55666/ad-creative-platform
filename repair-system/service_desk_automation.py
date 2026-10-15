"""Opt-in automation for the isolated wb_* customer-service test database.

No credentials, recipient selection or provider writes live here.  The caller
supplies a single-recipient LineTestSender and an authenticated read-only
provider.  Only explicitly enrolled, allowlisted snapshot quotes are processed.
Every reconciliation callback must perform its own exact fresh provider lookup.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid

from order_matching import normalize_phone


FLAGS = {'internalOnly': True, 'realPayment': False, 'releaseAllowed': False,
         'productionPaymentRecognized': False, 'providerWritesEnabled': False}
PROVIDER_GAP = 35
RETRY_WINDOW = 23 * 3600
MAX_LINE_ATTEMPTS = 8
_RUNNING = {}
_RUNNING_LOCK = threading.Lock()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _identity(value, prefix):
    try:
        suffix = value[len(prefix):]
        parsed = uuid.UUID(suffix)
        return type(value) is str and value.startswith(prefix) and parsed.version == 4 and str(parsed) == suffix
    except (TypeError, AttributeError, ValueError):
        return False


def _stamp(value):
    return datetime.fromtimestamp(value, timezone(timedelta(hours=8))).isoformat() if value else ''


class ServiceDeskAutomation:
    def __init__(self, connection_factory, *, quote_reader, line_sender,
                 order_provider, reconcile, allowed_case_ids, enabled=False,
                 clock=time.time, poll_interval=90):
        if (not callable(connection_factory) or not callable(quote_reader)
                or not callable(reconcile) or not callable(clock)
                or not callable(getattr(line_sender, 'send', None))
                or not callable(getattr(line_sender, 'status', None))
                or not callable(getattr(order_provider, 'fetch', None))
                or not callable(getattr(order_provider, 'state', None))):
            raise ValueError('內測自動流程的服務設定不正確')
        if (type(enabled) is not bool or type(poll_interval) is not int
                or not 60 <= poll_interval <= 3600
                or (not callable(allowed_case_ids) and (not isinstance(allowed_case_ids, (set, frozenset, list, tuple))
                    or not 1 <= len(allowed_case_ids) <= 100
                    or any(not _identity(case_id, 'WB-') for case_id in allowed_case_ids)))):
            raise ValueError('內測自動流程必須設定有限的案件副本名單')
        self.connection_factory, self.quote_reader = connection_factory, quote_reader
        self.line_sender, self.order_provider, self.reconcile = line_sender, order_provider, reconcile
        self.allowed = allowed_case_ids if callable(allowed_case_ids) else frozenset(allowed_case_ids)
        self.enabled, self.clock, self.poll_interval = enabled, clock, poll_interval
        self._owner = str(uuid.uuid4())
        self._cycle_lock = threading.Lock()
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread, self._db_key = None, None

    @contextmanager
    def _connection(self, write=False):
        with self.connection_factory() as c:
            if not isinstance(c, sqlite3.Connection):
                raise ValueError('內測自動流程的資料庫不正確')
            c.row_factory = sqlite3.Row
            for row in c.execute('PRAGMA database_list'):
                if row['name'] not in ('main', 'temp'):
                    raise ValueError('內測自動流程不得連接外部資料庫')
                if row['file']:
                    absolute, resolved = os.path.abspath(row['file']), os.path.realpath(row['file'])
                    if (os.path.normcase(absolute) != os.path.normcase(resolved)
                            or os.path.basename(resolved).lower() in ('repairs.db', 'payment-lab.db')
                            or os.stat(resolved).st_nlink > 1):
                        raise ValueError('內測自動流程必須使用獨立客服資料庫')
            with c:
                if write and not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                names = {r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if not {'wb_cases', 'wb_quotes', 'wb_audit'} <= names or any(not n.startswith('wb_') for n in names):
                    raise ValueError('內測自動流程不得使用正式或其他業務資料庫')
                yield c

    def init(self):
        with self._connection(True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS wb_auto_notifications (
                quote_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, quote_version INTEGER NOT NULL,
                request_id TEXT NOT NULL UNIQUE, snapshot TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                first_attempt REAL NOT NULL DEFAULT 0, last_attempt REAL NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_auto_enrollments (
                quote_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, quote_version INTEGER NOT NULL,
                status TEXT NOT NULL, checked_at REAL NOT NULL DEFAULT 0,
                payment_status TEXT NOT NULL DEFAULT 'awaiting_payment',
                order_number TEXT NOT NULL DEFAULT '')''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_auto_order_jobs (
                quote_id TEXT NOT NULL, order_number TEXT NOT NULL, observation_hash TEXT NOT NULL,
                request_id TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(quote_id,order_number))''')
            c.execute('CREATE TABLE IF NOT EXISTS wb_auto_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            if 'last_checked' not in {row['name'] for row in c.execute('PRAGMA table_info(wb_auto_order_jobs)')}:
                c.execute('ALTER TABLE wb_auto_order_jobs ADD COLUMN last_checked REAL NOT NULL DEFAULT 0')
            row = c.execute("SELECT file FROM pragma_database_list WHERE name='main'").fetchone()
            self._db_key = os.path.normcase(os.path.realpath(row['file'])) if row and row['file'] else id(self.connection_factory)
        return self.status()

    @staticmethod
    def _meta(c, key, default=''):
        row = c.execute('SELECT value FROM wb_auto_meta WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    @staticmethod
    def _set(c, key, value):
        c.execute('INSERT INTO wb_auto_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))

    def _wrapper(self, quote_id):
        if not _identity(quote_id, 'WQ-'):
            raise ValueError('內測報價識別碼不正確')
        wrapper = self.quote_reader(quote_id)
        if type(wrapper) is not dict or type(wrapper.get('quote')) is not dict or type(wrapper.get('case')) is not dict:
            raise ValueError('找不到內測報價副本')
        quote, case = wrapper['quote'], wrapper['case']
        for part in (wrapper, quote, case):
            if any(part.get(k) is not v for k, v in (('internalOnly', True), ('simulation', True), ('realPayment', False), ('releaseAllowed', False))):
                raise ValueError('只接受隔離內測報價')
        allowed = self.allowed() if callable(self.allowed) else self.allowed
        if (not isinstance(allowed, (set, frozenset, list, tuple)) or not 1 <= len(allowed) <= 100
                or any(not _identity(case_id, 'WB-') for case_id in allowed)):
            raise ValueError('內測自動流程的動態案件名單不正確')
        if (case.get('id') not in allowed or case.get('source') not in ('snapshot', 'test_intake')
                or quote.get('id') != quote_id or quote.get('caseId') != case.get('id')
                or quote.get('status') != 'active'
                or type(case.get('latestQuote')) is not dict or case['latestQuote'].get('id') != quote_id
                or quote.get('paymentStatus') not in ('awaiting_payment', 'no_payment_required')
                or quote.get('acceptedOrderId') or quote.get('currency') != 'TWD'
                or type(quote.get('total')) is not int or not 0 <= quote['total'] <= 100000
                or type(quote.get('version')) is not int or not 1 <= quote['version'] <= 1000000
                or not re.fullmatch(r'R[0-9]{8}-[0-9]{4,8}', quote.get('caseNumber', ''))):
            raise ValueError('報價未列入本次內測或不是目前有效版本')
        return wrapper

    def quote_approved(self, quote_id):
        if not self.enabled:
            return {**FLAGS, 'enrolled': False, 'code': 'automation_disabled'}
        wrapper = self._wrapper(quote_id)
        quote, case, now = wrapper['quote'], wrapper['case'], self.clock()
        with self._connection(True) as c:
            c.execute("UPDATE wb_auto_notifications SET status='cancelled',last_error='superseded_quote',updated_at=? WHERE case_id=? AND quote_id<>? AND status<>'accepted'", (now, case['id'], quote_id))
            c.execute("UPDATE wb_auto_enrollments SET status='superseded' WHERE case_id=? AND quote_id<>?", (case['id'], quote_id))
            c.execute('''INSERT OR IGNORE INTO wb_auto_enrollments(quote_id,case_id,quote_version,status,payment_status)
                VALUES(?,?,?,?,?)''', (quote_id, case['id'], quote['version'], 'active' if quote['total'] else 'no_payment', 'awaiting_payment' if quote['total'] else 'no_payment_required'))
            if quote['total']:
                c.execute('''INSERT OR IGNORE INTO wb_auto_notifications(quote_id,case_id,quote_version,
                    request_id,snapshot,status,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)''',
                    (quote_id, case['id'], quote['version'], str(uuid.uuid4()), _json(quote), now, now))
        self.wake()
        return {**FLAGS, 'enrolled': True, 'quoteId': quote_id}

    def retry_notification(self, quote_id):
        """Explicit operator retry; never create or replace a LINE retry key."""
        if not self.enabled:
            return {**FLAGS, 'retryQueued': False, 'code': 'automation_disabled'}
        quote = self._wrapper(quote_id)['quote']
        if quote['total'] == 0:
            return {**FLAGS, 'retryQueued': False, 'quoteId': quote_id, 'code': 'no_payment_required'}
        now = self.clock()
        with self._connection(True) as c:
            row = c.execute('SELECT * FROM wb_auto_notifications WHERE quote_id=?', (quote_id,)).fetchone()
            if row is None:
                raise ValueError('報價尚未啟用本次自動內測通知')
            if row['status'] == 'accepted':
                return {**FLAGS, 'retryQueued': False, 'quoteId': quote_id, 'code': 'already_accepted'}
            if row['status'] == 'sending':
                return {**FLAGS, 'retryQueued': False, 'quoteId': quote_id, 'code': 'send_in_progress'}
            if row['attempts'] >= MAX_LINE_ATTEMPTS or (row['attempts'] and now - row['first_attempt'] >= RETRY_WINDOW):
                c.execute("UPDATE wb_auto_notifications SET status='needs_review',last_error='retry_expired',updated_at=? WHERE quote_id=?", (now, quote_id))
                return {**FLAGS, 'retryQueued': False, 'quoteId': quote_id, 'code': 'retry_expired'}
            # A manual click must not accelerate a retry while a provider
            # cooldown is active. Hard failures may resume after fixing config.
            due = max(now, row['last_attempt'] + 60) if row['attempts'] else now
            c.execute("UPDATE wb_auto_notifications SET status='pending',next_attempt=?,updated_at=? WHERE quote_id=?", (due, now, quote_id))
        self.wake()
        return {**FLAGS, 'retryQueued': True, 'quoteId': quote_id, 'code': 'same_request_queued'}

    def status(self):
        try:
            line_state = self.line_sender.status()
            if type(line_state) is not dict:
                line_state = {}
        except Exception:
            line_state = {}
        try:
            payment_state = self.order_provider.state()
            if type(payment_state) is not dict:
                payment_state = {}
        except Exception:
            payment_state = {}
        line_configured = line_state.get('configured') is True
        line_enabled = self.enabled and line_state.get('enabled') is True
        payment_configured = payment_state.get('configured') is True
        configured = line_configured and line_enabled and payment_configured
        with self._connection() as c:
            rows = c.execute('''SELECT e.quote_id,e.payment_status,e.checked_at,e.order_number,
                COALESCE(n.status,'not_required') AS line_status,COALESCE(n.last_error,'') AS line_error,
                COALESCE(n.attempts,0) AS attempts FROM wb_auto_enrollments e LEFT JOIN
                wb_auto_notifications n ON n.quote_id=e.quote_id WHERE e.status<>'superseded' ORDER BY e.rowid DESC LIMIT 100''').fetchall()
            return {**FLAGS, 'enabled': self.enabled, 'configured': configured,
                    'line': {'configured': line_configured, 'enabled': line_enabled},
                    'payment': {'configured': payment_configured,
                                'automaticCheckEnabled': self.enabled and payment_configured},
                    'running': bool(self._thread and self._thread.is_alive()),
                    'pollingIntervalSeconds': self.poll_interval,
                    'providerMinimumGapSeconds': PROVIDER_GAP,
                    'lineRetryStorage': 'persistent_same_retry_key',
                    'lastScanAt': _stamp(float(self._meta(c, 'last_scan_at', '0'))),
                    'lastError': self._meta(c, 'last_error'),
                    'quotes': [{'quoteId': r['quote_id'], 'lineStatus': r['line_status'],
                        'lineError': r['line_error'], 'attempts': r['attempts'],
                        'checkedAt': _stamp(r['checked_at']), 'paymentStatus': r['payment_status'],
                        'orderNumber': r['order_number']} for r in rows]}

    def _lease(self, now):
        with self._connection(True) as c:
            owner, until = self._meta(c, 'lease_owner'), float(self._meta(c, 'lease_until', '0'))
            if owner and owner != self._owner and until > now:
                return False
            self._set(c, 'lease_owner', self._owner)
            self._set(c, 'lease_until', now + 120)
            return True

    def _release(self):
        with self._connection(True) as c:
            if self._meta(c, 'lease_owner') == self._owner:
                self._set(c, 'lease_owner', '')
                self._set(c, 'lease_until', 0)

    def _line(self, now):
        with self._connection() as c:
            row = c.execute("SELECT * FROM wb_auto_notifications WHERE status IN ('pending','retry','sending') AND next_attempt<=? ORDER BY created_at LIMIT 1", (now,)).fetchone()
        if not row:
            return
        try:
            quote = self._wrapper(row['quote_id'])['quote']
            stored = json.loads(row['snapshot'])
            # Ignore volatile notification attempt counters, but never replace
            # the immutable content associated with a durable LINE retry key.
            keys = ('id', 'caseId', 'caseNumber', 'name', 'version', 'total', 'currency', 'message', 'clipboardText')
            if any(quote.get(k) != stored.get(k) for k in keys):
                raise ValueError()
        except Exception:
            with self._connection(True) as c:
                c.execute("UPDATE wb_auto_notifications SET status='cancelled',last_error='superseded_quote',updated_at=? WHERE quote_id=?", (now, row['quote_id']))
                c.execute("UPDATE wb_auto_enrollments SET status='superseded' WHERE quote_id=?", (row['quote_id'],))
            return
        first = row['first_attempt'] or now
        if row['attempts'] >= MAX_LINE_ATTEMPTS or now - first >= RETRY_WINDOW:
            with self._connection(True) as c:
                c.execute("UPDATE wb_auto_notifications SET status='needs_review',last_error='retry_expired',updated_at=? WHERE quote_id=?", (now, row['quote_id']))
            return
        with self._connection(True) as c:
            c.execute("UPDATE wb_auto_notifications SET status='sending',attempts=attempts+1,first_attempt=?,last_attempt=?,next_attempt=?,updated_at=? WHERE quote_id=?", (first, now, now + 60, now, row['quote_id']))
        try:
            result = self.line_sender.send(stored, row['request_id'])
            state, code = result.get('state'), result.get('code', '')
            success = state == 'accepted' or (state == 'duplicate' and code in ('already_accepted', 'retry_key_accepted'))
            retry = result.get('retryable') is True
        except Exception:
            success, retry, code = False, True, 'unknown_result'
        if not re.fullmatch(r'[a-z_]{1,64}', code or ''):
            code = 'provider_result_unknown'
        attempts = row['attempts'] + 1
        next_attempt = now + min(3600, 60 * 2 ** min(attempts - 1, 6))
        with self._connection(True) as c:
            c.execute('''UPDATE wb_auto_notifications SET status=?,last_error=?,next_attempt=?,updated_at=? WHERE quote_id=?''',
                ('accepted' if success else 'retry' if retry else 'failed', '' if success else code, next_attempt, now, row['quote_id']))

    def _provider_ready(self, now):
        with self._connection(True) as c:
            if float(self._meta(c, 'next_provider_at', '0')) > now:
                return False
            self._set(c, 'next_provider_at', now + PROVIDER_GAP)
            return True

    @staticmethod
    def _provider_valid(state):
        return (type(state) is dict and state.get('configured') is True and state.get('status') == 'ok'
                and state.get('truncated') is False and state.get('readOnly') is True
                and state.get('simulation') is False and state.get('realPayment') is False
                and state.get('releaseAllowed') is False and type(state.get('orders')) is list
                and len(state['orders']) <= 100)

    def _observe(self, now):
        with self._connection() as c:
            job = c.execute("SELECT j.* FROM wb_auto_order_jobs j JOIN wb_auto_enrollments e ON e.quote_id=j.quote_id WHERE e.status='active' AND j.status IN ('queued','retry') AND j.next_attempt<=? ORDER BY j.rowid LIMIT 1", (now,)).fetchone()
        if not job:
            return False
        try:
            self._wrapper(job['quote_id'])
        except Exception:
            with self._connection(True) as c:
                c.execute("UPDATE wb_auto_order_jobs SET status='cancelled',last_error='superseded_quote' WHERE quote_id=? AND order_number=?", (job['quote_id'], job['order_number']))
            return True
        if not self._provider_ready(now):
            return True
        try:
            result = self.reconcile(job['quote_id'], {'orderNumber': job['order_number'], 'requestId': job['request_id']})
            if (type(result) is not dict or any(result.get(k) is not v for k, v in FLAGS.items() if k != 'providerWritesEnabled')
                    or type(result.get('result')) is not dict):
                raise ValueError()
            outcome = result['result']
            reasons = outcome.get('reasons', [])
            if outcome.get('state') == 'matched_internal_only' or (outcome.get('state') == 'duplicate' and outcome.get('code') == 'already_matched_internal_only'):
                payment = 'paid_internal_only'
            elif 'refunded' in reasons:
                payment = 'refund_needs_review'
            elif reasons and set(reasons) <= {'not_completed'}:
                payment = 'awaiting_payment'
            else:
                payment = 'needs_review'
        except Exception:
            with self._connection(True) as c:
                c.execute("UPDATE wb_auto_order_jobs SET status='retry',attempts=attempts+1,next_attempt=?,last_error='provider_lookup_failed' WHERE quote_id=? AND order_number=?", (now + min(1800, 60 * 2 ** min(job['attempts'], 5)), job['quote_id'], job['order_number']))
                self._set(c, 'last_error', 'provider_lookup_failed')
            return True
        with self._connection(True) as c:
            c.execute("UPDATE wb_auto_order_jobs SET status='done',attempts=attempts+1,last_error='',last_checked=? WHERE quote_id=? AND order_number=?", (now, job['quote_id'], job['order_number']))
            prior = c.execute('SELECT payment_status,order_number FROM wb_auto_enrollments WHERE quote_id=?', (job['quote_id'],)).fetchone()
            if prior and prior['payment_status'] == 'refund_needs_review' and prior['order_number'] == job['order_number']:
                payment = 'refund_needs_review'
            if prior and prior['payment_status'] in ('paid_internal_only', 'refund_needs_review') and prior['order_number'] != job['order_number']:
                c.execute('UPDATE wb_auto_enrollments SET checked_at=? WHERE quote_id=?', (now, job['quote_id']))
            else:
                c.execute('UPDATE wb_auto_enrollments SET checked_at=?,payment_status=?,order_number=? WHERE quote_id=?', (now, payment, job['order_number'], job['quote_id']))
            self._set(c, 'last_error', '')
        return True

    def _scan(self, now):
        with self._connection() as c:
            rows = c.execute("SELECT quote_id FROM wb_auto_enrollments WHERE status='active' ORDER BY rowid LIMIT 100").fetchall()
            due = float(self._meta(c, 'next_scan_at', '0')) <= now
        if not rows or not due or not self._provider_ready(now):
            return
        wrappers = []
        for row in rows:
            try:
                wrappers.append(self._wrapper(row['quote_id']))
            except Exception:
                with self._connection(True) as c:
                    c.execute("UPDATE wb_auto_enrollments SET status='superseded' WHERE quote_id=?", (row['quote_id'],))
        if not wrappers:
            return
        try:
            state = self.order_provider.fetch({'days': 30})
            if not self._provider_valid(state):
                raise ValueError('truncated' if type(state) is dict and state.get('truncated') else 'provider_scan_failed')
            orders = state['orders']
        except Exception as exc:
            with self._connection(True) as c:
                self._set(c, 'next_scan_at', now + self.poll_interval)
                self._set(c, 'last_error', 'provider_scan_truncated' if str(exc) == 'truncated' else 'provider_scan_failed')
            return
        with self._connection(True) as c:
            self._set(c, 'last_scan_at', now)
            self._set(c, 'next_scan_at', now + self.poll_interval)
            self._set(c, 'last_error', '')
            for wrapper in wrappers:
                quote, case = wrapper['quote'], wrapper['case']
                table = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wb_real_order_checks'").fetchone()
                bound = c.execute("SELECT order_id,order_number FROM wb_real_order_checks WHERE quote_id=? AND outcome='matched_internal_only' LIMIT 1",
                                  (quote['id'],)).fetchone() if table else None
                for order in orders:
                    if type(order) is not dict or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', order.get('orderNumber', '')):
                        continue
                    remarks = order.get('orderRemarks', '')
                    references = set(re.findall(r'R[0-9]{8}-[0-9]{4,8}', remarks)) if type(remarks) is str else set()
                    phone = normalize_phone(case.get('phone', ''))
                    contact = bool(phone and phone in (normalize_phone(order.get('customerPhone', '')), normalize_phone(order.get('recipientPhone', ''))))
                    exact = references == {quote['caseNumber']}
                    fallback = not references and contact and case.get('name') in (order.get('customerName'), order.get('recipientName'))
                    is_bound = bool(bound and bound['order_id'] == order.get('id') and bound['order_number'] == order['orderNumber'])
                    if not is_bound and (not contact or not (exact or fallback)):
                        continue
                    # Fallbacks are recorded by the strict reconciliation service
                    # as needs_review; they can never auto-pass its remark checks.
                    # Preview decorations (fetchedAt/matching) change on every
                    # read.  Only provider order facts define an observation.
                    facts = {key: order.get(key) for key in ('id', 'orderNumber',
                        'customerName', 'customerPhone', 'recipientName', 'recipientPhone',
                        'address', 'orderRemarks', 'currency', 'total', 'productValid',
                        'reportedPaymentStatus', 'reportedPaidAt', 'createdAt',
                        'paymentVerified', 'reviewReasons')}
                    fingerprint = hashlib.sha256(_json(facts).encode('utf-8')).hexdigest()
                    prior = c.execute('SELECT * FROM wb_auto_order_jobs WHERE quote_id=? AND order_number=?', (quote['id'], order['orderNumber'])).fetchone()
                    if prior and prior['observation_hash'] == fingerprint:
                        continue
                    c.execute('''INSERT INTO wb_auto_order_jobs(quote_id,order_number,observation_hash,request_id,status)
                        VALUES(?,?,?,?,'queued') ON CONFLICT(quote_id,order_number) DO UPDATE SET
                        observation_hash=excluded.observation_hash,request_id=excluded.request_id,
                        status='queued',attempts=0,next_attempt=0,last_error='' ''',
                        (quote['id'], order['orderNumber'], fingerprint, str(uuid.uuid4())))
                if bound:
                    prior = c.execute('SELECT * FROM wb_auto_order_jobs WHERE quote_id=? AND order_number=?',
                                      (quote['id'], bound['order_number'])).fetchone()
                    # Already accepted orders may age out of the rolling scan or
                    # have their contact/remarks edited. Re-read their exact ID
                    # periodically so refunds still revoke the internal gate.
                    if prior is None or (prior['status'] == 'done' and prior['last_checked'] <= now - 900):
                        fingerprint = 'bound-periodic:' + str(int(now // 900))
                        c.execute('''INSERT INTO wb_auto_order_jobs(quote_id,order_number,observation_hash,request_id,status)
                            VALUES(?,?,?,?,'queued') ON CONFLICT(quote_id,order_number) DO UPDATE SET
                            observation_hash=excluded.observation_hash,request_id=excluded.request_id,
                            status='queued',attempts=0,next_attempt=0,last_error='' ''',
                            (quote['id'], bound['order_number'], fingerprint, str(uuid.uuid4())))

    def run_once(self):
        if not self.enabled or not self._cycle_lock.acquire(blocking=False):
            return {**FLAGS, 'processed': False}
        leased = False
        try:
            now = self.clock()
            leased = self._lease(now)
            if not leased:
                return {**FLAGS, 'processed': False, 'code': 'worker_busy'}
            self._line(now)
            if not self._observe(now):
                self._scan(now)
            return {**FLAGS, 'processed': True}
        finally:
            if leased:
                self._release()
            self._cycle_lock.release()

    def _loop(self):
        try:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception:
                    try:
                        with self._connection(True) as c:
                            self._set(c, 'last_error', 'automation_cycle_failed')
                    except Exception:
                        pass
                self._wake.wait(2)
                self._wake.clear()
        finally:
            with _RUNNING_LOCK:
                if _RUNNING.get(self._db_key) is self:
                    _RUNNING.pop(self._db_key, None)

    def start(self):
        if not self.enabled:
            return False
        if self._db_key is None:
            self.init()
        with _RUNNING_LOCK:
            if self._thread and self._thread.is_alive():
                return True
            if self._db_key in _RUNNING:
                return False
            _RUNNING[self._db_key] = self
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name='service-desk-test-automation', daemon=True)
            self._thread.start()
        return True

    def stop(self, timeout=15):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not bool(self._thread and self._thread.is_alive())

    def wake(self):
        self._wake.set()
