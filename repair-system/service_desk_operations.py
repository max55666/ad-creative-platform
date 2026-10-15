"""Internal-only dispatch gates and refund follow-up ledger.

There are no provider clients, notifications, or production dispatch writes in
this module. Readers are injected and invoked outside SQLite write locks. Every
mutation then verifies the same case/payment evidence under BEGIN IMMEDIATE.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sqlite3
import uuid


FLAGS = {'internalOnly': True, 'realPayment': False, 'releaseAllowed': False,
         'productionPaymentRecognized': False, 'providerWritesEnabled': False,
         'externalDispatchEnabled': False}
STATES = ('awaiting_quote', 'awaiting_payment', 'ready', 'dispatched',
          'refund_hold', 'dispatched_refund_attention')
TAIPEI = timezone(timedelta(hours=8))


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_dump(value).encode('utf-8')).hexdigest()


def _object(value):
    try:
        result = json.loads(value)
        return result if type(result) is dict else {}
    except (TypeError, ValueError):
        return {}


def _text(value, maximum, minimum=0):
    if (type(value) is not str or not minimum <= len(value.strip()) <= maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError('內測作業文字格式不正確')
    return value.strip()


def _uuid(value, prefix=''):
    try:
        if type(value) is not str or not value.startswith(prefix):
            raise ValueError()
        parsed = uuid.UUID(value[len(prefix):])
        if parsed.version != 4 or str(parsed) != value[len(prefix):]:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('僅接受有效的內測案件與請求識別碼') from None
    return value


class ServiceDeskOperations:
    def __init__(self, connection_factory, quote_reader, payment_reader,
                 allowed_case_ids=None, clock=None):
        self.connection_factory = connection_factory
        self.quote_reader = quote_reader
        self.payment_reader = payment_reader
        self.allowed_case_ids = allowed_case_ids
        self.clock = clock or (lambda: datetime.now(TAIPEI))

    def _now(self):
        current = self.clock()
        if not isinstance(current, datetime):
            current = datetime.fromtimestamp(current, TAIPEI)
        if current.tzinfo is None:
            current = current.replace(tzinfo=TAIPEI)
        return current.astimezone(TAIPEI).isoformat(timespec='seconds')

    def _allowed(self, case_id):
        _uuid(case_id, 'WB-')
        registry = self.allowed_case_ids
        if registry is not None and not (registry(case_id) if callable(registry) else case_id in registry):
            raise ValueError('此案件不在內測作業允許名單')

    @contextmanager
    def _connection(self, write=False):
        with self.connection_factory() as c:
            if not isinstance(c, sqlite3.Connection):
                raise ValueError('內測作業資料庫連線不正確')
            c.row_factory = sqlite3.Row
            for row in c.execute('PRAGMA database_list').fetchall():
                if row['name'] not in ('main', 'temp'):
                    raise ValueError('內測作業不得連接外部資料庫')
                if row['file']:
                    absolute, resolved = os.path.abspath(row['file']), os.path.realpath(row['file'])
                    if (os.path.normcase(absolute) != os.path.normcase(resolved)
                            or os.path.basename(resolved).lower() in ('repairs.db', 'payment-lab.db')
                            or os.stat(resolved).st_nlink > 1):
                        raise ValueError('內測作業必須使用獨立工作台資料庫')
            with c:
                if write and not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                tables = {row['name'] for row in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if any(not name.startswith('wb_') for name in tables) or not {'wb_cases', 'wb_quotes'} <= tables:
                    raise ValueError('內測作業不得使用正式案件或其他業務資料庫')
                yield c

    def init(self):
        with self._connection(True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS wb_ops_dispatch (
                case_id TEXT PRIMARY KEY,version INTEGER NOT NULL,state TEXT NOT NULL,
                quote_id TEXT NOT NULL,quote_version INTEGER NOT NULL,proof_hash TEXT NOT NULL,
                refund_seen INTEGER NOT NULL DEFAULT 0,dispatched_at TEXT NOT NULL DEFAULT '',
                dispatched_by TEXT NOT NULL DEFAULT '',dispatch_reason TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_ops_jobs (
                case_id TEXT PRIMARY KEY,status TEXT NOT NULL,quote_id TEXT NOT NULL,
                quote_version INTEGER NOT NULL,updated_at TEXT NOT NULL,reason TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_ops_requests (
                request_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,operation TEXT NOT NULL,
                payload_hash TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_ops_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL,action TEXT NOT NULL,
                actor TEXT NOT NULL,reason TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL)''')
        return dict(FLAGS)

    @staticmethod
    def _source(c, case_id):
        """Fingerprint authoritative case-bound facts, including future wb_* match ledgers.

        Transport queues and automation delivery metadata are excluded: their ACKs
        do not establish or revoke a payment. New reconciliation tables with a
        case_id or quote_id column are included without coupling to their schema.
        """
        case = c.execute('SELECT * FROM wb_cases WHERE id=?', (case_id,)).fetchone()
        if case is None:
            raise ValueError('找不到內測案件副本')
        quotes = c.execute('SELECT * FROM wb_quotes WHERE case_id=? ORDER BY rowid', (case_id,)).fetchall()
        facts = {'wb_cases': [dict(case)], 'wb_quotes': [dict(row) for row in quotes]}
        quote_ids = [row['id'] for row in quotes]
        for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wb_%' ORDER BY name").fetchall():
            table = row['name']
            if (table in facts or table.startswith(('wb_ops_', 'wb_auto_', 'wb_payment_sheet_', 'wb_receipt_', 'wb_refund_notice_'))
                    or not re.fullmatch(r'wb_[A-Za-z0-9_]+', table)):
                continue
            columns = {item['name'] for item in c.execute('PRAGMA table_info("' + table + '")')}
            if 'case_id' in columns:
                rows = c.execute('SELECT * FROM "' + table + '" WHERE case_id=? ORDER BY rowid', (case_id,)).fetchall()
            elif 'quote_id' in columns and quote_ids:
                rows = c.execute('SELECT * FROM "' + table + '" WHERE quote_id IN (' +
                                 ','.join('?' for _ in quote_ids) + ') ORDER BY rowid', quote_ids).fetchall()
            else:
                continue
            facts[table] = [dict(item) for item in rows]
        return _hash(facts), dict(case), [dict(row) for row in quotes]

    def _context(self, case_id):
        self._allowed(case_id)
        for _ in range(3):
            with self._connection() as c:
                before, case_row, quotes = self._source(c, case_id)
            quote_wrapper = self.quote_reader(case_id)
            projection = self.payment_reader(case_id)
            with self._connection() as c:
                after, _, _ = self._source(c, case_id)
            if before == after:
                break
        else:
            raise ValueError('案件或付款證據正在更新，請稍後重新整理')
        data = _object(case_row['data'])
        if data.get('source') not in ('snapshot', 'synthetic', 'test_intake') or type(data.get('pickup')) is not bool:
            raise ValueError('內測案件來源或物流方式不正確')
        if data.get('source') == 'test_intake':
            _uuid(data.get('customerId'), 'WC-')
        active = next((row for row in quotes if row['id'] == case_row['latest_quote_id']), None)
        supplied = quote_wrapper.get('quote') if type(quote_wrapper) is dict else None
        if active is None:
            if supplied is not None:
                raise ValueError('目前報價讀取不同步，請重新整理')
            quote = None
        else:
            quote = {**_object(active['data']), 'id': active['id'], 'version': active['version'],
                     'status': active['status'], 'paymentStatus': active['payment_status']}
            if (type(supplied) is not dict or any(supplied.get(key) != quote.get(key)
                    for key in ('id', 'version', 'status', 'paymentStatus', 'total', 'pickupFee', 'repairFee', 'currency'))):
                raise ValueError('目前報價讀取不同步，請重新整理')
            if (quote['status'] != 'active' or type(quote['version']) is not int
                    or quote['version'] != case_row['version'] or quote['version'] < 1
                    or any(type(quote.get(key)) is not int or not 0 <= quote[key] <= 100350
                           for key in ('repairFee', 'pickupFee', 'total'))
                    or quote['pickupFee'] != (350 if data['pickup'] else 0)
                    or quote['repairFee'] + quote['pickupFee'] != quote['total']
                    or quote.get('currency') != 'TWD'):
                raise ValueError('目前報價金額或物流費不完整，無法放行')
        projection = projection if type(projection) is dict else {}
        current_projection = (quote is not None and projection.get('caseId') == case_id
            and projection.get('caseNumber') == data.get('caseNumber')
            and projection.get('name') == data.get('name')
            and type(projection.get('quoteVersion')) is int and projection['quoteVersion'] == quote['version']
            and type(projection.get('amountDue')) is int and projection['amountDue'] == quote['total'])
        payment_status = projection.get('paymentStatus', '') if current_projection else ''
        refunded = current_projection and payment_status in ('退款需處理', '已退款')
        free = (quote is not None and quote['total'] == 0 and not data['pickup']
                and quote['paymentStatus'] == 'no_payment_required')
        paid = (current_projection and payment_status == '已付款'
                and projection.get('source') in ('shopline_api_completed', 'shopline_api_manual_completed')
                and type(projection.get('amountPaid')) is int
                and projection['amountPaid'] == quote['total'] and quote['total'] > 0)
        base = 'awaiting_quote' if quote is None else 'refund_hold' if refunded else 'ready' if paid or free else 'awaiting_payment'
        proof = _hash({'quote': quote, 'payment': {key: projection.get(key) for key in (
            'quoteVersion', 'paymentStatus', 'amountDue', 'amountPaid', 'paymentOrderNumber', 'source')}, 'base': base})
        return {'fingerprint': after, 'case': {**data, 'id': case_id}, 'quote': quote,
                'payment': projection, 'paymentStatus': payment_status, 'base': base,
                'proof': proof, 'refunded': bool(refunded)}

    @staticmethod
    def _effective(context, saved):
        dispatched = bool(saved and saved['dispatched_at'])
        quote_id = context['quote']['id'] if context['quote'] else ''
        prior_refund = bool(saved and saved['refund_seen'] and
                            (saved['quote_id'] == quote_id or dispatched))
        refund_seen = prior_refund or context['refunded']
        state = ('dispatched_refund_attention' if refund_seen else 'dispatched') if dispatched else (
            'refund_hold' if refund_seen else context['base'])
        return state, refund_seen

    def _refresh(self, c, context):
        case_id = context['case']['id']
        if self._source(c, case_id)[0] != context['fingerprint']:
            raise ValueError('案件或付款證據已變更，請重新整理後再操作')
        saved = c.execute('SELECT * FROM wb_ops_dispatch WHERE case_id=?', (case_id,)).fetchone()
        state, refund_seen = self._effective(context, saved)
        quote = context['quote'] or {}
        changed = not saved or (saved['state'], saved['quote_id'], saved['quote_version'], saved['proof_hash'], saved['refund_seen']) != (
            state, quote.get('id', ''), quote.get('version', 0), context['proof'], int(refund_seen))
        version = (saved['version'] + int(changed)) if saved else 1
        if changed:
            c.execute('''INSERT INTO wb_ops_dispatch(case_id,version,state,quote_id,quote_version,
                proof_hash,refund_seen,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET
                version=excluded.version,state=excluded.state,quote_id=excluded.quote_id,
                quote_version=excluded.quote_version,proof_hash=excluded.proof_hash,
                refund_seen=excluded.refund_seen,updated_at=excluded.updated_at''',
                (case_id, version, state, quote.get('id', ''), quote.get('version', 0), context['proof'], int(refund_seen), self._now()))
            if saved and saved['state'] != state:
                self._audit(c, case_id, 'gate_changed', '系統', '',
                            {'from': saved['state'], 'to': state, 'quoteVersion': quote.get('version', 0)})
        job = ('completed' if state.startswith('dispatched') else 'cancelled' if refund_seen
               else 'queued' if state == 'ready' and context['case']['pickup'] else 'withheld')
        c.execute('''INSERT INTO wb_ops_jobs(case_id,status,quote_id,quote_version,updated_at,reason)
            VALUES(?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET status=excluded.status,
            quote_id=excluded.quote_id,quote_version=excluded.quote_version,updated_at=excluded.updated_at,
            reason=excluded.reason''', (case_id, job, quote.get('id', ''), quote.get('version', 0),
                                     self._now(), '退款案件停止內測派車' if refund_seen else state))
        return c.execute('SELECT * FROM wb_ops_dispatch WHERE case_id=?', (case_id,)).fetchone()

    def _audit(self, c, case_id, action, actor, reason, detail):
        c.execute('INSERT INTO wb_ops_audit(case_id,action,actor,reason,detail,created_at) VALUES(?,?,?,?,?,?)',
                  (case_id, action, actor, reason, _dump(detail), self._now()))

    def _result(self, c, context, saved, idempotent=False):
        case, quote, payment = context['case'], context['quote'] or {}, context['payment']
        state = saved['state']
        return {**FLAGS, **{key: case.get(key, '') for key in ('caseNumber', 'name', 'phone', 'address', 'model', 'pickup')},
            'caseId': case['id'], 'quoteId': quote.get('id', ''), 'quoteVersion': quote.get('version', 0),
            'operationsVersion': saved['version'], 'dispatchState': state,
            'paymentStatus': context['paymentStatus'] or ('待核價' if not quote else '待付款'),
            'amountDue': quote.get('total', 0), 'amountPaid': payment.get('amountPaid', 0) if context['paymentStatus'] else 0,
            'internalDispatchAllowed': bool(state == 'ready' and case['pickup']),
            'internalSendRepairAllowed': state == 'ready', 'refundRequiresAttention': bool(saved['refund_seen']),
            'dispatchedAt': saved['dispatched_at'], 'dispatchedBy': saved['dispatched_by'],
            'dispatchReason': saved['dispatch_reason'], 'updatedAt': saved['updated_at'],
            'jobStatus': c.execute('SELECT status FROM wb_ops_jobs WHERE case_id=?', (case['id'],)).fetchone()['status'],
            'idempotent': idempotent,
            'history': [dict(row) for row in c.execute('''SELECT action,actor,reason,detail,created_at AS createdAt
                FROM wb_ops_audit WHERE case_id=? ORDER BY id DESC LIMIT 50''', (case['id'],))]}

    def refresh(self, case_id):
        context = self._context(case_id)
        with self._connection(True) as c:
            return self._result(c, context, self._refresh(c, context))

    def case_state(self, case_id):
        return self.refresh(case_id)

    def state(self):
        with self._connection() as c:
            ids = [row['id'] for row in c.execute('SELECT id FROM wb_cases ORDER BY rowid')]
        rows = []
        for case_id in ids:
            try:
                self._allowed(case_id)
            except ValueError:
                continue
            rows.append(self.case_state(case_id))
        ready = [row for row in rows if row['internalDispatchAllowed']]
        return {**FLAGS, 'cases': rows, 'readyPickupCases': ready, 'readyPickupCount': len(ready),
                'awaitingPaymentCount': sum(row['dispatchState'] == 'awaiting_payment' for row in rows),
                'refundAttentionCount': sum(row['refundRequiresAttention'] for row in rows),
                'summary': {state: sum(row['dispatchState'] == state for row in rows) for state in STATES}}

    def _mutate(self, case_id, payload, actor, operation):
        allowed = {'expectedVersion', 'requestId', 'reason'} | ({'action'} if operation == 'refund_note' else set())
        if type(payload) is not dict or set(payload) != allowed:
            raise ValueError('內測作業欄位不正確')
        request_id = _uuid(payload['requestId'])
        expected = payload['expectedVersion']
        if type(expected) is not int or expected < 1:
            raise ValueError('請提供目前內測作業版本')
        reason, actor = _text(payload['reason'], 500, 1), _text(actor, 100, 1)
        if operation == 'refund_note' and payload['action'] not in ('acknowledged', 'followup'):
            raise ValueError('退款作業只接受確認或追蹤註記，不會執行退款')
        context = self._context(case_id)
        fingerprint = _hash({'caseId': case_id, 'operation': operation, 'payload': payload, 'actor': actor})
        with self._connection(True) as c:
            prior = c.execute('SELECT * FROM wb_ops_requests WHERE request_id=?', (request_id,)).fetchone()
            if prior and prior['payload_hash'] != fingerprint:
                raise ValueError('相同請求識別碼的內測作業內容不同')
            saved = self._refresh(c, context)
            if prior:
                return self._result(c, context, saved, True)
            if saved['version'] != expected:
                raise ValueError('內測作業版本已變更，請重新整理後再操作')
            if operation == 'dispatch':
                if saved['state'] != 'ready' or context['case']['pickup'] is not True:
                    raise ValueError('案件尚未通過付款門檻，或不是需要派車的案件')
                c.execute('''UPDATE wb_ops_dispatch SET state='dispatched',version=version+1,
                    dispatched_at=?,dispatched_by=?,dispatch_reason=?,updated_at=? WHERE case_id=?''',
                    (self._now(), actor, reason, self._now(), case_id))
                c.execute("UPDATE wb_ops_jobs SET status='completed',updated_at=?,reason='內測已派車' WHERE case_id=?",
                          (self._now(), case_id))
                self._audit(c, case_id, 'internal_dispatched', actor, reason,
                            {'quoteId': saved['quote_id'], 'quoteVersion': saved['quote_version'], 'externalDispatchEnabled': False})
            else:
                if saved['state'] not in ('refund_hold', 'dispatched_refund_attention'):
                    raise ValueError('目前案件沒有待處理的退款警示')
                c.execute('UPDATE wb_ops_dispatch SET version=version+1,updated_at=? WHERE case_id=?', (self._now(), case_id))
                self._audit(c, case_id, 'refund_' + payload['action'], actor, reason,
                            {'state': saved['state'], 'fundsMoved': False, 'holdReleased': False})
            saved = c.execute('SELECT * FROM wb_ops_dispatch WHERE case_id=?', (case_id,)).fetchone()
            result = self._result(c, context, saved)
            c.execute('INSERT INTO wb_ops_requests(request_id,case_id,operation,payload_hash,result,created_at) VALUES(?,?,?,?,?,?)',
                      (request_id, case_id, operation, fingerprint, _dump({'version': saved['version']}), self._now()))
            return result

    def mark_dispatched(self, case_id, payload, actor='管理員'):
        return self._mutate(case_id, payload, actor, 'dispatch')

    def record_refund_action(self, case_id, payload, actor='管理員'):
        return self._mutate(case_id, payload, actor, 'refund_note')
