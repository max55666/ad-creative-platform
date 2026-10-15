"""Offline payment rehearsal. This module cannot charge or release a repair.

The caller must provide a context-managed SQLite connection to a *dedicated*
laboratory database. No server, provider, customer, LINE, or dispatch imports
are permitted here. Every public result explicitly describes a simulation.
"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import sqlite3
import uuid
from order_matching import rank_candidates


MAX_AMOUNT = 100000
MAX_JSON_BYTES = 16384
PRODUCT_ID = 'SIMULATED-REPAIR-ONE-TWD'
PRODUCT_SKU = 'LAB-REPAIR-1TWD'
PROVIDER = 'SHOPLINE_SIMULATION'
TAIPEI = timezone(timedelta(hours=8))
FLAGS = {'enabled': True, 'simulation': True, 'internalOnly': True,
         'realPayment': False, 'releaseAllowed': False}
SCENARIOS = ('paid', 'pending', 'failed', 'cancelled', 'refund', 'duplicate',
             'underpaid', 'amount_mismatch', 'invalid_currency', 'wrong_sku',
             'mixed_cart', 'wrong_case', 'wrong_quote_version',
             'late_old_quote', 'missing_evidence')
RECEIPT_SCENARIOS = ('missing_case', 'missing_name', 'missing_both',
                     'different_payer', 'unpaid', 'refunded', 'wrong_amount',
                     'address_mismatch', 'missing_address', 'phone_format')


def _now():
    return datetime.now(TAIPEI).strftime('%Y-%m-%d %H:%M:%S')


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _object(value, allowed, required=(), max_bytes=MAX_JSON_BYTES):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('內部演練資料欄位不正確')
    try:
        encoded = _dump(value).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValueError('內部演練資料格式不正確') from None
    if len(encoded) > max_bytes:
        raise ValueError('內部演練資料超過大小限制')
    return value


def _text(value, length, minimum=1):
    if (not isinstance(value, str) or not minimum <= len(value) <= length
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError('內部演練文字格式不正確')
    return value


def _integer(value, minimum=0, maximum=MAX_AMOUNT):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('演練金額須為範圍內的新臺幣整數')
    return value


def _uuid(value):
    _text(value, 36)
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError('演練識別碼格式不正確') from None
    if str(parsed) != value or parsed.version != 4:
        raise ValueError('演練識別碼格式不正確')
    return value


def _synthetic_id(value, prefix):
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError('僅接受合成演練識別碼')
    _uuid(value[len(prefix):])
    return value


def _hash(value):
    return hashlib.sha256(_dump(value).encode('utf-8')).hexdigest()


def _phone(value):
    _text(value, 40, 0)
    normalized = re.sub(r'[\s-]', '', value)
    if normalized and not re.fullmatch(r'09[0-9]{8}', normalized):
        raise ValueError('演練電話須為臺灣十碼行動電話或留白')
    return normalized


class _BindingRejected(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


MESSAGES = {
    'verified': '演練付款驗證通過；未實際收款，未放行任何真實案件或派車。',
    'pending': '演練訂單尚未付款，不放行。',
    'failed': '演練付款失敗，不放行。',
    'cancelled': '演練訂單已取消，不放行。',
    'refunded': '演練退款已核對；不放行，真實收退款未發生。',
    'no_payment_required': '演練免付款；未放行任何真實案件，保固資格仍須另行核准。',
    'zero_amount_order': '演練總額為零，應走內部免付款紀錄；不建立外部訂單，未放行任何真實案件。',
    'duplicate': '重複演練訂單已辨識，未重複計入付款或放行。',
    'no_prior_order': '尚無演練訂單可供重複測試，不放行。',
    'order_id_reused': '演練訂單編號被用於不同內容，已阻擋，不放行。',
    'superseded_quote': '舊版演練報價已失效；舊連結付款不放行新版，須人工核對。',
    'case_mismatch': '演練訂單案件編號不符，不放行。',
    'quote_mismatch': '演練訂單報價識別碼不符，不放行。',
    'version_mismatch': '演練訂單報價版本不符，不放行。',
    'currency_mismatch': '演練訂單幣別不符，僅接受新臺幣，不放行。',
    'cart_mismatch': '演練訂單必須只含指定的一元維修商品，且數量須符合報價，不放行。',
    'amount_mismatch': '演練訂單總額與報價不符，不放行。',
    'paid_amount_mismatch': '演練實付金額與應付金額不符，不放行。',
    'missing_evidence': '缺少有效的演練金流付款佐證，不把訂單狀態當作已付款，不放行。',
    'refund_without_payment': '找不到此訂單先前已通過驗證的演練付款，退款需人工核對，不放行。',
    'terminal_conflict': '演練訂單已有退款、取消或失敗紀錄，本次狀態衝突需人工核對，不放行。',
    'state_regression': '演練訂單狀態倒退，保留既有核對紀錄，不重新放行。',
    'duplicate_payment': '本報價已有另一筆演練付款，疑似重複收款，須人工核對，不放行。',
    'gateway_transaction_reused': '相同演練金流交易編號已核對至另一筆訂單，不放行。',
    'payment_already_verified': '此訂單已有演練付款核對紀錄；不重複計入，改變金流佐證須人工核對。',
    'unmatched_requires_binding': '此演練收據尚未經客服確認配對，須使用人工配對流程，不放行。',
}


class PaymentLab:
    """Small admin-only service; authentication belongs to the HTTP caller.

    init() refuses a database containing non-lab business tables. Its public
    dictionaries contain no credentials, raw payloads, or real checkout URL.
    Validation raises a sanitized ValueError; get_quote returns None if absent.
    """

    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    @contextmanager
    def _connection(self, write=False):
        with self.connection_factory() as connection:
            if not isinstance(connection, sqlite3.Connection):
                raise ValueError('付款演練資料庫連線不正確')
            connection.row_factory = sqlite3.Row
            with connection:
                if write and not connection.in_transaction:
                    connection.execute('BEGIN IMMEDIATE')
                yield connection

    def init(self):
        with self._connection(True) as c:
            names = [r['name'] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            if any(not name.startswith('lab_') for name in names):
                raise ValueError('付款演練必須使用獨立資料庫')
            c.execute('''CREATE TABLE IF NOT EXISTS lab_quotes (
                id TEXT PRIMARY KEY,case_id TEXT NOT NULL,name TEXT NOT NULL,
                repair_fee INTEGER NOT NULL,warranty INTEGER NOT NULL,pickup INTEGER NOT NULL,
                pickup_fee INTEGER NOT NULL,total INTEGER NOT NULL,version INTEGER NOT NULL,
                status TEXT NOT NULL,payment_status TEXT NOT NULL,created_at TEXT NOT NULL,
                last_scenario TEXT NOT NULL DEFAULT '',verification_message TEXT NOT NULL,
                accepted_order_id TEXT NOT NULL DEFAULT '',request_id TEXT UNIQUE,
                request_hash TEXT NOT NULL,UNIQUE(case_id,version))''')
            if 'phone' not in [row['name'] for row in c.execute('PRAGMA table_info(lab_quotes)')]:
                c.execute("ALTER TABLE lab_quotes ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
            if 'address' not in [row['name'] for row in c.execute('PRAGMA table_info(lab_quotes)')]:
                c.execute("ALTER TABLE lab_quotes ADD COLUMN address TEXT NOT NULL DEFAULT ''")
            c.execute('''CREATE TABLE IF NOT EXISTS lab_orders (
                order_id TEXT PRIMARY KEY,quote_id TEXT NOT NULL,identity_hash TEXT NOT NULL,
                payload_hash TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,
                outcome TEXT NOT NULL,verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS lab_reconciliations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,quote_id TEXT NOT NULL,
                order_id TEXT NOT NULL,scenario TEXT NOT NULL,code TEXT NOT NULL,
                state TEXT NOT NULL,test_verified INTEGER NOT NULL,duplicate INTEGER NOT NULL,
                created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS lab_gateway_transactions (
                transaction_id TEXT PRIMARY KEY,order_id TEXT NOT NULL,quote_id TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS lab_reconciliations_quote ON lab_reconciliations(quote_id,id)')
            c.execute('''CREATE TABLE IF NOT EXISTS lab_unmatched_payments (
                id TEXT PRIMARY KEY,order_id TEXT UNIQUE NOT NULL,
                transaction_id TEXT UNIQUE NOT NULL,source_quote_id TEXT NOT NULL,
                payer_name TEXT NOT NULL,payer_phone TEXT NOT NULL,
                remark_case_id TEXT NOT NULL,remark_name TEXT NOT NULL,
                total INTEGER NOT NULL,currency TEXT NOT NULL,payment_status TEXT NOT NULL,
                scenario TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)''')
            if 'payer_address' not in [row['name'] for row in c.execute('PRAGMA table_info(lab_unmatched_payments)')]:
                c.execute("ALTER TABLE lab_unmatched_payments ADD COLUMN payer_address TEXT NOT NULL DEFAULT ''")
            c.execute('''CREATE TABLE IF NOT EXISTS lab_payment_bindings (
                payment_id TEXT PRIMARY KEY,quote_id TEXT UNIQUE NOT NULL,
                case_id TEXT NOT NULL,order_id TEXT UNIQUE NOT NULL,
                actor TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS lab_payment_binding_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,payment_id TEXT NOT NULL,
                quote_id TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,
                created_at TEXT NOT NULL,state TEXT NOT NULL,code TEXT NOT NULL,
                before_quote_id TEXT NOT NULL,before_case_id TEXT NOT NULL,
                after_quote_id TEXT NOT NULL,after_case_id TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS lab_binding_audit_payment ON lab_payment_binding_audit(payment_id,id)')
        return {**FLAGS}

    @staticmethod
    def _quote(row):
        if row is None:
            return None
        return {
            'id': row['id'], 'caseId': row['case_id'], 'name': row['name'], 'phone': row['phone'],
            'address': row['address'],
            'repairFee': row['repair_fee'], 'warranty': bool(row['warranty']),
            'pickup': bool(row['pickup']), 'pickupFee': row['pickup_fee'],
            'total': row['total'], 'currency': 'TWD', 'version': row['version'],
            'status': row['status'], 'paymentStatus': row['payment_status'],
            'createdAt': row['created_at'], 'lastScenario': row['last_scenario'],
            'verificationMessage': row['verification_message'],
            'simulation': True, 'internalOnly': True, 'realPayment': False,
            'releaseAllowed': False,
        }

    def create_quote(self, payload):
        _object(payload, ('name', 'repairFee', 'warranty', 'pickup', 'caseId',
                          'replacesQuoteId', 'requestId', 'phone', 'address'),
                ('name', 'repairFee', 'warranty', 'pickup'), max_bytes=4096)
        name = _text(payload['name'], 100)
        if not name.strip():
            raise ValueError('請填寫合成演練客戶名稱')
        phone = _phone(payload.get('phone', ''))
        address = _text(payload.get('address', ''), 500, 0)
        fee = _integer(payload['repairFee'])
        if type(payload['warranty']) is not bool or type(payload['pickup']) is not bool:
            raise ValueError('演練保固與派車欄位須為布林值')
        warranty, pickup = payload['warranty'], payload['pickup']
        if warranty and fee != 0:
            raise ValueError('保固免維修費演練的維修金額必須為零')
        pickup_fee = 350 if pickup else 0
        total = _integer(fee + pickup_fee)
        supplied_case = payload.get('caseId')
        if supplied_case is not None:
            _synthetic_id(supplied_case, 'LAB-')
        replaces = payload.get('replacesQuoteId')
        if replaces is not None:
            _uuid(replaces)
        request_id = payload.get('requestId')
        if request_id is not None:
            _uuid(request_id)
        fingerprint = _hash(payload)
        with self._connection(True) as c:
            if request_id:
                existing = c.execute('SELECT * FROM lab_quotes WHERE request_id=?', (request_id,)).fetchone()
                if existing:
                    if existing['request_hash'] != fingerprint:
                        raise ValueError('演練請求識別碼不可重用於不同報價')
                    return {**FLAGS, 'quote': self._quote(existing), 'duplicate': True}
            version = 1
            case_id = supplied_case or 'LAB-' + str(uuid.uuid4())
            if replaces:
                previous = c.execute('SELECT * FROM lab_quotes WHERE id=?', (replaces,)).fetchone()
                if not previous or previous['status'] != 'active':
                    raise ValueError('請選擇目前有效的演練報價建立新版')
                if supplied_case is not None and supplied_case != previous['case_id']:
                    raise ValueError('新版演練報價不可變更案件識別碼')
                case_id, version = previous['case_id'], previous['version'] + 1
                if 'phone' not in payload:
                    phone = previous['phone']
                if 'address' not in payload:
                    address = previous['address']
                c.execute("UPDATE lab_quotes SET status='superseded' WHERE id=?", (replaces,))
            elif c.execute('SELECT 1 FROM lab_quotes WHERE case_id=?', (case_id,)).fetchone():
                raise ValueError('相同演練案件須使用報價升版功能')
            quote_id = str(uuid.uuid4())
            code = 'no_payment_required' if total == 0 else 'pending'
            payment_status = 'simulation_no_payment_required' if total == 0 else 'simulation_pending'
            c.execute('''INSERT INTO lab_quotes
                (id,case_id,name,repair_fee,warranty,pickup,pickup_fee,total,version,status,
                 payment_status,created_at,verification_message,request_id,request_hash,phone,address)
                VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?)''',
                (quote_id, case_id, name, fee, int(warranty), int(pickup), pickup_fee,
                 total, version, payment_status, _now(), MESSAGES[code], request_id, fingerprint, phone, address))
            return {**FLAGS, 'quote': self._quote(c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone())}

    def list_quotes(self, limit=100):
        _integer(limit, 1, 200)
        with self._connection() as c:
            rows = c.execute('SELECT * FROM lab_quotes ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
        return {**FLAGS, 'quotes': [self._quote(row) for row in rows], 'scenarios': list(SCENARIOS)}

    def get_quote(self, quote_id):
        _uuid(quote_id)
        with self._connection() as c:
            row = c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone()
        return None if row is None else {**FLAGS, 'quote': self._quote(row)}

    def preview_quote(self, quote_id):
        result = self.get_quote(quote_id)
        if result is None:
            return None
        quote = result['quote']
        text = ('【內部付款演練，非實際付款通知】\n'
                '合成案件：' + quote['caseId'] + '\n'
                '維修費：NT$' + str(quote['repairFee']) + '\n'
                '派車回收運費：NT$' + str(quote['pickupFee']) + '\n'
                '演練總額：NT$' + str(quote['total']) + '\n'
                '未建立實際付款連結、未傳送 LINE、未收款，亦不放行維修或派車。')
        return {**result, 'text': text}

    @staticmethod
    def _validate_order(order):
        fields = ('orderId', 'simulation', 'provider', 'caseId', 'quoteRef', 'quoteVersion',
                  'currency', 'status', 'total', 'paidAmount', 'items', 'gatewayEvidence')
        _object(order, fields, fields)
        _synthetic_id(order['orderId'], 'LABORDER-' if isinstance(order['orderId'], str)
                      and order['orderId'].startswith('LABORDER-') else 'LABO-')
        _synthetic_id(order['caseId'], 'LAB-')
        _uuid(order['quoteRef'])
        _integer(order['quoteVersion'], 1, 1000000)
        if order['simulation'] is not True or order['provider'] != PROVIDER:
            raise ValueError('僅接受明確標示的合成 SHOPLINE 演練訂單')
        if not isinstance(order['currency'], str) or not re.fullmatch(r'[A-Z]{3}', order['currency']):
            raise ValueError('演練幣別格式不正確')
        if order['status'] not in ('pending', 'paid', 'failed', 'cancelled', 'refunded'):
            raise ValueError('演練訂單狀態不正確')
        _integer(order['total']); _integer(order['paidAmount'])
        if not isinstance(order['items'], list) or not 1 <= len(order['items']) <= 5:
            raise ValueError('演練商品資料超過限制')
        for item in order['items']:
            _object(item, ('productId', 'sku', 'unitPrice', 'quantity'),
                    ('productId', 'sku', 'unitPrice', 'quantity'))
            _text(item['productId'], 100); _text(item['sku'], 100)
            _integer(item['unitPrice'], 1); _integer(item['quantity'], 1)
        evidence = order['gatewayEvidence']
        if evidence is not None:
            fields = ('simulation', 'verified', 'transactionId', 'status', 'amount', 'currency')
            _object(evidence, fields, fields)
            if type(evidence['simulation']) is not bool or type(evidence['verified']) is not bool:
                raise ValueError('演練金流佐證格式不正確')
            _synthetic_id(evidence['transactionId'], 'LABTX-')
            _text(evidence['status'], 20); _text(evidence['currency'], 3)
            _integer(evidence['amount'])
        return order

    @staticmethod
    def _identity(order):
        return _hash({key: value for key, value in order.items()
                      if key not in ('status', 'paidAmount', 'gatewayEvidence')})

    @staticmethod
    def _evidence(order):
        evidence = order['gatewayEvidence']
        return bool(evidence and evidence['simulation'] is True and evidence['verified'] is True
                    and evidence['status'] == order['status']
                    and evidence['currency'] == 'TWD'
                    and evidence['amount'] == order['paidAmount'])

    @staticmethod
    def _base_order(quote):
        total = quote['total']
        return {'orderId': 'LABO-' + str(uuid.uuid4()), 'simulation': True,
                'provider': PROVIDER, 'caseId': quote['case_id'], 'quoteRef': quote['id'],
                'quoteVersion': quote['version'], 'currency': 'TWD', 'status': 'paid',
                'total': total, 'paidAmount': total,
                'items': [{'productId': PRODUCT_ID, 'sku': PRODUCT_SKU,
                           'unitPrice': 1, 'quantity': max(1, total)}],
                'gatewayEvidence': {'simulation': True, 'verified': True,
                    'transactionId': 'LABTX-' + str(uuid.uuid4()),
                    'status': 'paid', 'amount': total, 'currency': 'TWD'}}

    def _scenario_order(self, c, quote, scenario):
        order = self._base_order(quote)
        if scenario == 'duplicate':
            previous = c.execute('SELECT payload FROM lab_orders WHERE quote_id=? ORDER BY rowid DESC LIMIT 1', (quote['id'],)).fetchone()
            return json.loads(previous['payload']) if previous else None
        if scenario == 'refund':
            previous = c.execute('SELECT payload FROM lab_orders WHERE order_id=?', (quote['accepted_order_id'],)).fetchone()
            if previous:
                order = json.loads(previous['payload'])
            order['status'] = 'refunded'
            order['gatewayEvidence'] = {**order['gatewayEvidence'], 'status': 'refunded'}
        elif scenario in ('pending', 'failed', 'cancelled'):
            order.update(status=scenario, paidAmount=0, gatewayEvidence=None)
        elif scenario in ('underpaid', 'amount_mismatch'):
            order['paidAmount'] = max(0, quote['total'] - 1)
            order['gatewayEvidence']['amount'] = order['paidAmount']
            if scenario == 'amount_mismatch':
                order['total'] = max(0, quote['total'] - 1)
        elif scenario == 'invalid_currency':
            order['currency'] = 'USD'
        elif scenario == 'wrong_sku':
            order['items'][0]['sku'] = 'LAB-WRONG-SKU'
        elif scenario == 'mixed_cart':
            order['items'].append({'productId': 'LAB-OTHER', 'sku': 'LAB-OTHER', 'unitPrice': 1, 'quantity': 1})
        elif scenario == 'wrong_case':
            order['caseId'] = 'LAB-' + str(uuid.uuid4())
        elif scenario == 'wrong_quote_version':
            order['quoteVersion'] += 1
        elif scenario == 'late_old_quote':
            prior = c.execute('SELECT id,version FROM lab_quotes WHERE case_id=? AND version<? ORDER BY version DESC LIMIT 1', (quote['case_id'], quote['version'])).fetchone()
            order['quoteRef'] = prior['id'] if prior else str(uuid.uuid4())
            order['quoteVersion'] = prior['version'] if prior else quote['version']
        elif scenario == 'missing_evidence':
            order['gatewayEvidence'] = None
        return order

    def _classify(self, quote, order, previous):
        if quote['total'] == 0:
            return 'zero_amount_order'
        if order['caseId'] != quote['case_id']:
            return 'case_mismatch'
        if order['quoteRef'] != quote['id']:
            return 'quote_mismatch'
        if order['quoteVersion'] != quote['version']:
            return 'version_mismatch'
        if order['currency'] != 'TWD':
            return 'currency_mismatch'
        if (len(order['items']) != 1 or order['items'][0] != {
                'productId': PRODUCT_ID, 'sku': PRODUCT_SKU,
                'unitPrice': 1, 'quantity': quote['total']}):
            return 'cart_mismatch'
        if order['total'] != quote['total']:
            return 'amount_mismatch'
        status = order['status']
        if status == 'refunded':
            if not previous or not previous['verified']:
                return 'refund_without_payment'
            if order['paidAmount'] != quote['total'] or not self._evidence(order):
                return 'missing_evidence'
            return 'refunded'
        if quote['status'] != 'active':
            return 'superseded_quote'
        if previous and previous['status'] in ('refunded', 'cancelled', 'failed'):
            return 'terminal_conflict'
        if previous and previous['verified'] and status == 'paid':
            return 'payment_already_verified'
        if status != 'paid':
            return 'state_regression' if previous and previous['verified'] else status
        if order['paidAmount'] != quote['total']:
            return 'paid_amount_mismatch'
        if not self._evidence(order):
            return 'missing_evidence'
        if quote['accepted_order_id'] and quote['accepted_order_id'] != order['orderId']:
            return 'duplicate_payment'
        return 'verified'

    def simulate_order(self, quote_id, payload):
        _uuid(quote_id)
        _object(payload, ('scenario', 'order'))
        if ('scenario' in payload) == ('order' in payload):
            raise ValueError('請指定一種演練情境或一筆合成訂單')
        scenario = payload.get('scenario', 'custom')
        if 'scenario' in payload and scenario not in SCENARIOS:
            raise ValueError('不支援此內部付款演練情境')
        if 'order' in payload:
            self._validate_order(payload['order'])
        with self._connection(True) as c:
            quote = c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone()
            if quote is None:
                raise ValueError('找不到合成演練報價')
            order = payload.get('order') if 'order' in payload else self._scenario_order(c, quote, scenario)
            code, duplicate, previous = 'no_prior_order', False, None
            order_id = ''
            if order is not None:
                self._validate_order(order)
                order_id = order['orderId']
                previous = c.execute('SELECT * FROM lab_orders WHERE order_id=?', (order_id,)).fetchone()
                fingerprint, identity = _hash(order), self._identity(order)
                if previous and (previous['quote_id'] != quote_id or previous['identity_hash'] != identity):
                    code = 'order_id_reused'
                elif previous and previous['payload_hash'] == fingerprint:
                    code, duplicate = 'duplicate', True
                else:
                    unbound = c.execute('''SELECT p.id FROM lab_unmatched_payments p
                        LEFT JOIN lab_payment_bindings b ON b.payment_id=p.id
                        WHERE p.order_id=? AND b.payment_id IS NULL''', (order_id,)).fetchone()
                    transaction = (c.execute('SELECT order_id FROM lab_gateway_transactions WHERE transaction_id=?',
                                   (order['gatewayEvidence']['transactionId'],)).fetchone()
                                   if order['gatewayEvidence'] else None)
                    code = ('unmatched_requires_binding' if unbound else
                            'gateway_transaction_reused' if transaction and transaction['order_id'] != order_id
                            else self._classify(quote, order, previous))
                    # A verified refund may carry its own gateway transaction
                    # ID. Reserve it too: otherwise another order could reuse
                    # that acknowledged refund as synthetic payment evidence.
                    if code in ('verified', 'refunded'):
                        c.execute('INSERT OR IGNORE INTO lab_gateway_transactions(transaction_id,order_id,quote_id) VALUES(?,?,?)',
                                  (order['gatewayEvidence']['transactionId'], order_id, quote_id))
                    # Preserve the accepted original on invalid transitions and
                    # never let an invalid attempt replace its stored evidence.
                    if previous is None and not unbound:
                        c.execute('''INSERT INTO lab_orders
                            (order_id,quote_id,identity_hash,payload_hash,payload,status,outcome,verified,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?)''',
                            (order_id, quote_id, identity, fingerprint, _dump(order), order['status'],
                             code, int(code == 'verified'), _now(), _now()))
                    elif code in ('verified', 'pending', 'failed', 'cancelled', 'refunded'):
                        c.execute('''UPDATE lab_orders SET payload_hash=?,payload=?,status=?,outcome=?,verified=?,updated_at=? WHERE order_id=?''',
                            (fingerprint, _dump(order), order['status'], code,
                             int(code == 'verified'), _now(), order_id))
            verified = code == 'verified'
            state = 'duplicate' if duplicate else ('processed' if code in ('verified', 'pending', 'failed', 'cancelled', 'refunded') else 'blocked')
            payment_status = quote['payment_status']
            if verified:
                payment_status = 'simulation_verified'
                c.execute('UPDATE lab_quotes SET accepted_order_id=? WHERE id=?', (order_id, quote_id))
            elif code == 'refunded':
                payment_status = 'simulation_refunded'
                c.execute("UPDATE lab_unmatched_payments SET payment_status='simulation_refunded' WHERE order_id=?", (order_id,))
            elif code == 'zero_amount_order':
                payment_status = 'simulation_no_payment_required'
            elif not duplicate and quote['payment_status'] not in ('simulation_verified', 'simulation_refunded', 'simulation_no_payment_required'):
                payment_status = ('simulation_' + code) if code in ('pending', 'failed', 'cancelled') else 'simulation_review'
            message = MESSAGES[code]
            c.execute('UPDATE lab_quotes SET payment_status=?,last_scenario=?,verification_message=? WHERE id=?',
                      (payment_status, scenario, message, quote_id))
            c.execute('''INSERT INTO lab_reconciliations
                (quote_id,order_id,scenario,code,state,test_verified,duplicate,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',
                (quote_id, order_id, scenario, code, state, int(verified), int(duplicate), _now()))
            result = {**FLAGS, 'state': state, 'code': code, 'orderId': order_id,
                      'testPaymentVerified': verified, 'duplicate': duplicate,
                      'verificationMessage': message}
            return {**FLAGS, 'quote': self._quote(c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone()), 'result': result}

    def list_reconciliations(self, quote_id, limit=100):
        _uuid(quote_id); _integer(limit, 1, 200)
        with self._connection() as c:
            rows = c.execute('''SELECT id,order_id,scenario,code,state,test_verified,duplicate,created_at
                FROM lab_reconciliations WHERE quote_id=? ORDER BY id DESC LIMIT ?''', (quote_id, limit)).fetchall()
        records = [{'id': row['id'], 'orderId': row['order_id'], 'scenario': row['scenario'],
                    'code': row['code'], 'state': row['state'],
                    'testPaymentVerified': bool(row['test_verified']),
                    'duplicate': bool(row['duplicate']), 'createdAt': row['created_at'],
                    'verificationMessage': MESSAGES[row['code']],
                    'simulation': True, 'internalOnly': True,
                    'realPayment': False, 'releaseAllowed': False} for row in rows]
        return {**FLAGS, 'reconciliations': records}

    def _candidates(self, c, payment):
        # The fixture's source quote is deliberately not a matching criterion:
        # real missing-note recovery must remain an explicit human decision.
        rows = c.execute('''SELECT q.* FROM lab_quotes q
            WHERE q.status='active' AND q.total>0 AND q.accepted_order_id=''
              AND NOT EXISTS(SELECT 1 FROM lab_payment_bindings b WHERE b.quote_id=q.id)
            ORDER BY q.rowid DESC LIMIT 1001''').fetchall()
        if len(rows) > 1000:
            return {'candidates': [], 'assessment': {'level': 'low', 'unique': False,
                    'reason': '演練候選案件過多，請先縮小人工核對範圍。', 'autoBindAllowed': False}}
        source = c.execute('SELECT status FROM lab_quotes WHERE id=?', (payment['source_quote_id'],)).fetchone()
        product_valid = False
        try:
            receipt = json.loads(payment['payload'])
            product_valid = payment['total'] > 0 and receipt.get('items') == [
                {'productId': PRODUCT_ID, 'sku': PRODUCT_SKU, 'unitPrice': 1, 'quantity': payment['total']}]
            verified = bool(payment['payment_status'] == 'simulation_verified' and source and source['status'] == 'active'
                            and receipt.get('simulation') is True and receipt.get('provider') == PROVIDER
                            and receipt.get('status') == 'paid' and receipt.get('currency') == 'TWD'
                            and receipt.get('total') == payment['total'] and receipt.get('paidAmount') == payment['total']
                            and self._evidence(receipt) and receipt['gatewayEvidence']['transactionId'] == payment['transaction_id'])
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            verified = False
        order = {'customerName': payment['payer_name'], 'customerPhone': payment['payer_phone'],
                 'address': payment['payer_address'], 'total': payment['total'], 'currency': payment['currency'],
                 'remarkCaseId': payment['remark_case_id'], 'paymentVerified': verified,
                 'productValid': product_valid,
                 'reportedPaymentStatus': 'paid' if payment['payment_status'] == 'simulation_verified' else
                                          'refunded' if payment['payment_status'] == 'simulation_refunded' else 'pending'}
        result = rank_candidates(order, [{'quoteId': quote['id'], 'caseId': quote['case_id'],
                    'name': quote['name'], 'phone': quote['phone'], 'address': quote['address'],
                    'total': quote['total'], 'currency': 'TWD', 'status': quote['status'],
                    'paymentStatus': quote['payment_status']} for quote in rows])
        # Limit display only after the complete pool determines ambiguity.
        result['candidates'] = [row for row in result['candidates']
                                if row['score'] > 0 or '案件編號相同' in row['reasons']][:20]
        if not source or source['status'] != 'active':
            result['assessment']['reason'] = '原演練報價已失效，舊版付款不可配對至新版或其他案件。'
        return result

    def _payment(self, c, row):
        binding = c.execute('SELECT quote_id,case_id FROM lab_payment_bindings WHERE payment_id=?', (row['id'],)).fetchone()
        payment_status = row['payment_status']
        if binding:
            order = c.execute('SELECT status,outcome,verified FROM lab_orders WHERE order_id=? AND quote_id=?',
                              (row['order_id'], binding['quote_id'])).fetchone()
            # A bound receipt follows its authoritative lab ledger, including
            # refunds made through the older order-rehearsal interface.
            payment_status = ('simulation_refunded' if order and order['status'] == 'refunded' and order['outcome'] == 'refunded'
                              else 'simulation_verified' if order and order['status'] == 'paid' and order['verified']
                              else 'simulation_pending')
        matching = (self._candidates(c, row) if not binding else
                    {'candidates': [], 'assessment': {'level': 'low', 'unique': False,
                     'reason': '此演練付款已有人工配對紀錄，保留原關聯，不再提供新配對建議。', 'autoBindAllowed': False}})
        return {'id': row['id'], 'orderId': row['order_id'],
                'payerName': row['payer_name'], 'payerPhone': row['payer_phone'],
                'payerAddress': row['payer_address'],
                'remarkCaseId': row['remark_case_id'], 'remarkName': row['remark_name'],
                'total': row['total'], 'currency': row['currency'],
                'paymentStatus': payment_status,
                'matchStatus': 'bound' if binding else 'unmatched',
                'boundQuoteId': binding['quote_id'] if binding else '',
                'boundCaseId': binding['case_id'] if binding else '',
                'createdAt': row['created_at'],
                'candidates': matching['candidates'], 'matching': matching['assessment'],
                'simulation': True, 'internalOnly': True,
                'realPayment': False, 'releaseAllowed': False}

    def simulate_receipt(self, payload):
        """Generate a fixed synthetic receipt; never accept provider payloads."""
        _object(payload, ('quoteId', 'scenario'), ('quoteId', 'scenario'), max_bytes=1024)
        quote_id = _uuid(payload['quoteId'])
        scenario = payload['scenario']
        if scenario not in RECEIPT_SCENARIOS:
            raise ValueError('不支援此漏填備註演練情境')
        with self._connection(True) as c:
            quote = c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone()
            if quote is None:
                raise ValueError('找不到合成演練報價')
            order = self._base_order(quote)
            order['orderId'] = 'LABORDER-' + str(uuid.uuid4())
            payer_name, payer_phone = quote['name'], quote['phone']
            payer_address = quote['address']
            remark_case, remark_name = quote['case_id'], quote['name']
            if scenario in ('missing_case', 'missing_both'):
                remark_case = ''
            if scenario in ('missing_name', 'missing_both'):
                remark_name = ''
            if scenario == 'different_payer':
                payer_name = '合成代付人' if quote['name'] != '合成代付人' else '另一位合成代付人'
                payer_phone, remark_name = '', payer_name
            if scenario == 'address_mismatch':
                payer_address = ('台北市中正區合成測試路999號9樓' if quote['address'] != '台北市中正區合成測試路999號9樓'
                                 else '台北市中正區合成測試路998號9樓')
            elif scenario == 'missing_address':
                payer_address = ''
            elif scenario == 'phone_format' and quote['phone']:
                payer_phone = '+886 ' + quote['phone'][1:4] + '-' + quote['phone'][4:]
            if scenario == 'wrong_amount':
                amount = quote['total'] - 1 if quote['total'] > 0 else 1
                order.update(total=amount, paidAmount=amount)
                order['items'][0]['quantity'] = max(1, amount)
                order['gatewayEvidence']['amount'] = amount
            payment_status = 'simulation_verified'
            transaction_id = order['gatewayEvidence']['transactionId']
            if scenario == 'unpaid':
                order.update(status='pending', paidAmount=0, gatewayEvidence=None)
                payment_status = 'simulation_pending'
            elif scenario == 'refunded':
                order['status'] = 'refunded'; order['gatewayEvidence']['status'] = 'refunded'
                payment_status = 'simulation_refunded'
            # Missing metadata is absent from the immutable receipt. It is
            # assigned only after the operator has confirmed a specific quote.
            receipt = {key: value for key, value in order.items()
                       if key not in ('caseId', 'quoteRef', 'quoteVersion')}
            payment_id = str(uuid.uuid4())
            c.execute('''INSERT INTO lab_unmatched_payments
                (id,order_id,transaction_id,source_quote_id,payer_name,payer_phone,
                 remark_case_id,remark_name,total,currency,payment_status,scenario,payload,created_at,payer_address)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (payment_id, order['orderId'], transaction_id, quote_id, payer_name, payer_phone,
                 remark_case, remark_name, order['total'], order['currency'], payment_status,
                 scenario, _dump(receipt), _now(), payer_address))
            # Reserve even an unmatched receipt's transaction against reuse by
            # a different order; quote ownership remains empty until binding.
            c.execute('INSERT INTO lab_gateway_transactions(transaction_id,order_id,quote_id) VALUES(?,?,?)',
                      (transaction_id, order['orderId'], ''))
            return {**FLAGS, 'payment': self._payment(c, c.execute(
                'SELECT * FROM lab_unmatched_payments WHERE id=?', (payment_id,)).fetchone())}

    def list_unmatched(self, limit=100):
        _integer(limit, 1, 200)
        with self._connection() as c:
            rows = c.execute('SELECT * FROM lab_unmatched_payments ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
            payments = [self._payment(c, row) for row in rows]
        return {**FLAGS, 'payments': payments, 'scenarios': list(RECEIPT_SCENARIOS)}

    def get_payment(self, payment_id):
        _uuid(payment_id)
        with self._connection() as c:
            row = c.execute('SELECT * FROM lab_unmatched_payments WHERE id=?', (payment_id,)).fetchone()
            return None if row is None else {**FLAGS, 'payment': self._payment(c, row)}

    @staticmethod
    def _binding_audit(c, payment_id, quote_id, actor, reason, state, code, before, after):
        c.execute('''INSERT INTO lab_payment_binding_audit
            (payment_id,quote_id,actor,reason,created_at,state,code,
             before_quote_id,before_case_id,after_quote_id,after_case_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (payment_id, quote_id, actor, reason, _now(), state, code,
             before['quoteId'], before['caseId'], after['quoteId'], after['caseId']))

    def bind_payment(self, payment_id, payload, actor='admin'):
        """Atomically associate one verified synthetic receipt with one quote."""
        _uuid(payment_id)
        _object(payload, ('quoteId', 'reason', 'confirm'), ('quoteId', 'reason', 'confirm'), max_bytes=4096)
        quote_id = _uuid(payload['quoteId'])
        reason = _text(payload['reason'], 500).strip()
        actor = _text(actor, 100).strip()
        if payload['confirm'] is not True or len(reason) < 8 or not actor:
            raise ValueError('人工配對演練須明確確認，並填寫至少八字的核對理由')
        failure, output = None, None
        with self._connection(True) as c:
            payment = c.execute('SELECT * FROM lab_unmatched_payments WHERE id=?', (payment_id,)).fetchone()
            if payment is None:
                raise ValueError('找不到合成演練付款')
            previous = c.execute('SELECT * FROM lab_payment_bindings WHERE payment_id=?', (payment_id,)).fetchone()
            before = {'quoteId': previous['quote_id'] if previous else '',
                      'caseId': previous['case_id'] if previous else ''}
            try:
                if previous:
                    if previous['quote_id'] != quote_id:
                        raise _BindingRejected('payment_already_bound', '此演練付款已配對至其他報價，不可重複配對')
                    quote = c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone()
                    return {**FLAGS, 'payment': self._payment(c, payment), 'quote': self._quote(quote),
                            'result': {**FLAGS, 'state': 'duplicate',
                                       'verificationMessage': '已存在相同演練配對，未重複處理或放行任何真實案件。'}}
                quote = c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone()
                if quote is None or quote['status'] != 'active':
                    raise _BindingRejected('inactive_quote', '僅能配對目前有效的合成演練報價')
                source = c.execute('SELECT status FROM lab_quotes WHERE id=?', (payment['source_quote_id'],)).fetchone()
                if not source or source['status'] != 'active':
                    raise _BindingRejected('receipt_source_superseded', '演練收據所屬原報價已失效，不能將舊版付款認列至新版或其他案件')
                if quote['total'] <= 0:
                    raise _BindingRejected('zero_quote', '零元演練報價應使用免付款流程，不可綁定付款')
                if quote['accepted_order_id'] or c.execute('SELECT 1 FROM lab_payment_bindings WHERE quote_id=?', (quote_id,)).fetchone():
                    raise _BindingRejected('quote_already_paid', '此演練報價已有付款核對紀錄，不可再綁第二筆付款')
                if payment['payment_status'] != 'simulation_verified':
                    raise _BindingRejected('payment_not_verified', '未付款或已退款的演練收據不可配對為已付款')
                if payment['currency'] != 'TWD' or payment['total'] != quote['total']:
                    raise _BindingRejected('amount_currency_mismatch', '演練收據幣別或實付總額與報價不一致，不可配對')
                if payment['remark_case_id'] and payment['remark_case_id'] != quote['case_id']:
                    raise _BindingRejected('remark_case_conflict', '付款備註已指向其他案件，不可配對至本案')
                if c.execute('SELECT 1 FROM lab_orders WHERE order_id=?', (payment['order_id'],)).fetchone():
                    raise _BindingRejected('order_already_recorded', '此演練訂單已有核對紀錄，須保留原始訂單關聯')
                transaction = c.execute('SELECT * FROM lab_gateway_transactions WHERE transaction_id=?', (payment['transaction_id'],)).fetchone()
                if transaction and (transaction['order_id'] != payment['order_id'] or transaction['quote_id'] not in ('', quote_id)):
                    raise _BindingRejected('gateway_transaction_reused', MESSAGES['gateway_transaction_reused'])
                try:
                    receipt = json.loads(payment['payload'])
                    order = {**receipt, 'caseId': quote['case_id'], 'quoteRef': quote_id,
                             'quoteVersion': quote['version']}
                    self._validate_order(order)
                except (ValueError, TypeError, RecursionError):
                    raise _BindingRejected('invalid_receipt', '合成演練收據資料無法核對，不可配對') from None
                if (order['orderId'] != payment['order_id'] or not order['gatewayEvidence']
                        or order['gatewayEvidence']['transactionId'] != payment['transaction_id']
                        or order['total'] != payment['total'] or order['currency'] != payment['currency']):
                    raise _BindingRejected('receipt_identity_conflict', '合成演練收據識別資料不一致，不可配對')
                code = self._classify(quote, order, None)
                if code != 'verified':
                    raise _BindingRejected(code, MESSAGES[code])
                message = '人工配對演練已完成；未實際收款，未放行任何真實案件或派車。'
                c.execute('''INSERT INTO lab_orders
                    (order_id,quote_id,identity_hash,payload_hash,payload,status,outcome,verified,created_at,updated_at)
                    VALUES(?,?,?,?,?,'paid','verified',1,?,?)''',
                    (payment['order_id'], quote_id, self._identity(order), _hash(order), _dump(order), _now(), _now()))
                c.execute('INSERT OR IGNORE INTO lab_gateway_transactions(transaction_id,order_id,quote_id) VALUES(?,?,?)',
                          (payment['transaction_id'], payment['order_id'], quote_id))
                c.execute('UPDATE lab_gateway_transactions SET quote_id=? WHERE transaction_id=? AND order_id=?',
                          (quote_id, payment['transaction_id'], payment['order_id']))
                c.execute('''INSERT INTO lab_payment_bindings(payment_id,quote_id,case_id,order_id,actor,reason,created_at)
                    VALUES(?,?,?,?,?,?,?)''',
                    (payment_id, quote_id, quote['case_id'], payment['order_id'], actor, reason, _now()))
                c.execute("UPDATE lab_quotes SET payment_status='simulation_verified',accepted_order_id=?,last_scenario='manual_binding',verification_message=? WHERE id=?",
                          (payment['order_id'], message, quote_id))
                self._binding_audit(c, payment_id, quote_id, actor, reason, 'bound', 'bound',
                                    before, {'quoteId': quote_id, 'caseId': quote['case_id']})
                output = {**FLAGS, 'payment': self._payment(c, payment),
                          'quote': self._quote(c.execute('SELECT * FROM lab_quotes WHERE id=?', (quote_id,)).fetchone()),
                          'result': {**FLAGS, 'state': 'bound', 'verificationMessage': message}}
            except _BindingRejected as error:
                self._binding_audit(c, payment_id, quote_id, actor, reason, 'blocked', error.code, before, before)
                failure = ValueError(str(error))
        # Commit a blocked attempt's audit without committing any association.
        if failure:
            raise failure
        return output

    def list_binding_audit(self, payment_id, limit=100):
        _uuid(payment_id); _integer(limit, 1, 200)
        with self._connection() as c:
            if not c.execute('SELECT 1 FROM lab_unmatched_payments WHERE id=?', (payment_id,)).fetchone():
                return None
            rows = c.execute('SELECT * FROM lab_payment_binding_audit WHERE payment_id=? ORDER BY id DESC LIMIT ?', (payment_id, limit)).fetchall()
        events = [{'id': row['id'], 'paymentId': row['payment_id'], 'quoteId': row['quote_id'],
                   'actor': row['actor'], 'reason': row['reason'], 'createdAt': row['created_at'],
                   'state': row['state'], 'code': row['code'],
                   'before': {'quoteId': row['before_quote_id'], 'caseId': row['before_case_id']},
                   'after': {'quoteId': row['after_quote_id'], 'caseId': row['after_case_id']},
                   'simulation': True, 'internalOnly': True,
                   'realPayment': False, 'releaseAllowed': False} for row in rows]
        return {**FLAGS, 'paymentId': payment_id, 'events': events}
