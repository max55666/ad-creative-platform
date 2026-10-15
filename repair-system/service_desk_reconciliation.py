"""Local-only observations of freshly read SHOPLINE test orders.

This module performs no network calls and never recognizes a real payment.
Its only writes are wb_real_order_checks and the existing workbench audit.
The provider provenance argument is constructed by the server after its own
read-only provider lookup; browser-supplied orders must never reach this API.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sqlite3
import uuid

from order_matching import normalize_phone


FLAGS = {'internalOnly': True, 'simulation': False, 'readOnly': True,
         'paymentVerified': False, 'settlementVerified': False,
         'productionPaymentRecognized': False, 'realPayment': False,
         'releaseAllowed': False}
TAIPEI = timezone(timedelta(hours=8))
_NUMBER = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_ORDER_ID = re.compile(r'[0-9a-f]{24}\Z')
_CASE_NUMBER = re.compile(r'R[0-9]{8}-[0-9]{4,8}\Z')
_ORDER_FIELDS = ('id', 'orderNumber', 'customerName', 'customerPhone',
    'recipientName', 'recipientPhone', 'address', 'orderRemarks', 'currency',
    'total', 'productValid', 'reportedPaymentStatus', 'reportedPaidAt',
    'createdAt', 'paymentVerified', 'verificationStatus', 'reviewReasons')
MESSAGES = {
    'matched_internal_only': '內測配對成功；SHOPLINE API 回報付款完成，僅記錄本機核對結果，尚未驗證金流入帳，未更新正式案件或放行派車。',
    'already_matched_internal_only': '此訂單與報價已有相同內測配對紀錄，未重複配對或認列付款。',
    'invalid_provenance': '訂單不是本次由伺服器重新唯讀查得，已阻擋配對。',
    'invalid_order': '訂單欄位不完整或格式不正確，已阻擋配對。',
    'invalid_quote': '找不到可核對的本機報價副本，已阻擋配對。',
    'stale_quote_snapshot': '報價副本已變更，請重新整理後再核對。',
    'not_snapshot': '僅接受真實維修案件的本機副本，已阻擋配對。',
    'superseded_quote': '報價不是目前有效版本，已阻擋配對。',
    'quote_not_awaiting_payment': '報價目前不是待付款狀態，已阻擋配對。',
    'no_payment_required': '此報價無須付款，已阻擋付費配對。',
    'invalid_currency': '訂單或報價不是新臺幣，已阻擋配對。',
    'amount_mismatch': '訂單金額與目前核定金額不同，已阻擋配對。',
    'invalid_product': '訂單商品、數量或金額組成不符維修一元商品規則，已阻擋配對。',
    'provider_review_required': 'SHOPLINE 訂單有待核對的異常欄位，已阻擋配對。',
    'not_completed': 'SHOPLINE 尚未回報此訂單付款完成，已阻擋配對。',
    'refunded': 'SHOPLINE 回報退款或退款處理中，已阻擋配對。',
    'untrusted_payment_assertion': '訂單含有不適用的付款驗證主張，已阻擋配對。',
    'invalid_order_time': '缺少可核對的訂單或報價時間，已阻擋配對。',
    'order_predates_quote': '訂單建立時間早於本次核定報價，已阻擋配對。',
    'missing_remark': '訂單備註須包含送修編號與申請人姓名兩個標籤，已阻擋配對。',
    'conflicting_remark': '訂單備註包含多筆或衝突資料，已阻擋配對。',
    'case_mismatch': '訂單備註的送修編號與案件副本不同，已阻擋配對。',
    'name_mismatch': '訂單備註的申請人姓名與案件副本不同，已阻擋配對。',
    'phone_mismatch': '訂購人或收件人電話未與案件電話吻合，已阻擋配對。',
    'order_already_bound': '同一筆 SHOPLINE 訂單已有其他報價或版本的內測配對紀錄，已阻擋重用。',
    'quote_already_bound': '此報價已有其他 SHOPLINE 訂單的內測配對紀錄，已阻擋重複付款配對。',
}


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _request_id(value):
    try:
        parsed = uuid.UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('請提供有效的內測核對請求識別碼') from None
    return value


def _identifier(value, prefix):
    try:
        return type(value) is str and value.startswith(prefix) and bool(_request_id(value[len(prefix):]))
    except ValueError:
        return False


def _time(value, local=False):
    if type(value) is not str or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=TAIPEI) if local else None
        return parsed if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _text(value, maximum=200):
    return (value if type(value) is str and len(value) <= maximum
            and all(ord(ch) >= 32 and ord(ch) != 127 for ch in value) else '')


def _remark(value):
    """Require the exact two visible labels and reject extra identifiers."""
    if type(value) is not str or len(value) > 2000:
        return '', '', 'missing_remark'
    value = value.replace('\r\n', '\n')
    lines = value.split('\n')
    if (len(lines) != 2 or any(not line for line in lines)
            or not lines[0].startswith('送修編號：')
            or not lines[1].startswith('申請人姓名：')):
        labelled = value.count('送修編號') + value.count('申請人姓名')
        return '', '', 'conflicting_remark' if labelled >= 2 else 'missing_remark'
    case_number, name = lines[0][5:], lines[1][6:]
    if (_CASE_NUMBER.fullmatch(case_number) is None or not _text(name, 100)
            or len(re.findall(r'R[0-9]{8}-[0-9]{4,8}', value)) != 1
            or value.count('送修編號：') != 1 or value.count('申請人姓名：') != 1):
        return '', '', 'conflicting_remark'
    return case_number, name, ''


class RealOrderReconciliation:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    @contextmanager
    def _connection(self, write=False):
        with self.connection_factory() as c:
            if not isinstance(c, sqlite3.Connection):
                raise ValueError('內測核對資料庫連線不正確')
            c.row_factory = sqlite3.Row
            for row in c.execute('PRAGMA database_list').fetchall():
                if row['name'] not in ('main', 'temp'):
                    raise ValueError('內測核對不得連接外部資料庫')
                if row['file']:
                    absolute, resolved = os.path.abspath(row['file']), os.path.realpath(row['file'])
                    if (os.path.normcase(absolute) != os.path.normcase(resolved)
                            or os.path.basename(resolved).lower() in ('repairs.db', 'payment-lab.db')
                            or os.stat(resolved).st_nlink > 1):
                        raise ValueError('內測核對必須使用獨立客服工作台資料庫')
            with c:
                if write and not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                tables = {row['name'] for row in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if any(not name.startswith('wb_') for name in tables):
                    raise ValueError('內測核對不得使用正式案件或其他業務資料庫')
                if not {'wb_cases', 'wb_quotes', 'wb_audit'} <= tables:
                    raise ValueError('客服工作台尚未初始化')
                yield c

    def init(self):
        with self._connection(True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS wb_real_order_checks (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL, order_id TEXT NOT NULL,
                order_number TEXT NOT NULL, quote_id TEXT NOT NULL,
                case_id TEXT NOT NULL, quote_version INTEGER NOT NULL,
                outcome TEXT NOT NULL, response TEXT NOT NULL,
                created_at TEXT NOT NULL)''')
            for field in ('order_id', 'order_number', 'quote_id'):
                c.execute('CREATE UNIQUE INDEX IF NOT EXISTS wb_real_success_' + field +
                          ' ON wb_real_order_checks(' + field +
                          ") WHERE outcome='matched_internal_only'")
            c.execute('CREATE INDEX IF NOT EXISTS wb_real_quote_checks ON wb_real_order_checks(quote_id,created_at)')
        return dict(FLAGS)

    @staticmethod
    def _context(c, wrapper):
        if type(wrapper) is not dict or type(wrapper.get('quote')) is not dict or type(wrapper.get('case')) is not dict:
            return None, 'invalid_quote'
        quote, case = wrapper['quote'], wrapper['case']
        if not _identifier(quote.get('id'), 'WQ-') or not _identifier(case.get('id'), 'WB-'):
            return None, 'invalid_quote'
        q = c.execute('SELECT * FROM wb_quotes WHERE id=?', (quote['id'],)).fetchone()
        r = c.execute('SELECT * FROM wb_cases WHERE id=?', (case['id'],)).fetchone()
        if q is None or r is None or q['case_id'] != r['id']:
            return None, 'invalid_quote'
        q_data, c_data = json.loads(q['data']), json.loads(r['data'])
        canonical_quote = {**q_data, 'id': q['id'], 'caseId': q['case_id'],
            'version': q['version'], 'status': q['status'], 'paymentStatus': q['payment_status'],
            'acceptedOrderId': q['accepted_order_id'], 'createdAt': q['created_at']}
        canonical_case = {**c_data, 'id': r['id'], 'version': r['version'],
            'status': r['status'], 'latestQuoteId': r['latest_quote_id']}
        context = {'quote': canonical_quote, 'case': canonical_case}
        for part in (wrapper, quote, case):
            if any(part.get(key) is not val for key, val in (
                    ('internalOnly', True), ('simulation', True),
                    ('realPayment', False), ('releaseAllowed', False))):
                return context, 'invalid_quote'
        for key in ('caseId', 'version', 'status', 'paymentStatus', 'total',
                    'currency', 'caseNumber', 'name', 'createdAt'):
            if quote.get(key) != canonical_quote.get(key):
                return context, 'stale_quote_snapshot'
        for key in ('source', 'caseNumber', 'name', 'phone', 'version', 'status'):
            if case.get(key) != canonical_case.get(key):
                return context, 'stale_quote_snapshot'
        if (type(case.get('latestQuote')) is not dict
                or case['latestQuote'].get('id') != r['latest_quote_id']):
            return context, 'stale_quote_snapshot'
        return context, ''

    @staticmethod
    def _decision(order, context, context_error, provenance):
        reasons, facts = [], {}
        def reject(code):
            if code not in reasons:
                reasons.append(code)
        if (type(provenance) is not dict or provenance.get('freshProviderLookup') is not True
                or provenance.get('readOnly') is not True):
            reject('invalid_provenance')
        if context_error:
            reject(context_error)
        if type(order) is not dict:
            order = {}
        identity, number = order.get('id'), order.get('orderNumber')
        if (type(identity) is not str or _ORDER_ID.fullmatch(identity) is None
                or type(number) is not str or _NUMBER.fullmatch(number) is None):
            reject('invalid_order')
        total, currency = order.get('total'), order.get('currency')
        if type(total) is not int or not 1 <= total <= 100000:
            reject('invalid_order')
        if currency != 'TWD':
            reject('invalid_currency')
        if order.get('paymentVerified') is not False:
            reject('untrusted_payment_assertion')
        if order.get('productValid') is not True:
            reject('invalid_product')
        reviews = order.get('reviewReasons')
        if type(reviews) is not list or reviews:
            reject('provider_review_required')
        reported = order.get('reportedPaymentStatus')
        if reported in ('refunded', 'partially_refunded', 'refunding'):
            reject('refunded')
        elif reported != 'completed':
            reject('not_completed')
        facts.update({'orderTotal': total if type(total) is int else None,
            'currency': currency if currency in ('TWD', 'USD', 'JPY') else '',
            'providerPaymentStatus': reported if reported in ('completed', 'pending', 'failed', 'expired',
                'temp', 'refunded', 'partially_refunded', 'refunding') else 'unknown',
            'productValid': order.get('productValid') is True,
            'freshProviderLookup': type(provenance) is dict and provenance.get('freshProviderLookup') is True})
        paid_at = _time(order.get('reportedPaidAt'))
        facts['reportedPaidAt'] = paid_at.isoformat() if paid_at else ''
        if context:
            quote, case = context['quote'], context['case']
            if case.get('source') != 'snapshot':
                reject('not_snapshot')
            if quote['status'] != 'active' or case['latestQuoteId'] != quote['id']:
                reject('superseded_quote')
            if (quote['paymentStatus'] != 'awaiting_payment' or case['status'] != 'awaiting_payment'
                    or quote['acceptedOrderId']):
                reject('quote_not_awaiting_payment')
            if type(quote.get('total')) is not int or not 1 <= quote['total'] <= 100000:
                reject('no_payment_required')
            if quote.get('currency') != 'TWD':
                reject('invalid_currency')
            if total != quote.get('total') or type(total) is not int:
                reject('amount_mismatch')
            quote_time, order_time = _time(quote.get('createdAt'), local=True), _time(order.get('createdAt'))
            if not quote_time or not order_time:
                reject('invalid_order_time')
            elif order_time < quote_time:
                reject('order_predates_quote')
            remark_case, remark_name, remark_error = _remark(order.get('orderRemarks'))
            if remark_error:
                reject(remark_error)
            else:
                if remark_case != case.get('caseNumber'):
                    reject('case_mismatch')
                if remark_name != case.get('name'):
                    reject('name_mismatch')
            case_phone = normalize_phone(case.get('phone'))
            phones = [normalize_phone(order.get(field)) for field in ('customerPhone', 'recipientPhone')]
            phone_match = bool(case_phone and case_phone in phones)
            if not phone_match:
                reject('phone_mismatch')
            facts.update({'quoteTotal': quote.get('total'), 'quoteVersion': quote['version'],
                'caseSource': case.get('source', ''), 'currentQuote': case['latestQuoteId'] == quote['id'],
                'amountMatches': type(total) is int and total == quote.get('total'),
                'remarkCaseMatches': not remark_error and remark_case == case.get('caseNumber'),
                'remarkNameMatches': not remark_error and remark_name == case.get('name'),
                'contactPhoneMatches': phone_match,
                'customerNameDiffers': bool(_text(order.get('customerName'))) and order.get('customerName') != case.get('name'),
                'recipientNameDiffers': bool(_text(order.get('recipientName'))) and order.get('recipientName') != case.get('name'),
                'orderCreatedAfterQuote': bool(quote_time and order_time and order_time >= quote_time)})
        code = reasons[0] if reasons else 'matched_internal_only'
        return {**FLAGS, 'source': 'shopline_api_completed' if not reasons else 'shopline_api_observation',
            'result': {'state': 'blocked' if reasons else 'matched_internal_only', 'code': code,
                'message': MESSAGES[code], 'reasons': reasons, 'facts': facts}}

    def assess(self, order, quote_wrapper, *, provenance):
        with self._connection() as c:
            context, error = self._context(c, quote_wrapper)
            return self._decision(order, context, error, provenance)

    @staticmethod
    def _reference(wrapper):
        quote = wrapper.get('quote', {}) if type(wrapper) is dict else {}
        case = wrapper.get('case', {}) if type(wrapper) is dict else {}
        quote = quote if type(quote) is dict else {}
        case = case if type(case) is dict else {}
        return (quote.get('id', '') if _identifier(quote.get('id'), 'WQ-') else '',
                case.get('id', '') if _identifier(case.get('id'), 'WB-') else '')

    @staticmethod
    def _fingerprint(order, wrapper, provenance):
        scoped_order = {key: order.get(key) for key in _ORDER_FIELDS} if type(order) is dict else None
        try:
            payload = _dump({'order': scoped_order, 'quote': wrapper,
                             'provenance': provenance})
            if len(payload.encode('utf-8')) > 65536:
                raise ValueError()
            return hashlib.sha256(payload.encode('utf-8')).hexdigest()
        except (TypeError, ValueError, RecursionError, UnicodeError):
            raise ValueError('內測核對資料格式不正確') from None

    def lookup(self, request_id, quote_id, order_number):
        _request_id(request_id)
        if not _identifier(quote_id, 'WQ-') or type(order_number) is not str or _NUMBER.fullmatch(order_number) is None:
            raise ValueError('內測核對識別資料不正確')
        with self._connection() as c:
            row = c.execute('SELECT quote_id,order_number,response FROM wb_real_order_checks WHERE request_id=?', (request_id,)).fetchone()
            if row is None:
                return None
            if row['quote_id'] != quote_id or row['order_number'] != order_number:
                raise ValueError('相同內測核對請求不可更換報價或訂單')
            return {**json.loads(row['response']), 'idempotent': True}

    def record(self, order, quote_wrapper, request_id, *, provenance):
        _request_id(request_id)
        fingerprint = self._fingerprint(order, quote_wrapper, provenance)
        quote_id, case_id = self._reference(quote_wrapper)
        with self._connection(True) as c:
            previous = c.execute('SELECT * FROM wb_real_order_checks WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if previous['payload_hash'] != fingerprint:
                    raise ValueError('相同內測核對請求的內容不同，請重新整理後再試')
                return {**json.loads(previous['response']), 'idempotent': True}
            context, error = self._context(c, quote_wrapper)
            response = self._decision(order, context, error, provenance)
            identity = order.get('id', '') if type(order) is dict else ''
            number = order.get('orderNumber', '') if type(order) is dict else ''
            identity = identity if type(identity) is str and _ORDER_ID.fullmatch(identity) else ''
            number = number if type(number) is str and _NUMBER.fullmatch(number) else ''
            if response['result']['state'] == 'matched_internal_only':
                prior_order = c.execute("SELECT quote_id,order_id,order_number FROM wb_real_order_checks WHERE outcome='matched_internal_only' AND (order_id=? OR order_number=?)", (identity, number)).fetchone()
                prior_quote = c.execute("SELECT order_id,order_number FROM wb_real_order_checks WHERE outcome='matched_internal_only' AND quote_id=?", (quote_id,)).fetchone()
                code = ''
                if prior_order:
                    code = ('already_matched_internal_only' if prior_order['quote_id'] == quote_id
                            and prior_order['order_id'] == identity and prior_order['order_number'] == number
                            else 'order_already_bound')
                elif prior_quote:
                    code = 'quote_already_bound'
                if code:
                    response['result'].update({'state': 'duplicate' if code == 'already_matched_internal_only' else 'blocked',
                        'code': code, 'message': MESSAGES[code], 'reasons': [] if code == 'already_matched_internal_only' else [code]})
            check_id, now = 'WRC-' + str(uuid.uuid4()), datetime.now(TAIPEI).strftime('%Y-%m-%d %H:%M:%S')
            response.update({'checkId': check_id, 'requestId': request_id, 'quoteId': quote_id,
                'orderNumber': number, 'createdAt': now, 'idempotent': False})
            c.execute('''INSERT INTO wb_real_order_checks(id,request_id,payload_hash,order_id,
                order_number,quote_id,case_id,quote_version,outcome,response,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (check_id, request_id, fingerprint, identity,
                number, quote_id, case_id, context['quote']['version'] if context else 0,
                response['result']['state'], _dump(response), now))
            if context:
                c.execute('INSERT INTO wb_audit(case_id,action,detail,created_at) VALUES(?,?,?,?)',
                    (case_id, 'real_order_check_' + response['result']['state'],
                     '真實測試訂單本機核對：' + response['result']['message'], now))
            return response

    def history(self, quote_id=None):
        if quote_id is not None and not _identifier(quote_id, 'WQ-'):
            raise ValueError('內測報價識別碼不正確')
        with self._connection() as c:
            rows = c.execute('SELECT response FROM wb_real_order_checks' +
                (' WHERE quote_id=?' if quote_id is not None else '') +
                ' ORDER BY rowid DESC LIMIT 100', (quote_id,) if quote_id is not None else ()).fetchall()
            checks = [json.loads(row['response']) for row in rows]
            return {**FLAGS, 'checks': checks, 'latest': checks[0] if checks else None}
