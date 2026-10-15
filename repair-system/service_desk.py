"""Isolated customer-service rehearsal; no network or production writes.

All cases, quotes, orders and LINE attempts live in a dedicated wb_* SQLite
database. Real provider orders can be compared in memory, never recognized as
payments here. Public identifiers are UUIDs, not production repair IDs.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import uuid

from order_matching import rank_candidates, normalize_phone


FLAGS = {'enabled': True, 'simulation': True, 'internalOnly': True,
         'realPayment': False, 'releaseAllowed': False, 'realNotifications': False}
PAYMENT_URL = 'https://www.zoko.com.tw/products/petpivot-maintenance-1'
SCENARIOS = ('paid', 'pending', 'underpaid', 'overpaid', 'missing_case',
             'missing_name', 'wrong_case', 'refunded', 'duplicate', 'old_quote',
             'missing_evidence', 'mixed_cart')
STATUSES = ('waiting_quote', 'awaiting_payment', 'needs_review',
            'simulated_paid', 'no_payment_required')
_LIVE_REVIEW_REASONS = frozenset({
    'invalid_order_number', 'non_twd', 'missing_currency', 'invalid_total',
    'mixed_cart', 'unsupported_item_type', 'invalid_unit_price',
    'invalid_quantity', 'invalid_item_total', 'order_total_mismatch',
    'invalid_payment_total', 'payment_total_mismatch', 'unknown_payment_status',
})
TAIPEI = timezone(timedelta(hours=8))
MESSAGES = {
    'verified': '合成付款已核對成功；僅更新內部演練，不放行正式維修或派車。',
    'pending': '合成訂單尚未付款。',
    'superseded_quote': '此為已失效的舊版報價，付款交由人工核對。',
    'amount_mismatch': '訂單金額與目前核定金額不同，交由人工核對。',
    'missing_remark': '訂單缺少送修編號或申請人姓名，請確認後人工配對。',
    'case_mismatch': '訂單明確填寫的送修編號或姓名不同，已阻擋配對。',
    'missing_evidence': '缺少合成金流付款佐證，不能只用訂單狀態認列付款。',
    'mixed_cart': '訂單含有其他商品，無法認列本次維修付款。',
    'refunded': '合成訂單已退款，不能認列為已付款。',
    'duplicate': '已識別重複訂單，未重複計入付款。',
    'already_paid': '此報價已有另一筆合成付款，須人工處理重複付款。',
    'no_payment_required': '此案件為免付款核定，不建立付款訂單。',
}


def _now():
    return datetime.now(TAIPEI).strftime('%Y-%m-%d %H:%M:%S')


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('客服演練欄位不正確')
    try:
        if len(_dump(value).encode('utf-8')) > 16384:
            raise ValueError('客服演練資料過長')
    except (TypeError, UnicodeError, RecursionError):
        raise ValueError('客服演練資料格式不正確') from None
    return value


def _text(value, maximum=200, minimum=0):
    if (not isinstance(value, str) or not minimum <= len(value) <= maximum
            or any(ord(ch) < 32 or ord(ch) == 127 or unicodedata.category(ch) == 'Cs' for ch in value)):
        raise ValueError('客服演練文字格式不正確')
    return value.strip()


def _int(value, maximum=100000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('請填寫範圍內的新臺幣整數')
    return value


def _boolean(value):
    if type(value) is not bool:
        raise ValueError('客服演練選項須為布林值')
    return value


def _id(value, prefix):
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError('僅接受內部客服演練識別碼')
    _request_id(value[len(prefix):])
    return value


def _request_id(value):
    try:
        parsed = uuid.UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('請提供有效的演練請求識別碼') from None
    return value


def _new(prefix):
    return prefix + str(uuid.uuid4())


def _hash(value):
    return hashlib.sha256(_dump(value).encode('utf-8')).hexdigest()


def _search_text(value):
    return re.sub(r'[\s\-+()]', '', unicodedata.normalize('NFKC', value)).casefold()


class ServiceDesk:
    def __init__(self, connection_factory, *, seed_examples=True):
        self.connection_factory = connection_factory
        self.seed_examples = seed_examples

    @contextmanager
    def _connection(self, write=False):
        with self.connection_factory() as c:
            if not isinstance(c, sqlite3.Connection):
                raise ValueError('客服工作台資料庫連線不正確')
            c.row_factory = sqlite3.Row
            databases = c.execute('PRAGMA database_list').fetchall()
            if any(row['name'] not in ('main', 'temp') for row in databases):
                raise ValueError('客服工作台不得連接外部資料庫')
            for row in databases:
                path = row['file']
                if not path:
                    continue
                absolute, resolved = os.path.abspath(path), os.path.realpath(path)
                if (os.path.normcase(absolute) != os.path.normcase(resolved)
                        or os.path.basename(resolved).lower() in ('repairs.db', 'payment-lab.db')
                        or os.stat(resolved).st_nlink > 1):
                    raise ValueError('客服工作台必須使用獨立資料庫檔案')
            with c:
                if write and not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                if any(not row['name'].startswith('wb_') for row in tables):
                    raise ValueError('客服工作台不得使用正式案件或其他業務資料庫')
                yield c

    def init(self):
        with self._connection(True) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS wb_cases (
                id TEXT PRIMARY KEY, data TEXT NOT NULL,version INTEGER NOT NULL,
                status TEXT NOT NULL,latest_quote_id TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_quotes (
                id TEXT PRIMARY KEY,case_id TEXT NOT NULL,version INTEGER NOT NULL,
                data TEXT NOT NULL,status TEXT NOT NULL,payment_status TEXT NOT NULL,
                accepted_order_id TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,
                UNIQUE(case_id,version))''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_notifications (
                id TEXT PRIMARY KEY,quote_id TEXT NOT NULL,status TEXT NOT NULL,
                error TEXT NOT NULL,created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_orders (
                id TEXT PRIMARY KEY,order_number TEXT NOT NULL UNIQUE,quote_id TEXT NOT NULL,
                case_id TEXT NOT NULL,data TEXT NOT NULL,scenario TEXT NOT NULL,
                outcome TEXT NOT NULL,status TEXT NOT NULL,bound_quote_id TEXT NOT NULL DEFAULT '',
                transaction_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_requests (
                id TEXT PRIMARY KEY,operation TEXT NOT NULL,payload_hash TEXT NOT NULL,
                result_id TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS wb_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL,
                action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS wb_quote_cases ON wb_quotes(case_id,version)')
            c.execute('CREATE INDEX IF NOT EXISTS wb_order_cases ON wb_orders(case_id,created_at)')
            if self.seed_examples and not c.execute('SELECT 1 FROM wb_cases LIMIT 1').fetchone():
                for i, name, phone, address, model, pickup, linked in (
                    (1, '演練王小明', '0900000001', '台北市中正區測試路1號2樓', 'AS11', True, True),
                    (2, '演練林小美', '0900000002', '新北市新莊區測試路2號3樓', 'AS12', False, True),
                    (3, '演練未綁定', '0900000003', '桃園市桃園區測試路3號', 'AS11', True, False),
                    (4, '演練保固案', '0900000004', '台中市西區測試路4號', 'AS13', False, True)):
                    self._insert_case(c, {'caseNumber': 'TEST-R20261015-%04d' % i,
                        'originalOrderNumber': 'TEST-ORDER-%04d' % i, 'name': name,
                        'phone': phone, 'address': address, 'model': model, 'pickup': pickup,
                        'lineLinked': linked, 'lineName': name if linked else '', 'source': 'synthetic'})
        return {**FLAGS}

    @staticmethod
    def _audit(c, case_id, action, detail):
        c.execute('INSERT INTO wb_audit(case_id,action,detail,created_at) VALUES(?,?,?,?)',
                  (case_id, action, detail, _now()))

    @staticmethod
    def _request(c, request_id, operation, payload):
        request_id = _request_id(request_id)
        row = c.execute('SELECT * FROM wb_requests WHERE id=?', (request_id,)).fetchone()
        if row and (row['operation'] != operation or row['payload_hash'] != _hash(payload)):
            raise ValueError('相同請求識別碼的內容不同，請重新整理後再試')
        return row['result_id'] if row else None

    @staticmethod
    def _remember(c, request_id, operation, payload, result_id):
        c.execute('INSERT INTO wb_requests(id,operation,payload_hash,result_id) VALUES(?,?,?,?)',
                  (request_id, operation, _hash(payload), result_id))

    def _insert_case(self, c, data):
        case_id = _new('WB-')
        c.execute('INSERT INTO wb_cases(id,data,version,status,created_at) VALUES(?,?,0,?,?)',
                  (case_id, _dump(data), 'waiting_quote', _now()))
        self._audit(c, case_id, 'case_created', '建立本機合成案件' if data['source'] == 'synthetic' else '建立本機案件副本；未修改正式案件')
        return case_id

    def create_case(self, payload):
        _object(payload, ('requestId', 'caseNumber', 'originalOrderNumber', 'name', 'phone',
            'address', 'model', 'pickup', 'lineLinked', 'lineName', 'source'),
            ('name', 'phone', 'address', 'model', 'pickup', 'lineLinked'))
        name = _text(payload['name'], 100, 1)
        if not name:
            raise ValueError('請填寫演練申請人姓名')
        phone = normalize_phone(_text(payload['phone'], 40, 1))
        if not phone:
            raise ValueError('請填寫有效的臺灣十碼行動電話')
        number = _text(payload.get('caseNumber', ''), 80)
        if number and not re.fullmatch(r'(?:TEST-)?R[0-9]{8}-[0-9]{4,8}', number):
            raise ValueError('案件參考編號格式不正確')
        source = payload.get('source', 'synthetic')
        if source not in ('synthetic', 'snapshot'):
            raise ValueError('案件來源須為合成測試或副本')
        if source == 'synthetic' and number.startswith('R'):
            raise ValueError('正式編號只能作為明確標記的本機副本')
        address, model = _text(payload['address'], 500, 1), _text(payload['model'], 100, 1)
        if not address or not model:
            raise ValueError('請填寫演練回收地址及商品機型')
        data = {'caseNumber': number or ('TEST-R' + datetime.now(TAIPEI).strftime('%Y%m%d') + '-' + '%08d' % (uuid.uuid4().int % 100000000)),
                'originalOrderNumber': _text(payload.get('originalOrderNumber', ''), 100),
                'name': name, 'phone': phone, 'address': address,
                'model': model, 'pickup': _boolean(payload['pickup']),
                'lineLinked': _boolean(payload['lineLinked']), 'lineName': _text(payload.get('lineName', ''), 100),
                'source': source}
        request_id = _request_id(payload.get('requestId', str(uuid.uuid4())))
        with self._connection(True) as c:
            prior = self._request(c, request_id, 'create_case', payload)
            if prior:
                return {**FLAGS, 'case': self._case(c, prior), 'idempotent': True}
            if number and c.execute('SELECT 1 FROM wb_cases WHERE json_extract(data,\'$.caseNumber\')=?', (number,)).fetchone():
                raise ValueError('本機工作台已有相同案件參考編號')
            case_id = self._insert_case(c, data)
            self._remember(c, request_id, 'create_case', payload, case_id)
            return {**FLAGS, 'case': self._case(c, case_id), 'idempotent': False}

    def create_verified_intake(self, payload, identity, request_id):
        """Internal intake; identity must come from the host's verified LINE session."""
        _object(payload, ('name', 'phone', 'address', 'model', 'shipping',
                'originalOrderNumber', 'problem', 'consent'),
                ('name', 'phone', 'address', 'model', 'shipping', 'consent'))
        if type(identity) is not dict:
            raise ValueError('請先完成內測 LINE 身分驗證')
        customer_id = _id(identity.get('customerId'), 'WC-')
        display_name = _text(identity.get('displayName', ''), 100, 1)
        if payload['consent'] is not True or payload['shipping'] not in ('pickup', 'self'):
            raise ValueError('請選擇送修方式並同意內測資料處理')
        name, phone = _text(payload['name'], 100, 1), normalize_phone(_text(payload['phone'], 40, 1))
        address, model = _text(payload['address'], 500, 1), _text(payload['model'], 100, 1)
        if not name or not phone or not address or not model or not display_name:
            raise ValueError('請填寫姓名、有效行動電話、地址與機型')
        request_id = _request_id(request_id)
        request_payload = {'form': payload, 'customerId': customer_id}
        with self._connection(True) as c:
            prior = self._request(c, request_id, 'verified_intake', request_payload)
            if prior:
                return {**FLAGS, 'case': self._case(c, prior), 'idempotent': True}
            counts = c.execute('''SELECT COUNT(*) AS total,
                SUM(CASE WHEN json_extract(data,'$.customerId')=? THEN 1 ELSE 0 END) AS customer_total
                FROM wb_cases WHERE json_extract(data,'$.source')='test_intake' ''', (customer_id,)).fetchone()
            if counts['total'] >= 90 or (counts['customer_total'] or 0) >= 5:
                raise ValueError('內測案件已達數量限制，請聯絡管理員整理既有內測案件')
            c.execute('CREATE TABLE IF NOT EXISTS wb_intake_sequence (day TEXT PRIMARY KEY,sequence INTEGER NOT NULL)')
            day = datetime.now(TAIPEI).strftime('%Y%m%d')
            c.execute('INSERT OR IGNORE INTO wb_intake_sequence(day,sequence) VALUES(?,8999)', (day,))
            while True:
                seq = c.execute('SELECT sequence FROM wb_intake_sequence WHERE day=?', (day,)).fetchone()['sequence'] + 1
                if seq > 9999:
                    raise ValueError('今日內測案件編號已用完')
                c.execute('UPDATE wb_intake_sequence SET sequence=? WHERE day=?', (seq, day))
                number = 'R' + day + '-' + str(seq)
                if not c.execute("SELECT 1 FROM wb_cases WHERE json_extract(data,'$.caseNumber')=?", (number,)).fetchone():
                    break
            data = {'caseNumber': number, 'name': name, 'phone': phone, 'address': address,
                'model': model, 'pickup': payload['shipping'] == 'pickup',
                'originalOrderNumber': _text(payload.get('originalOrderNumber', ''), 100),
                'problem': _text(payload.get('problem', ''), 2000),
                'source': 'test_intake', 'lineLinked': True, 'lineName': display_name,
                'customerId': customer_id}
            case_id = self._insert_case(c, data)
            self._audit(c, case_id, 'verified_test_intake', '經內測 LINE 驗證建立；僅限獨立內測站')
            self._remember(c, request_id, 'verified_intake', request_payload, case_id)
            return {**FLAGS, 'case': self._case(c, case_id), 'idempotent': False}

    def _quote(self, c, quote_id):
        row = c.execute('SELECT * FROM wb_quotes WHERE id=?', (quote_id,)).fetchone()
        if row is None:
            return None
        notifications = c.execute('SELECT * FROM wb_notifications WHERE quote_id=? ORDER BY rowid', (quote_id,)).fetchall()
        last = notifications[-1] if notifications else None
        return {**json.loads(row['data']), 'id': row['id'], 'caseId': row['case_id'],
                'version': row['version'], 'status': row['status'], 'paymentStatus': row['payment_status'],
                'acceptedOrderId': row['accepted_order_id'], 'createdAt': row['created_at'],
                'requiresExplicitResend': False,
                'notification': {'status': last['status'] if last else 'not_sent', 'attempts': len(notifications),
                    'lastError': last['error'] if last else '', 'createdAt': last['created_at'] if last else '',
                    'message': '僅模擬傳送，未發送真實 LINE'}, **FLAGS}

    def _case(self, c, case_id):
        row = c.execute('SELECT * FROM wb_cases WHERE id=?', (case_id,)).fetchone()
        if row is None:
            return None
        return {**json.loads(row['data']), 'id': row['id'], 'version': row['version'],
                'status': row['status'], 'latestQuote': self._quote(c, row['latest_quote_id']) if row['latest_quote_id'] else None,
                'createdAt': row['created_at'], **FLAGS}

    def state(self, query='', status=''):
        query, status = _text(query, 100), _text(status, 30)
        if status and status not in STATUSES:
            raise ValueError('案件狀態篩選不正確')
        with self._connection() as c:
            cases = [self._case(c, row['id']) for row in c.execute('SELECT id FROM wb_cases ORDER BY rowid DESC LIMIT 1000')]
            summary = {'total': len(cases), **{key: sum(case['status'] == key for case in cases) for key in STATUSES}}
            needle = _search_text(normalize_phone(query) or query)
            if needle:
                cases = [case for case in cases if any(needle in _search_text(str(case[key])) for key in
                    ('caseNumber', 'originalOrderNumber', 'name', 'phone', 'address', 'model', 'lineName'))]
            if status:
                cases = [case for case in cases if case['status'] == status]
            return {**FLAGS, 'cases': cases, 'summary': summary, 'scenarios': list(SCENARIOS), 'query': query, 'status': status}

    def get_case(self, case_id):
        _id(case_id, 'WB-')
        with self._connection() as c:
            case = self._case(c, case_id)
            if case is None:
                return None
            quotes = [self._quote(c, row['id']) for row in c.execute('SELECT id FROM wb_quotes WHERE case_id=? ORDER BY version DESC', (case_id,))]
            orders = [self._order(c, row['id']) for row in c.execute('SELECT id FROM wb_orders WHERE case_id=? ORDER BY rowid DESC', (case_id,))]
            audit = [dict(row) for row in c.execute('SELECT id,action,detail,created_at AS createdAt FROM wb_audit WHERE case_id=? ORDER BY id DESC LIMIT 100', (case_id,))]
            return {**FLAGS, 'case': case, 'quotes': quotes, 'orders': orders, 'audit': audit}

    def get_quote(self, quote_id):
        _id(quote_id, 'WQ-')
        with self._connection() as c:
            quote = self._quote(c, quote_id)
            return {**FLAGS, 'quote': quote, 'case': self._case(c, quote['caseId'])} if quote else None

    @staticmethod
    def _message(case, fee, pickup_fee, total):
        remark = '送修編號：' + case['caseNumber'] + '\n申請人姓名：' + case['name']
        if total == 0:
            message = ('【維修免付款通知】\n\n送修編號：' + case['caseNumber'] + '\n申請人：' + case['name'] +
                '\n\n維修費：NT$0\n派車回收費：NT$0\n應付合計：NT$0\n\n本次核定無須付款，請依客服指示安排送修。\n\n如需補充資訊，請直接在此聊天室留言並附上案件編號。')
        else:
            message = ('【維修費用付款通知】\n\n送修編號：' + case['caseNumber'] + '\n申請人：' + case['name'] +
                '\n\n維修費：NT$' + format(fee, ',') + '\n派車回收費：NT$' + format(pickup_fee, ',') +
                '\n應付合計：NT$' + format(total, ',') + '\n\n請至下方一元賣場付款：\n' + PAYMENT_URL +
                '\n購買數量請填「' + str(total) + '」，結帳總額應為 NT$' + format(total, ',') +
                '。\n\n【下單必填】\n請在「訂單備註」貼上以下兩行：\n\n' + remark +
                '\n\n請填本次送修編號，不是原商品購買訂單編號。\n漏填可能延後付款核對與送修安排。\n請勿與其他商品合併下單，亦不適用折扣或購物金。\n\n如需補充資訊，請直接在此聊天室留言並附上案件編號。')
        return message, remark

    def _notify(self, c, case, quote_id, simulate_failure):
        error = ('此案件未綁定 LINE，請先確認客戶連線。' if not case['lineLinked'] else
                 '演練 LINE 傳送失敗，請重試。' if simulate_failure else '')
        c.execute('INSERT INTO wb_notifications(id,quote_id,status,error,created_at) VALUES(?,?,?,?,?)',
                  (_new('WN-'), quote_id, 'failed' if error else 'simulated_sent', error, _now()))
        self._audit(c, case['id'], 'notification_failed' if error else 'notification_simulated',
                    error or '已模擬 LINE 付款通知；未發送真實訊息')

    def approve_quote(self, case_id, payload):
        _id(case_id, 'WB-')
        _object(payload, ('repairFee', 'warranty', 'expectedVersion', 'requestId', 'simulateFailure'),
                ('repairFee', 'warranty', 'expectedVersion', 'requestId'))
        fee, warranty = _int(payload['repairFee']), _boolean(payload['warranty'])
        expected = _int(payload['expectedVersion'], 1000000)
        failure = _boolean(payload.get('simulateFailure', False))
        request_id = _request_id(payload['requestId'])
        if warranty and fee != 0:
            raise ValueError('保固免維修費時，維修費必須為 0 元')
        with self._connection(True) as c:
            previous = self._request(c, request_id, 'approve_quote:' + case_id, payload)
            if previous:
                return {**FLAGS, 'case': self._case(c, case_id), 'quote': self._quote(c, previous), 'idempotent': True}
            case = self._case(c, case_id)
            if case is None:
                raise ValueError('找不到內部演練案件')
            if case['version'] != expected:
                raise ValueError('報價版本已變更，請重新整理案件後再核定')
            if case['latestQuote'] and (case['latestQuote']['acceptedOrderId'] or case['latestQuote']['paymentStatus'] == 'no_payment_required'):
                raise ValueError('已核對付款或免付款的案件不能直接改價，請先交由主管處理')
            real_checks = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wb_real_order_checks'").fetchone()
            if real_checks and case['latestQuote'] and c.execute("SELECT 1 FROM wb_real_order_checks WHERE quote_id=? AND outcome='matched_internal_only' LIMIT 1",
                    (case['latestQuote']['id'],)).fetchone():
                raise ValueError('此報價已有真實訂單配對或退款追蹤，不能直接改價，請先交由主管處理')
            pickup_fee = 350 if case['pickup'] else 0
            total = fee + pickup_fee
            message, remark = self._message(case, fee, pickup_fee, total)
            version, quote_id = case['version'] + 1, _new('WQ-')
            data = {'caseNumber': case['caseNumber'], 'name': case['name'], 'repairFee': fee,
                    'warranty': warranty, 'pickup': case['pickup'], 'pickupFee': pickup_fee,
                    'total': total, 'currency': 'TWD', 'quantity': total,
                    'paymentUrl': PAYMENT_URL if total else '', 'checkoutUrl': PAYMENT_URL if total else '',
                    'clipboardText': remark, 'remarkText': remark, 'message': message, 'messageText': message}
            c.execute("UPDATE wb_quotes SET status='superseded' WHERE case_id=? AND status='active'", (case_id,))
            payment_status = 'awaiting_payment' if total else 'no_payment_required'
            c.execute('INSERT INTO wb_quotes(id,case_id,version,data,status,payment_status,created_at) VALUES(?,?,?,?,?,?,?)',
                      (quote_id, case_id, version, _dump(data), 'active', payment_status, _now()))
            c.execute('UPDATE wb_cases SET version=?,status=?,latest_quote_id=? WHERE id=?',
                      (version, payment_status, quote_id, case_id))
            self._audit(c, case_id, 'quote_approved', '核定第 %d 版：維修費 %d 元、派車費 %d 元、合計 %d 元' % (version, fee, pickup_fee, total))
            self._notify(c, case, quote_id, failure)
            self._remember(c, request_id, 'approve_quote:' + case_id, payload, quote_id)
            return {**FLAGS, 'case': self._case(c, case_id), 'quote': self._quote(c, quote_id), 'idempotent': False}

    def retry_notification(self, quote_id, payload):
        _id(quote_id, 'WQ-')
        _object(payload, ('requestId', 'simulateFailure'), ('requestId',))
        request_id, failure = _request_id(payload['requestId']), _boolean(payload.get('simulateFailure', False))
        with self._connection(True) as c:
            prior = self._request(c, request_id, 'notify:' + quote_id, payload)
            quote = self._quote(c, quote_id)
            if not quote:
                raise ValueError('找不到內部演練報價')
            case = self._case(c, quote['caseId'])
            if prior:
                return {**FLAGS, 'case': case, 'quote': quote, 'idempotent': True}
            if quote['status'] != 'active' or case['latestQuote']['id'] != quote_id:
                raise ValueError('舊版報價已失效，不能重新發送付款通知')
            already_sent = quote['notification']['status'] == 'simulated_sent'
            if not already_sent:
                self._notify(c, case, quote_id, failure)
            self._remember(c, request_id, 'notify:' + quote_id, payload, quote_id)
            return {**FLAGS, 'case': self._case(c, quote['caseId']), 'quote': self._quote(c, quote_id), 'idempotent': already_sent}

    def _candidate_quotes(self, c):
        result = []
        for row in c.execute('SELECT id FROM wb_cases ORDER BY rowid DESC LIMIT 1000'):
            case = self._case(c, row['id'])
            quote = case['latestQuote']
            if quote:
                result.append({'quoteId': quote['id'], 'caseId': case['caseNumber'], 'name': case['name'],
                    'phone': case['phone'], 'address': case['address'], 'total': quote['total'], 'currency': 'TWD',
                    'status': quote['status'], 'paymentStatus': 'paid' if quote['paymentStatus'] == 'simulated_paid' else
                        'unpaid' if quote['paymentStatus'] in ('awaiting_payment', 'needs_review') else quote['paymentStatus']})
        return result

    def _order(self, c, order_id):
        row = c.execute('SELECT * FROM wb_orders WHERE id=?', (order_id,)).fetchone()
        if row is None:
            return None
        data = json.loads(row['data'])
        result = rank_candidates({**data, 'remarkCaseId': data.get('remarkCaseNumber', '')}, self._candidate_quotes(c))
        return {**data, 'id': row['id'], 'orderNumber': row['order_number'], 'quoteId': row['quote_id'],
                'caseId': row['case_id'], 'scenario': row['scenario'], 'outcome': row['outcome'], 'status': row['status'],
                'boundQuoteId': row['bound_quote_id'], 'candidates': result['candidates'], 'matching': result['assessment'],
                'createdAt': row['created_at'], **FLAGS}

    def _assess(self, c, case, quote, order, manual=False):
        if quote['status'] != 'active' or case['latestQuote']['id'] != quote['id'] or order['quoteId'] != quote['id']:
            return 'superseded_quote'
        if quote['total'] == 0:
            return 'no_payment_required'
        if order['reportedPaymentStatus'] == 'refunded':
            return 'refunded'
        if order['reportedPaymentStatus'] != 'paid':
            return 'pending'
        if order['productValid'] is not True:
            return 'mixed_cart'
        if order['currency'] != 'TWD' or order['total'] != quote['total']:
            return 'amount_mismatch'
        if not order['paymentVerified']:
            return 'missing_evidence'
        if ((order['remarkCaseNumber'] and order['remarkCaseNumber'] != case['caseNumber'])
                or (order['remarkName'] and order['remarkName'] != case['name'])):
            return 'case_mismatch'
        if not manual and (not order['remarkCaseNumber'] or not order['remarkName']):
            return 'missing_remark'
        if quote['acceptedOrderId'] and quote['acceptedOrderId'] != order.get('id'):
            return 'already_paid'
        return 'verified'

    def _apply_result(self, c, case, quote, order_id, code):
        accepted = code == 'verified'
        status = 'accepted' if accepted else 'pending' if code == 'pending' else 'refunded' if code == 'refunded' else 'review'
        c.execute('UPDATE wb_orders SET outcome=?,status=?,bound_quote_id=? WHERE id=?',
                  (code, status, quote['id'] if accepted else '', order_id))
        current = quote['status'] == 'active' and case['latestQuote']['id'] == quote['id']
        if accepted:
            c.execute("UPDATE wb_quotes SET payment_status='simulated_paid',accepted_order_id=? WHERE id=?", (order_id, quote['id']))
            c.execute("UPDATE wb_cases SET status='simulated_paid' WHERE id=?", (case['id'],))
        elif current and quote['paymentStatus'] not in ('simulated_paid', 'no_payment_required'):
            state = 'awaiting_payment' if code == 'pending' else 'needs_review'
            c.execute('UPDATE wb_quotes SET payment_status=? WHERE id=?', (state, quote['id']))
            c.execute('UPDATE wb_cases SET status=? WHERE id=?', (state, case['id']))
        self._audit(c, case['id'], 'order_' + code, MESSAGES[code])

    def _order_response(self, c, order_id, code=None, idempotent=False):
        order = self._order(c, order_id)
        code = code or order['outcome']
        return {**FLAGS, 'case': self._case(c, order['caseId']), 'quote': self._quote(c, order['quoteId']),
                'order': order, 'result': {'code': code, 'message': MESSAGES[code], 'accepted': code == 'verified'},
                'idempotent': idempotent}

    def simulate_order(self, quote_id, payload):
        _id(quote_id, 'WQ-')
        _object(payload, ('scenario', 'requestId'), ('scenario', 'requestId'))
        scenario, request_id = payload['scenario'], _request_id(payload['requestId'])
        if scenario not in SCENARIOS:
            raise ValueError('訂單演練情境不正確')
        with self._connection(True) as c:
            prior = self._request(c, request_id, 'simulate:' + quote_id, payload)
            if prior:
                return self._order_response(c, prior, code='duplicate' if scenario == 'duplicate' else None, idempotent=True)
            quote = self._quote(c, quote_id)
            if not quote:
                raise ValueError('找不到內部演練報價')
            case = self._case(c, quote['caseId'])
            if quote['total'] == 0:
                raise ValueError('免付款案件不建立付款訂單')
            if scenario == 'old_quote':
                old = c.execute("SELECT id FROM wb_quotes WHERE case_id=? AND status='superseded' ORDER BY version DESC LIMIT 1", (case['id'],)).fetchone()
                if not old:
                    raise ValueError('請先改價建立新版報價，再測試舊版付款')
                quote = self._quote(c, old['id'])
            if scenario == 'duplicate':
                old = c.execute('SELECT id FROM wb_orders WHERE case_id=? ORDER BY rowid DESC LIMIT 1', (case['id'],)).fetchone()
                if not old:
                    raise ValueError('請先建立一筆演練訂單再測試重複')
                self._remember(c, request_id, 'simulate:' + quote_id, payload, old['id'])
                return self._order_response(c, old['id'], code='duplicate', idempotent=True)
            if scenario == 'refunded' and quote['acceptedOrderId']:
                order_id = quote['acceptedOrderId']
                row = c.execute('SELECT data FROM wb_orders WHERE id=?', (order_id,)).fetchone()
                data = json.loads(row['data'])
                data['reportedPaymentStatus'] = 'refunded'
                data['paymentVerified'] = False
                c.execute("UPDATE wb_orders SET data=?,outcome='refunded',status='refunded' WHERE id=?", (_dump(data), order_id))
                c.execute("UPDATE wb_quotes SET payment_status='refunded' WHERE id=?", (quote['id'],))
                c.execute("UPDATE wb_cases SET status='needs_review' WHERE id=?", (case['id'],))
                self._audit(c, case['id'], 'order_refunded', MESSAGES['refunded'])
                self._remember(c, request_id, 'simulate:' + quote_id, payload, order_id)
                return self._order_response(c, order_id)
            order_id = _new('WO-')
            data = {'quoteId': quote['id'], 'customerName': case['name'], 'customerPhone': case['phone'],
                    'address': case['address'], 'remarkCaseNumber': '' if scenario == 'missing_case' else
                        'TEST-R20990101-9999' if scenario == 'wrong_case' else case['caseNumber'],
                    'remarkName': '' if scenario == 'missing_name' else case['name'],
                    'total': max(0, quote['total'] - 1) if scenario == 'underpaid' else quote['total'] + 1 if scenario == 'overpaid' else quote['total'],
                    'currency': 'TWD', 'reportedPaymentStatus': 'pending' if scenario == 'pending' else 'refunded' if scenario == 'refunded' else 'paid',
                    'paymentVerified': scenario not in ('pending', 'missing_evidence', 'refunded'), 'productValid': scenario != 'mixed_cart',
                    'verificationSource': 'synthetic_gateway_fixture', 'rawRemark': ''}
            data['rawRemark'] = '\n'.join(filter(None, ('送修編號：' + data['remarkCaseNumber'] if data['remarkCaseNumber'] else '',
                                                       '申請人姓名：' + data['remarkName'] if data['remarkName'] else '')))
            number = 'SIM-' + uuid.uuid4().hex[:16].upper()
            c.execute('INSERT INTO wb_orders(id,order_number,quote_id,case_id,data,scenario,outcome,status,transaction_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (order_id, number, quote['id'], case['id'], _dump(data), scenario, 'pending', 'pending', _new('SIMTX-'), _now()))
            code = self._assess(c, case, quote, {**data, 'id': order_id})
            self._apply_result(c, case, quote, order_id, code)
            self._remember(c, request_id, 'simulate:' + quote_id, payload, order_id)
            return self._order_response(c, order_id)

    def bind_order(self, order_id, payload):
        _id(order_id, 'WO-')
        _object(payload, ('quoteId', 'reason', 'confirm', 'requestId'), ('quoteId', 'reason', 'confirm', 'requestId'))
        quote_id, request_id = _id(payload['quoteId'], 'WQ-'), _request_id(payload['requestId'])
        reason = _text(payload['reason'], 500, 8)
        if len(reason) < 8 or payload['confirm'] is not True:
            raise ValueError('請確認客戶與訂單關係，並填寫至少 8 字的人工配對原因')
        with self._connection(True) as c:
            prior = self._request(c, request_id, 'bind:' + order_id, payload)
            if prior:
                return self._order_response(c, order_id, idempotent=True)
            order, quote = self._order(c, order_id), self._quote(c, quote_id)
            if not order or not quote:
                raise ValueError('找不到演練訂單或報價')
            if order['boundQuoteId'] and order['boundQuoteId'] != quote_id:
                raise ValueError('同一筆訂單不能配對多份報價')
            case = self._case(c, quote['caseId'])
            # A receipt retains its immutable source quote/version. Human
            # confirmation cannot bypass a superseded quote or cross-case order.
            if order['caseId'] != case['id']:
                raise ValueError('此合成收據來源屬於另一案件，不能跨案件強制配對')
            code = self._assess(c, case, quote, order, manual=True)
            if code != 'verified':
                raise ValueError(MESSAGES[code])
            if order['boundQuoteId'] != quote_id:
                self._apply_result(c, case, quote, order_id, code)
                self._audit(c, case['id'], 'manual_bind', '人工配對原因：' + reason)
            self._remember(c, request_id, 'bind:' + order_id, payload, order_id)
            return self._order_response(c, order_id, idempotent=order['boundQuoteId'] == quote_id)

    def compare_live_orders(self, orders):
        if not isinstance(orders, list) or len(orders) > 100:
            raise ValueError('真實唯讀訂單數量不正確')
        result = []
        with self._connection() as c:
            candidates = self._candidate_quotes(c)
            for order in orders:
                if not isinstance(order, dict):
                    raise ValueError('真實唯讀訂單格式不正確')
                # Never propagate credentials, payment/card payloads, caller
                # supplied verification or arbitrary fields into this view.
                safe = {key: _text(order.get(key, '') or '', maximum) for key, maximum in (
                    ('id', 100), ('orderNumber', 100), ('customerName', 200), ('customerPhone', 40),
                    ('recipientName', 200), ('recipientPhone', 40), ('currency', 3),
                    ('reportedPaymentStatus', 40), ('createdAt', 100), ('reportedPaidAt', 100))}
                remarks = order.get('orderRemarks', '') or ''
                if (not isinstance(remarks, str) or len(remarks) > 4000
                        or any(ord(ch) < 32 and ch not in '\n\r\t' for ch in remarks)):
                    raise ValueError('真實唯讀訂單備註格式不正確')
                safe['orderRemarks'] = remarks
                address = order.get('address', '') or ''
                safe['address'] = ({key: _text(address.get(key, '') or '', 500) for key in
                    ('countryCode', 'city', 'district', 'address1', 'address2', 'postcode')}
                    if isinstance(address, dict) else _text(address, 500))
                amount = order.get('total')
                safe['total'] = amount if type(amount) is int and 0 <= amount <= 100000000 else None
                safe['productValid'] = order.get('productValid') is True
                # Only fixed diagnostic codes can cross this boundary, never
                # arbitrary provider text or nested payment/credential data.
                review_reasons = order.get('reviewReasons')
                safe['reviewReasons'] = (list(dict.fromkeys(reason for reason in review_reasons[:100]
                    if type(reason) is str and reason in _LIVE_REVIEW_REASONS))
                    if type(review_reasons) is list else [])
                safe.update({'paymentVerified': False, 'verificationStatus': 'not_verified'})
                remark = safe.get('orderRemarks')
                references = re.findall(r'(?<![A-Za-z0-9])(?:TEST-)?R[0-9]{8}-[0-9]{4,8}(?![A-Za-z0-9])', remark) if isinstance(remark, str) else []
                matching = rank_candidates({**safe, 'remarkCaseId': references[0] if len(set(references)) == 1 else ''}, candidates)
                result.append({**safe, 'candidates': matching['candidates'], 'matching': matching,
                    'readOnly': True, 'automaticBindingEnabled': False, 'realPayment': False,
                    'releaseAllowed': False, 'internalOnly': True})
        return {**FLAGS, 'simulation': False, 'readOnly': True, 'orders': result,
                'automaticBindingEnabled': False, 'matchingScope': 'identity_suggestions_only'}
