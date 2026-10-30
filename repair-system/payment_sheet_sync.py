"""Offline payment-sheet projection and durable, case-collapsing outbox.

Only server-owned workbench facts are projected. This module cannot connect to
Google, SHOPLINE, LINE, or a production database, and cannot recognize a
production payment. Cloud transport must separately validate its destination.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sqlite3
import uuid

from service_desk_reconciliation import _valid_repair_allocation


HEADERS = ['案件編號', '申請人', '付款狀態', '維修費', '派車回收費', '應付合計',
           '已付金額', '付款訂單編號', '付款完成時間', '最近核對時間', '報價版本', '同步版本']
FLAGS = {'internalOnly': True, 'simulation': False, 'realPayment': False,
         'releaseAllowed': False, 'productionPaymentRecognized': False,
         'networkEnabled': False, 'source': 'isolated_workbench_projection'}
TAIPEI = timezone(timedelta(hours=8))
_RECORD_FIELDS = ('caseId', 'name', 'status', 'repairFee', 'pickupFee', 'amountDue',
                  'amountPaid', 'orderNumber', 'paidAt', 'checkedAt', 'quoteVersion', 'revision')
_REFUNDS = {'refunded', 'partially_refunded', 'refunding'}


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _case_id(value):
    try:
        if type(value) is not str or not value.startswith('WB-'):
            raise ValueError()
        parsed = uuid.UUID(value[3:])
        if parsed.version != 4 or str(parsed) != value[3:]:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('付款同步僅接受內部案件識別碼') from None
    return value


def _revision(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError('付款同步版本不正確')
    return value


def _time(value):
    """Missing provider dates stay empty; naive workbench dates are Taipei."""
    if type(value) is not str or not value or len(value) > 64:
        return ''
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TAIPEI)
        return parsed.astimezone(TAIPEI).isoformat(timespec='seconds')
    except (ValueError, OverflowError):
        return ''


def _object(value):
    if type(value) is not str or len(value) > 65536:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if type(parsed) is dict else {}
    except (TypeError, ValueError, RecursionError):
        return {}


def _text(value, maximum):
    if (type(value) is not str or len(value) > maximum
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise ValueError('付款同步文字欄位不正確')
    return value


class PaymentSheetSync:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    @contextmanager
    def _connection(self, write=False):
        with self.connection_factory() as c:
            if not isinstance(c, sqlite3.Connection):
                raise ValueError('付款同步資料庫連線不正確')
            c.row_factory = sqlite3.Row
            for row in c.execute('PRAGMA database_list').fetchall():
                if row['name'] not in ('main', 'temp'):
                    raise ValueError('付款同步不得連接外部資料庫')
                if row['file']:
                    absolute, resolved = os.path.abspath(row['file']), os.path.realpath(row['file'])
                    if (os.path.normcase(absolute) != os.path.normcase(resolved)
                            or os.path.basename(resolved).lower() in ('repairs.db', 'payment-lab.db')
                            or os.stat(resolved).st_nlink > 1):
                        raise ValueError('付款同步必須使用獨立工作台資料庫')
            with c:
                if write and not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                tables = {row['name'] for row in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if any(not name.startswith('wb_') for name in tables):
                    raise ValueError('付款同步不得使用正式案件或其他業務資料庫')
                if not {'wb_cases', 'wb_quotes'} <= tables:
                    raise ValueError('客服工作台尚未初始化')
                yield c

    def init(self):
        with self._connection(True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS wb_payment_sheet_state (
                case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                projection_hash TEXT NOT NULL, record TEXT NOT NULL,
                acked_revision INTEGER NOT NULL DEFAULT 0, receipt TEXT NOT NULL DEFAULT '')''')
            columns = {row['name'] for row in c.execute('PRAGMA table_info(wb_payment_sheet_state)')}
            if 'synced_at' not in columns:
                c.execute("ALTER TABLE wb_payment_sheet_state ADD COLUMN synced_at TEXT NOT NULL DEFAULT ''")
            c.execute('''CREATE TABLE IF NOT EXISTS wb_payment_sheet_outbox (
                case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                projection_hash TEXT NOT NULL, record TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '')''')
        return dict(FLAGS)

    @staticmethod
    def _checks(c, case_id, quote):
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wb_real_order_checks'").fetchone()
        if not exists or quote is None:
            return []
        records = c.execute('''SELECT rowid AS sequence,* FROM wb_real_order_checks
            WHERE case_id=? AND quote_id=? AND quote_version=? ORDER BY rowid DESC''',
            (case_id, quote['id'], quote['version'])).fetchall()
        checked = []
        for row in records:
            response = _object(row['response'])
            result = response.get('result', {})
            facts = result.get('facts', {}) if type(result) is dict else {}
            if not (type(result) is dict and type(facts) is dict
                    and response.get('quoteId') == quote['id']
                    and response.get('orderNumber') == row['order_number']
                    and response.get('internalOnly') is True
                    and response.get('simulation') is False
                    and response.get('readOnly') is True
                    and facts.get('freshProviderLookup') is True
                    and type(facts.get('quoteVersion')) is int
                    and facts.get('quoteVersion') == quote['version']
                    and facts.get('currentQuote') is True):
                continue
            approval = None
            if facts.get('manualRemarkException') is True or facts.get('manualMixedAllocation') is True:
                table = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wb_real_manual_approvals'").fetchone()
                if table:
                    approval = c.execute('''SELECT * FROM wb_real_manual_approvals
                        WHERE quote_id=? AND case_id=? AND order_id=? AND order_number=?''',
                        (quote['id'], case_id, row['order_id'], row['order_number'])).fetchone()
            approved_facts = _object(approval['facts']) if approval else {}
            mixed_approval = bool(approval and approved_facts.get('manualMixedAllocation') is True
                and facts.get('manualMixedAllocation') is True
                and approved_facts.get('repairAllocation') == facts.get('repairAllocation')
                and approved_facts.get('repairAllocatedAmount') == facts.get('repairAllocatedAmount')
                and approved_facts.get('orderTotal') == facts.get('orderTotal'))
            checked.append({'row': row, 'response': response, 'result': result, 'facts': facts,
                            'manualApproval': approval is not None, 'mixedApproval': mixed_approval})
        return checked

    @staticmethod
    def _success(check, due):
        response, result, facts, row = (check[k] for k in ('response', 'result', 'facts', 'row'))
        ordinary_amount = (facts.get('manualMixedAllocation') is not True
            and type(facts.get('orderTotal')) is int and facts['orderTotal'] == due
            and facts.get('productValid') is True and facts.get('amountMatches') is True)
        mixed_amount = (facts.get('manualMixedAllocation') is True and check.get('mixedApproval') is True
            and facts.get('productValid') is False and facts.get('amountMatches') is False
            and facts.get('repairAmountMatches') is True and facts.get('allocationCustomerNameMatches') is True
            and facts.get('remarkCaseMatches') is True and facts.get('remarkNameMatches') is True
            and type(facts.get('repairAllocatedAmount')) is int and facts['repairAllocatedAmount'] == due
            and _valid_repair_allocation(facts.get('repairAllocation'), facts.get('orderTotal'), due))
        return (response.get('source') == 'shopline_api_completed'
                and result.get('state') == row['outcome']
                and ((result.get('state') == 'matched_internal_only' and result.get('code') == 'matched_internal_only')
                     or (result.get('state') == 'duplicate' and result.get('code') == 'already_matched_internal_only'))
                and result.get('reasons') == []
                and facts.get('providerPaymentStatus') == 'completed'
                and (ordinary_amount or mixed_amount)
                and type(facts.get('quoteTotal')) is int and facts['quoteTotal'] == due
                and facts.get('currency') == 'TWD'
                and facts.get('caseSource') in ('snapshot', 'test_intake')
                and all(facts.get(field) is True for field in ('contactPhoneMatches', 'orderCreatedAfterQuote'))
                and ((facts.get('remarkCaseMatches') is True and facts.get('remarkNameMatches') is True)
                     or (facts.get('manualRemarkException') is True and check.get('manualApproval') is True))
                and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', row['order_number'])))

    def _projection(self, c, row):
        data = _object(row['data'])
        number, name = data.get('caseNumber', ''), _text(data.get('name', ''), 100)
        if (data.get('source') not in ('snapshot', 'test_intake') or type(number) is not str
                or re.fullmatch(r'R[0-9]{8}-[0-9]{4,8}', number) is None):
            return None
        quote = c.execute('SELECT * FROM wb_quotes WHERE id=? AND case_id=?',
                          (row['latest_quote_id'], row['id'])).fetchone() if row['latest_quote_id'] else None
        fees, paid, status, order_number, paid_at, checked_at, quote_version = (0, 0, 0), 0, '待核價', '', '', '', 0
        if quote is not None:
            values = _object(quote['data'])
            fee, pickup, due = (values.get(key) for key in ('repairFee', 'pickupFee', 'total'))
            if (quote['status'] != 'active' or type(quote['version']) is not int
                    or quote['version'] != row['version'] or quote['version'] < 1
                    or any(type(val) is not int or not 0 <= val <= 100350 for val in (fee, pickup, due))
                    or pickup != (350 if data.get('pickup') is True else 0)
                    or fee + pickup != due or values.get('currency') != 'TWD'
                    or values.get('caseNumber') != number or values.get('name') != name):
                raise ValueError('目前報價內容不完整，無法同步付款狀態')
            fees, quote_version, status = (fee, pickup, due), quote['version'], '免付款' if due == 0 else '待付款'
            checks = self._checks(c, row['id'], quote)
            if checks:
                checked_at = _time(checks[0]['row']['created_at'])
            success = next((check for check in checks if self._success(check, due)), None) if due else None
            if success:
                status, paid, order_number = '已付款', due, success['row']['order_number']
                paid_at = _time(success['facts'].get('reportedPaidAt', ''))
                # A second mismatched order cannot erase a verified match. A
                # later refund observation of that exact paid order can flag it.
                latest_same = next((check for check in checks
                    if check['row']['order_number'] == order_number
                    and check['row']['order_id'] == success['row']['order_id']), success)
                if latest_same['facts'].get('providerPaymentStatus') in _REFUNDS:
                    status = ('已退款' if latest_same['facts']['providerPaymentStatus'] in ('refunding', 'refunded')
                              else '退款需處理')
                elif (latest_same['facts'].get('providerPaymentStatus') != 'completed'
                      or not self._success(latest_same, due)):
                    status, paid = '需人工核對', 0
                followups = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wb_refund_followups'").fetchone()
                refund = c.execute('SELECT provider_status FROM wb_refund_followups WHERE quote_id=? AND order_id=? AND order_number=?',
                    (quote['id'], success['row']['order_id'], order_number)).fetchone() if followups else None
                if refund:
                    # A later provider flip cannot silently clear a recorded
                    # refund hold, including an administratively closed refund.
                    # Company policy treats provider refunding as operationally
                    # refunded. Keep the actual provider state in its ledger;
                    # this label never manufactures a bank completion time.
                    status, paid = ('已退款' if refund['provider_status'] in ('refunding', 'refunded')
                                    else '退款需處理'), due
            elif due and (row['status'] in ('needs_review', 'simulated_paid')
                          or quote['payment_status'] in ('needs_review', 'simulated_paid')
                          or quote['accepted_order_id']):
                status = '需人工核對'
            elif due and checks:
                last = checks[0]
                # A valid unpaid provider observation is still awaiting payment;
                # every amount, identity or product conflict needs review.
                if (last['result'].get('code') != 'not_completed'
                        or last['result'].get('reasons') != ['not_completed']):
                    status = '需人工核對'
        record = dict(zip(_RECORD_FIELDS, (number, name, status, fees[0], fees[1], fees[2],
            paid, order_number, paid_at, checked_at, quote_version, 0)))
        saved = c.execute('SELECT revision,projection_hash FROM wb_payment_sheet_state WHERE case_id=?', (row['id'],)).fetchone()
        fingerprint = hashlib.sha256(_dump({key: val for key, val in record.items() if key != 'revision'}).encode('utf-8')).hexdigest()
        revision = saved['revision'] + int(saved['projection_hash'] != fingerprint) if saved else 1
        record['revision'] = revision
        return {'caseId': row['id'], 'caseNumber': number, 'name': name,
            'paymentStatus': status, 'repairFee': fees[0], 'pickupFee': fees[1],
            'amountDue': fees[2], 'amountPaid': paid, 'paymentOrderNumber': order_number,
            'paidAt': paid_at, 'checkedAt': checked_at, 'quoteVersion': quote_version,
            'syncRevision': revision, 'source': 'shopline_api_completed' if paid else 'workbench_quote',
            'record': record, 'projectionHash': fingerprint}

    def preview(self, case_id=None):
        if case_id is not None:
            _case_id(case_id)
        with self._connection() as c:
            rows = c.execute('SELECT * FROM wb_cases' + (' WHERE id=?' if case_id else '') + ' ORDER BY rowid',
                             (case_id,) if case_id else ()).fetchall()
            if case_id and not rows:
                raise ValueError('找不到內部案件副本')
            projections = [p for row in rows if (p := self._projection(c, row)) is not None]
            entries = c.execute('''SELECT s.case_id,s.revision,s.acked_revision,s.synced_at,
                o.case_id AS pending_case,o.attempts,o.last_error
                FROM wb_payment_sheet_state s LEFT JOIN wb_payment_sheet_outbox o
                ON s.case_id=o.case_id''' + (' WHERE s.case_id=?' if case_id else '') +
                ' ORDER BY s.rowid', (case_id,) if case_id else ()).fetchall()
            queue = [{'caseId': entry['case_id'], 'revision': entry['revision'],
                'status': ('failed' if entry['attempts'] else 'pending')
                    if entry['pending_case'] else 'synced'
                    if entry['acked_revision'] == entry['revision'] else 'pending',
                'attempts': entry['attempts'] or 0, 'lastError': entry['last_error'] or '',
                'syncedAt': entry['synced_at'] if entry['acked_revision'] == entry['revision'] else ''}
                for entry in entries]
            return {**FLAGS, 'headers': list(HEADERS), 'rows': projections, 'queue': queue,
                    'pendingCount': sum(entry['status'] != 'synced' for entry in queue)}

    def enqueue(self, case_id):
        _case_id(case_id)
        with self._connection(True) as c:
            row = c.execute('SELECT * FROM wb_cases WHERE id=?', (case_id,)).fetchone()
            if row is None:
                raise ValueError('找不到內部案件副本')
            projection = self._projection(c, row)
            if projection is None:
                raise ValueError('付款同步只接受真實案件的內部副本')
            saved = c.execute('SELECT * FROM wb_payment_sheet_state WHERE case_id=?', (case_id,)).fetchone()
            same = saved is not None and saved['projection_hash'] == projection['projectionHash']
            if not same:
                c.execute('''INSERT INTO wb_payment_sheet_state(case_id,revision,projection_hash,record)
                    VALUES(?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,
                    projection_hash=excluded.projection_hash,record=excluded.record''',
                    (case_id, projection['syncRevision'], projection['projectionHash'], _dump(projection['record'])))
                c.execute('''INSERT INTO wb_payment_sheet_outbox(case_id,revision,projection_hash,record)
                    VALUES(?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,
                    projection_hash=excluded.projection_hash,record=excluded.record,attempts=0,last_error='' ''',
                    (case_id, projection['syncRevision'], projection['projectionHash'], _dump(projection['record'])))
            queued = c.execute('SELECT 1 FROM wb_payment_sheet_outbox WHERE case_id=?', (case_id,)).fetchone() is not None
            return {**FLAGS, 'row': projection, 'queued': queued, 'idempotent': same,
                    'revision': projection['syncRevision']}

    def pending(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('付款同步批次筆數不正確')
        with self._connection() as c:
            rows = c.execute('SELECT * FROM wb_payment_sheet_outbox ORDER BY rowid LIMIT ?', (limit,)).fetchall()
            return {**FLAGS, 'rows': [{'caseId': row['case_id'], 'revision': row['revision'],
                'record': _object(row['record']), 'attempts': row['attempts'],
                'lastError': row['last_error']} for row in rows]}

    def ack(self, case_id, revision, receipt):
        _case_id(case_id)
        _revision(revision)
        if type(receipt) is not dict:
            raise ValueError('付款同步回執格式不正確')
        with self._connection(True) as c:
            row = c.execute('SELECT * FROM wb_payment_sheet_state WHERE case_id=?', (case_id,)).fetchone()
            if row is None:
                raise ValueError('找不到付款同步版本')
            record = _object(row['record'])
            if (receipt.get('ok') is not True or receipt.get('caseId') != record.get('caseId')
                    or type(receipt.get('revision')) is not int or receipt['revision'] != revision
                    or receipt.get('action') not in ('inserted', 'updated', 'unchanged')):
                raise ValueError('付款同步回執與傳送資料不符')
            if row['revision'] != revision:
                return {**FLAGS, 'acked': False, 'stale': True, 'revision': row['revision']}
            if receipt.get('status') != record.get('status'):
                raise ValueError('付款同步回執與傳送資料不符')
            safe_receipt = {key: receipt[key] for key in ('caseId', 'revision', 'status', 'action')}
            c.execute('UPDATE wb_payment_sheet_state SET acked_revision=?,receipt=?,synced_at=? WHERE case_id=? AND revision=?',
                      (revision, _dump(safe_receipt), datetime.now(TAIPEI).isoformat(timespec='seconds'), case_id, revision))
            c.execute('DELETE FROM wb_payment_sheet_outbox WHERE case_id=? AND revision=?', (case_id, revision))
            return {**FLAGS, 'acked': True, 'stale': False, 'revision': revision}

    def mark_failed(self, case_id, revision, error='同步失敗'):
        _case_id(case_id)
        _revision(revision)
        # Transport errors can contain response bodies or credentials. Persist
        # only a fixed user-facing error; no provider diagnostics cross here.
        with self._connection(True) as c:
            changed = c.execute('''UPDATE wb_payment_sheet_outbox SET attempts=attempts+1,
                last_error='同步失敗，可重試' WHERE case_id=? AND revision=?''', (case_id, revision)).rowcount
            return {**FLAGS, 'retryable': bool(changed), 'revision': revision}
