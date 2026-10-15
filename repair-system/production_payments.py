"""Production authority joining repair cases to a separate, empty payment ledger.

Calculation modules retain their strict isolated-ledger contracts. This adapter
alone reads real repair ownership and controls production release. No test DB,
test identity, demo endpoint, synthetic order or provider write is imported.
"""
import atexit
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from service_desk import ServiceDesk
from service_desk_reconciliation import RealOrderReconciliation
from payment_sheet_sync import PaymentSheetSync
from shopline_orders import fetch_repair_orders
from order_matching import normalize_phone

WORKFLOW = 'payment-v1'
TAIPEI = timezone(timedelta(hours=8))
CASE = re.compile(r'R[0-9]{8}-[0-9]{4,8}\Z')
QUOTE = re.compile(r'WQ-[0-9a-f-]{36}\Z')
ORDER = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1C5gGI4cL4lgw-GqSXRcQuicM2e5FvDHp-bnfqpMcnqI/edit'
CHECK_REASONS = {
    'invalid_provenance': '未取得本次伺服器重新查詢的訂單，請重新核對。',
    'invalid_order': '訂單欄位不完整或格式不正確。',
    'invalid_quote': '找不到有效的核定金額。',
    'stale_quote_snapshot': '案件或核定資料已異動，請重新整理後核對。',
    'not_snapshot': '訂單未連結至有效的維修案件。',
    'superseded_quote': '此為舊版報價，不能套用至目前核定金額。',
    'quote_not_awaiting_payment': '此報價目前不接受新的付款配對。',
    'no_payment_required': '此案核定免付款，不應配對付費訂單。',
    'invalid_currency': '訂單或核定金額不是新臺幣。',
    'amount_mismatch': '付款訂單總額與目前核定金額不一致。',
    'invalid_product': '商品、數量或金額組成不符合維修費用一元商品規則。',
    'provider_review_required': '商城回傳的訂單欄位需要客服確認。',
    'not_completed': '商城尚未回報此訂單付款完成。',
    'refunded': '此訂單已有退款相關狀態，不能作為可用付款。',
    'untrusted_payment_assertion': '訂單的付款驗證資料不符合目前核對規則。',
    'invalid_order_time': '缺少有效的訂單或報價時間。',
    'order_predates_quote': '付款訂單建立時間早於本次核定報價。',
    'missing_remark': '訂單備註缺少「送修編號」或「申請人姓名」。',
    'conflicting_remark': '訂單備註含有多筆或互相衝突的案件資料。',
    'case_mismatch': '備註的送修編號與本案件不一致。',
    'name_mismatch': '備註的申請人姓名與本案件不一致。',
    'phone_mismatch': '訂購人及收件人電話均未與案件電話吻合。',
    'order_already_bound': '此付款訂單已配對其他案件或報價，不能重複使用。',
    'quote_already_bound': '本次報價已配對另一筆付款訂單，請確認是否重複付款。',
}


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _now():
    return datetime.now(TAIPEI).isoformat(timespec='seconds')


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value or uuid.UUID(value).version != 4:
        raise ValueError('操作識別碼不正確，請重新整理')
    return value


def _case_data(case):
    value = case.get('data', {})
    return json.loads(value) if isinstance(value, str) else value


def _identity(case):
    data = _case_data(case)
    return {'id': case['id'], 'userId': case['user_id'], 'created': case['created'],
        **{key: data.get(key, '') for key in ('name', 'phone', 'model', 'shipping',
            'pickupAddress', 'returnAddress', 'order', 'paymentWorkflow')}}


def _fingerprint(case):
    return hashlib.sha256(_dump(_identity(case)).encode()).hexdigest()


class ProviderBusy(ValueError):
    pass


class ProductionOrderProvider:
    def __init__(self, token, fetcher=None):
        self.token = token
        self.fetcher = fetcher or (lambda token, filters: fetch_repair_orders(token, filters, max_pages=250))
        self.lock = threading.Lock()
        self.next_attempt = 0.0
        self.last_state = {'configured': True, 'status': 'not_checked', 'orders': []}

    def fetch(self, filters):
        if not self.lock.acquire(False):
            raise ProviderBusy('商城核對進行中，請稍後再試')
        try:
            if time.monotonic() < self.next_attempt:
                raise ProviderBusy('請稍後再核對商城訂單')
            self.next_attempt = time.monotonic() + 2
            result = self.fetcher(self.token, filters)
            if type(result) is not dict:
                raise ValueError('商城暫時無法核對')
            self.last_state = {**result, 'configured': True, 'lastFetchedAt': _now()}
            return self.last_state
        finally:
            self.lock.release()

    def exact(self, number):
        if not isinstance(number, str) or not ORDER.fullmatch(number):
            raise ValueError('付款訂單編號不正確')
        state = self.fetch({'orderNumber': number})
        rows = state.get('orders', [])
        if (state.get('status') != 'ok' or state.get('truncated') is True
                or len(rows) != 1 or rows[0].get('orderNumber') != number):
            raise ValueError('無法取得唯一且完整的維修付款訂單')
        return rows[0]


class ProductionPayments:
    def __init__(self, server, config, *, sender=None, provider=None, sheet=None, start_workers=True):
        self.s, self.config = server, config
        self.path = Path(server['DATA_DIR']) / 'payments.db'
        if self.path.is_symlink():
            raise ValueError('付款資料庫位置不正確')
        self.stop_event, self.wake_event = threading.Event(), threading.Event()
        self.cycle_lock, self.last_scan = threading.Lock(), 0.0
        self.last_error, self.thread = '', None
        self.provider = provider or ProductionOrderProvider(config['shoplineApiToken'])
        self.desk = ServiceDesk(self.connect, seed_examples=False)
        self.desk.init()
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS wb_prod_links (
                real_id TEXT PRIMARY KEY, wb_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL,
                source_hash TEXT NOT NULL, enrolled_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wb_prod_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT OR IGNORE INTO wb_prod_settings VALUES('new_cases_enabled','0');
                INSERT OR IGNORE INTO wb_prod_settings VALUES('notifications_enabled','0');
                CREATE TABLE IF NOT EXISTS wb_prod_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, quote_id TEXT NOT NULL,
                order_number TEXT NOT NULL DEFAULT '', user_id TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
                first_attempt REAL NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',accepted_at TEXT NOT NULL DEFAULT '',
                UNIQUE(kind,quote_id,order_number));''')
            if 'leased_until' not in {r['name'] for r in c.execute('PRAGMA table_info(wb_prod_messages)')}:
                c.execute('ALTER TABLE wb_prod_messages ADD COLUMN leased_until REAL NOT NULL DEFAULT 0')
        self.reconciliation = RealOrderReconciliation(self.connect)
        self.reconciliation.init()
        self.sync = PaymentSheetSync(self.connect)
        self.sync.init()
        if sender is None:
            from production_payment_sender import ProductionPaymentSender
            sender = ProductionPaymentSender(token_getter=lambda: self.s['TOKEN'], recipient_resolver=self.recipient)
        self.sender = sender
        if sheet is None:
            from production_payment_sheet import ProductionPaymentSheet
            sheet = ProductionPaymentSheet(self.sync, self.s['cloud_settings'], self.allowed_ids)
        self.sheet = sheet
        self._backup()
        self.last_backup = time.time()
        if start_workers:
            self.sheet.start()
            self.thread = threading.Thread(target=self._loop, name='production-payments', daemon=True)
            self.thread.start()
            atexit.register(self.stop)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _backup(self):
        directory = self.path.parent / 'payment-backups'
        directory.mkdir(exist_ok=True)
        name = datetime.now(TAIPEI).strftime('%Y%m%dT%H%M%S')
        target = directory / ('payments-' + name + '-' + secrets.token_hex(4) + '.sqlite3')
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        os.chmod(target, 0o600)
        for old in sorted(directory.glob('payments-*.sqlite3'))[:-14]:
            if not old.is_symlink() and old.resolve().parent == directory.resolve():
                old.unlink()

    def setting(self, key):
        with self.connect() as c:
            row = c.execute('SELECT value FROM wb_prod_settings WHERE key=?', (key,)).fetchone()
        return bool(row and row['value'] == '1')

    @property
    def new_cases_enabled(self):
        return self.setting('new_cases_enabled')

    def _repair(self, case_id):
        if not isinstance(case_id, str) or not CASE.fullmatch(case_id):
            raise ValueError('維修案件編號不正確')
        with self.s['connect']() as c:
            row = c.execute('SELECT * FROM cases WHERE id=?', (case_id,)).fetchone()
        if row is None:
            raise ValueError('找不到維修案件')
        return dict(row)

    def allowed_ids(self):
        with self.connect() as c:
            return {r['wb_id'] for r in c.execute('SELECT wb_id FROM wb_prod_links')}

    def enroll(self, real_id):
        case = self._repair(real_id)
        data = _case_data(case)
        if data.get('paymentWorkflow') != WORKFLOW:
            raise ValueError('此案維持原作業方式，未採用新付款流程')
        if not re.fullmatch(r'U[0-9a-f]{32}', case['user_id']):
            raise ValueError('案件缺少已驗證的 LINE 身分')
        with self.connect() as c:
            prior = c.execute('SELECT * FROM wb_prod_links WHERE real_id=?', (real_id,)).fetchone()
        if prior:
            self._current(prior['wb_id'])
            return prior['wb_id']
        pickup = data.get('shipping') == '由客服派遣物流回收'
        address = data.get('pickupAddress') if pickup else data.get('returnAddress')
        values = {'caseNumber': real_id,
            'originalOrderNumber': data.get('order', ''), 'name': data.get('name', ''),
            'phone': normalize_phone(data.get('phone', '')) or data.get('phone', ''),
            'address': address or '', 'model': data.get('model', ''),
            'pickup': pickup, 'lineLinked': True, 'lineName': case.get('line_display_name') or data.get('name', ''),
            'source': 'snapshot'}
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            prior = c.execute('SELECT * FROM wb_prod_links WHERE real_id=?', (real_id,)).fetchone()
            if prior:
                return prior['wb_id']
            created_id = self.desk._insert_case(c, values)
            c.execute('INSERT INTO wb_prod_links VALUES(?,?,?,?,?)',
                (real_id, created_id, case['user_id'], _fingerprint(case), _now()))
            self.desk._audit(c, created_id, 'production_enrollment', '正式案件採用付款流程；未搬入任何內測付款紀錄')
        self.sync.enqueue(created_id)
        self.wake()
        return created_id

    def _current(self, wb_id, *, allow_cancelled=False):
        with self.connect() as c:
            link = c.execute('SELECT * FROM wb_prod_links WHERE wb_id=?', (wb_id,)).fetchone()
        if not link:
            raise ValueError('付款紀錄未綁定正式案件')
        case = self._repair(link['real_id'])
        if (case['user_id'] != link['user_id'] or _fingerprint(case) != link['source_hash']
                or _case_data(case).get('paymentWorkflow') != WORKFLOW):
            raise ValueError('案件資料已異動，請由客服核實後處理')
        if not allow_cancelled and case['status'] in ('已取消', '不維修退回'):
            raise ValueError('案件已取消或停止維修')
        return case

    def recipient(self, wb_id):
        case = self._current(wb_id, allow_cancelled=True)
        return {'verified': True, 'userId': case['user_id'],
            'displayName': case.get('line_display_name') or _case_data(case).get('name', '')}

    def wrapper(self, quote_id, *, allow_cancelled=False):
        if not isinstance(quote_id, str) or not QUOTE.fullmatch(quote_id):
            raise ValueError('核價識別碼不正確')
        wrapper = self.desk.get_quote(quote_id)
        if not wrapper or not wrapper.get('quote'):
            raise ValueError('找不到核定金額')
        self._current(wrapper['case']['id'], allow_cancelled=allow_cancelled)
        if wrapper['case'].get('latestQuote', {}).get('id') != quote_id:
            raise ValueError('舊版報價已失效')
        return wrapper

    def is_allowed(self, case):
        try:
            data = _case_data(case)
            marker = data.get('paymentWorkflow')
            if 'paymentWorkflow' not in data:
                return True
            if marker != WORKFLOW:
                return False
            with self.connect() as c:
                link = c.execute('SELECT * FROM wb_prod_links WHERE real_id=?', (case['id'],)).fetchone()
            if not link or _fingerprint(case) != link['source_hash']:
                return False
            self._current(link['wb_id'])
            detail = self.desk.get_case(link['wb_id'])['case']
            quote = detail.get('latestQuote')
            preview = self.sync.preview(link['wb_id'])
            row = preview['rows'][0]
            queue = next((q for q in preview['queue'] if q['caseId'] == link['wb_id']), {})
            if (not quote or quote['status'] != 'active' or row['quoteVersion'] != quote['version']
                    or row['amountDue'] != quote['total'] or queue.get('status') != 'synced'
                    or row['syncRevision'] != queue.get('revision')):
                return False
            if row['paymentStatus'] == '免付款':
                return quote['total'] == 0 and quote['paymentStatus'] == 'no_payment_required'
            if row['paymentStatus'] != '已付款' or row['amountPaid'] != quote['total']:
                return False
            checked = datetime.fromisoformat(row['checkedAt'].replace('Z', '+00:00'))
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=TAIPEI)
            return 0 <= (datetime.now(TAIPEI) - checked).total_seconds() <= 300
        except Exception:
            return False

    def can_requote_free(self, wb_id):
        try:
            self._current(wb_id)
            return self.desk.can_requote_free(wb_id) is True
        except Exception:
            return False

    def warranty_policy(self, wb_id):
        allowed = False
        try:
            data = _case_data(self._current(wb_id))
            order = data.get('order')
            allowed = (data.get('orderChoice') != 'missing'
                and type(order) is str and bool(order.strip()))
        except Exception:
            pass
        return {'warrantyConfirmationAllowed': allowed,
                'warrantyPolicy': '待客服核實' if allowed else '保固外'}

    def _queue_message(self, kind, quote, row=None):
        target = self.recipient(quote['caseId'])
        if kind == 'quote':
            payload, number = quote, ''
        else:
            payload = {key: quote[key] for key in ('id', 'caseId', 'caseNumber', 'name', 'version', 'total', 'currency',
                'internalOnly', 'realPayment', 'releaseAllowed', 'simulation')}
            number = row['paymentOrderNumber']
            payload.update(orderNumber=number, paidAt=row['paidAt'], source='shopline_api_completed')
            if kind == 'refund':
                followups = self.reconciliation.refund_followups(quote['id'])['followups']
                followup = next((f for f in followups if f['orderNumber'] == number), None)
                if not followup or followup['providerStatus'] not in ('refunding', 'refunded'):
                    return
                payload.update(source='shopline_api_refund', providerStatus=followup['providerStatus'])
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO wb_prod_messages(kind,quote_id,order_number,user_id,request_id,payload) VALUES(?,?,?,?,?,?)',
                (kind, quote['id'], number, target['userId'], str(uuid.uuid4()), _dump(payload)))

    def after_payment(self, quote_id):
        wrapper = self.wrapper(quote_id, allow_cancelled=True)
        quote, wb = wrapper['quote'], wrapper['case']['id']
        self.sync.enqueue(wb)
        self.sheet.wake()
        row = self.sync.preview(wb)['rows'][0]
        case = self._current(wb, allow_cancelled=True)
        if row['paymentStatus'] in ('已退款', '退款需處理'):
            self.s['hold_payment_case'](case['id'])
            if row['paymentStatus'] == '已退款':
                self._queue_message('refund', quote, row)
        elif row['paymentStatus'] == '已付款':
            self._queue_message('receipt', quote, row)
        if self.is_allowed(case):
            self.s['promote_payment_case'](case['id'])
        self.wake()
        return row

    def reconcile(self, quote_id, payload, actor='系統', manual=False):
        expected = {'orderNumber', 'requestId', 'confirm', 'reason'} if manual else {'orderNumber', 'requestId'}
        if type(payload) is not dict or set(payload) != expected:
            raise ValueError('訂單核對欄位不正確')
        _uuid(payload['requestId'])
        wrapper = self.wrapper(quote_id)
        order = self.provider.exact(payload['orderNumber'])
        provenance = {'freshProviderLookup': True, 'readOnly': True}
        if manual:
            if not isinstance(payload.get('reason'), str) or len(payload['reason'].strip()) < 8:
                raise ValueError('人工核實理由至少 8 字')
            result = self.reconciliation.record_manual(order, wrapper, payload['requestId'],
                provenance=provenance, confirm=payload['confirm'], reason=payload['reason'], actor=actor)
        else:
            result = self.reconciliation.record(order, wrapper, payload['requestId'], provenance=provenance)
        self.after_payment(quote_id)
        return {'mode': 'production', 'result': result['result'], 'payment': self.detail(wrapper['case']['caseNumber'])['payment']}

    def _messages(self):
        if not self.setting('notifications_enabled'):
            return
        with self.connect() as c:
            c.execute("UPDATE wb_prod_messages SET status='retry',leased_until=0 WHERE status='working' AND leased_until<=?", (time.time(),))
            rows = c.execute("SELECT * FROM wb_prod_messages WHERE status IN ('pending','retry') AND next_attempt<=? ORDER BY id LIMIT 20", (time.time(),)).fetchall()
        for entry in rows:
            try:
                wrapper = self.wrapper(entry['quote_id'], allow_cancelled=entry['kind'] == 'refund')
                quote = wrapper['quote']
                target = self.recipient(quote['caseId'])
                if target['userId'] != entry['user_id']:
                    raise ValueError('recipient_changed')
                row = self.sync.preview(quote['caseId'])['rows'][0]
                eligible = (entry['kind'] == 'quote' and row['paymentStatus'] in ('待付款', '需人工核對')
                    or entry['kind'] == 'receipt' and row['paymentStatus'] == '已付款'
                    or entry['kind'] == 'refund' and row['paymentStatus'] == '已退款')
                if not eligible:
                    raise ValueError('notification_no_longer_current')
                now = time.time()
                first = entry['first_attempt'] or now
                if entry['attempts'] >= 10 or now - first >= 23 * 3600:
                    raise ValueError('retry_window_expired')
                with self.connect() as c:
                    c.execute("UPDATE wb_prod_messages SET status='working',attempts=attempts+1,first_attempt=?,leased_until=? WHERE id=? AND status IN ('pending','retry')", (first, now + 60, entry['id']))
                send = {'quote': self.sender.send, 'receipt': self.sender.send_receipt,
                    'refund': self.sender.send_refund_notice}[entry['kind']]
                result = send(json.loads(entry['payload']), entry['request_id'])
                accepted = result.get('state') in ('accepted', 'duplicate') and result.get('code') in ('accepted', 'already_accepted', 'line_accepted', 'duplicate_accepted')
                # Some safe send engines use accepted state with a provider-specific success code.
                accepted = accepted or result.get('state') == 'accepted'
                with self.connect() as c:
                    c.execute('UPDATE wb_prod_messages SET status=?,next_attempt=?,last_error=?,accepted_at=?,leased_until=0 WHERE id=?',
                        ('accepted' if accepted else 'retry' if result.get('retryable') else 'failed',
                         now + min(300, 5 * 2 ** min(entry['attempts'], 6)), '' if accepted else str(result.get('code', 'send_failed'))[:80],
                         _now() if accepted else '', entry['id']))
                # One network submission per worker cycle. The global LINE
                # cooldown must not consume attempts of later queued customers.
                return
            except ValueError:
                with self.connect() as c:
                    c.execute("UPDATE wb_prod_messages SET status='cancelled',last_error='current_case_or_payment_changed' WHERE id=? AND status<>'accepted'", (entry['id'],))
            except Exception:
                with self.connect() as c:
                    c.execute("UPDATE wb_prod_messages SET status='retry',next_attempt=?,leased_until=0,last_error='temporary_delivery_or_storage_error' WHERE id=? AND status<>'accepted'", (time.time() + 30, entry['id']))
                return

    def _scan(self):
        now = time.time()
        if now - self.last_scan < 90:
            return
        self.last_scan = now
        with self.connect() as c:
            links = [dict(r) for r in c.execute('SELECT * FROM wb_prod_links ORDER BY enrolled_at')]
        # Bound orders are refreshed individually even when recent search fails/truncates.
        for link in links:
            try:
                detail = self.desk.get_case(link['wb_id'])['case']
                quote = detail.get('latestQuote')
                if not quote or quote['total'] == 0:
                    continue
                number = self.reconciliation.bound_order_number(quote['id'])
                if number:
                    order = self.provider.exact(number)
                    self.reconciliation.record(order, self.wrapper(quote['id'], allow_cancelled=True), str(uuid.uuid4()),
                        provenance={'freshProviderLookup': True, 'readOnly': True})
                    self.after_payment(quote['id'])
                    self.stop_event.wait(2.1)
            except ProviderBusy:
                continue
            except Exception:
                self.last_error = 'bound_order_refresh_failed'
        try:
            state = self.provider.fetch({'days': 7})
            if state.get('status') != 'ok' or state.get('truncated') is True:
                self.last_error = 'recent_orders_incomplete'
                return
            for link in links:
                try:
                    detail = self.desk.get_case(link['wb_id'])['case']
                    quote = detail.get('latestQuote')
                    if not quote or quote['total'] == 0 or self.reconciliation.bound_order_number(quote['id']):
                        continue
                    wrapper = self.wrapper(quote['id'])
                except Exception:
                    continue
                for order in state.get('orders', []):
                    remarks = order.get('orderRemarks', '')
                    if not re.search(r'(?:送修編號|維修案件編號|案件編號)[：:]\s*' + re.escape(link['real_id']) + r'(?![0-9])', remarks):
                        continue
                    try:
                        self.reconciliation.record(order, wrapper, str(uuid.uuid4()),
                            provenance={'freshProviderLookup': True, 'readOnly': True})
                        self.after_payment(quote['id'])
                    except Exception:
                        continue
            self.last_error = ''
        except ProviderBusy:
            pass
        except Exception:
            self.last_error = 'recent_order_refresh_failed'

    def run_once(self):
        if not self.cycle_lock.acquire(False):
            return
        try:
            with self.s['connect']() as c:
                cases = [dict(r) for r in c.execute("SELECT * FROM cases WHERE json_extract(data,'$.paymentWorkflow')=?", (WORKFLOW,))]
            for case in cases:
                try:
                    self.enroll(case['id'])
                except Exception:
                    continue
            with self.connect() as c:
                links = list(c.execute('SELECT * FROM wb_prod_links'))
            # Recover a crash between quote commit and notification scheduling.
            for link in links:
                try:
                    wrapper_case = self.desk.get_case(link['wb_id'])['case']
                    quote = wrapper_case.get('latestQuote')
                    if not quote:
                        continue
                    self.sync.enqueue(link['wb_id'])
                    self.sheet.wake()
                    row = self.sync.preview(link['wb_id'])['rows'][0]
                    if quote['total'] and row['paymentStatus'] in ('待付款', '需人工核對'):
                        self._queue_message('quote', quote)
                    elif row['paymentStatus'] == '已付款':
                        self._queue_message('receipt', quote, row)
                    elif row['paymentStatus'] == '已退款':
                        self._queue_message('refund', quote, row)
                except Exception:
                    continue
            self._scan()
            self._messages()
            with self.connect() as c:
                links = list(c.execute('SELECT * FROM wb_prod_links'))
            for link in links:
                try:
                    case = self._current(link['wb_id'])
                    if self.is_allowed(case):
                        self.s['promote_payment_case'](case['id'])
                except Exception:
                    pass
            if time.time() - self.last_backup >= 86400:
                self._backup()
                self.last_backup = time.time()
        finally:
            self.cycle_lock.release()

    def _loop(self):
        with self.connect() as c:
            # A crash after the provider accepted reuses the durable LINE retry UUID.
            c.execute("UPDATE wb_prod_messages SET status='retry' WHERE status='working'")
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                self.last_error = 'payment_worker_failed'
            self.wake_event.wait(5)
            self.wake_event.clear()

    def wake(self):
        self.wake_event.set()

    def stop(self):
        self.stop_event.set()
        self.wake()
        self.sheet.stop()

    @staticmethod
    def _notification_display(message=None):
        status = message['status'] if message else 'not_queued'
        labels = {
            'not_queued': '尚未排程 LINE 通知。',
            'pending': 'LINE 通知等待傳送。',
            'working': 'LINE 通知正在傳送，結果尚未確認。',
            'retry': 'LINE 通知等待使用原識別碼重試，結果尚未確認。',
            'accepted': 'LINE 平台已接受通知；尚未確認送達或已讀。',
            'failed': 'LINE 通知傳送失敗，請由客服確認。',
            'cancelled': 'LINE 通知已停止，未認定為已送達。',
        }
        return {'mode': 'production', 'status': status,
            'attempts': message.get('attempts', 0) if message else 0,
            'lastError': message.get('last_error', '') if message else '',
            'acceptedAt': message.get('accepted_at', '') if message and status == 'accepted' else '',
            'message': labels.get(status, 'LINE 通知狀態待確認。')}

    @classmethod
    def _quote_display(cls, quote, messages):
        if quote is None:
            return None
        current = next((message for message in messages
            if message['kind'] == 'quote' and message['quote_id'] == quote['id']), None)
        notification = cls._notification_display(current)
        if quote['total'] == 0 and current is None:
            notification.update(status='not_required', message='本次核定免付款，無須發送付款連結。')
        # Replace only the public projection. The calculation engine and its
        # original stored audit remain intact for reproducible verification.
        return {**quote, 'notification': notification}

    @classmethod
    def _audit_display(cls, audit, messages, last_check=None):
        rows = []
        if last_check:
            rows.append({'action': 'production_order_check', 'createdAt': last_check['checkedAt'],
                'detail': ('付款訂單 ' + last_check['orderNumber'] + '：' if last_check['orderNumber'] else '付款訂單核對：')
                    + last_check['message']})
        kind_labels = {'quote': '付款通知', 'receipt': '付款確認', 'refund': '退款通知'}
        for message in messages:
            if message['kind'] not in kind_labels:
                continue
            notice = cls._notification_display(message)
            rows.append({'action': 'production_line_' + message['kind'] + '_' + notice['status'],
                'createdAt': notice['acceptedAt'],
                'detail': kind_labels[message['kind']] + '：' + notice['message']})
        for entry in audit:
            action = entry.get('action', '')
            # These are calculation-engine exercises, not production transport
            # evidence. Actual delivery status is taken from the outbox above.
            if action in ('notification_simulated', 'notification_failed'):
                continue
            entry = dict(entry)
            if action == 'case_created':
                entry['detail'] = '建立付款核對紀錄'
            elif action == 'real_order_check_matched_internal_only':
                entry['detail'] = '付款訂單已核對配對；目前結果請見付款狀態。'
            elif action == 'real_order_check_duplicate':
                entry['detail'] = '付款訂單已重新核對，保留原配對紀錄。'
            elif action == 'real_order_check_blocked':
                entry['detail'] = '訂單核對結果已記錄；目前結果請見付款與退款狀態。'
            rows.append(entry)
        return rows[:100]

    @staticmethod
    def _check_display(row):
        """Business-only projection; never expose provider text, facts or IDs."""
        try:
            response = json.loads(row['response'])
            result = response.get('result', {}) if type(response) is dict else {}
            result = result if type(result) is dict else {}
        except (ValueError, TypeError):
            result = {}
        state = result.get('state')
        state = state if state in ('matched_internal_only', 'duplicate', 'blocked') else 'unknown'
        code = result.get('code')
        code = code if type(code) is str and code in (*CHECK_REASONS, 'matched_internal_only', 'already_matched_internal_only') else 'unknown'
        raw_reasons = result.get('reasons')
        raw_reasons = raw_reasons if type(raw_reasons) is list else []
        reasons = list(dict.fromkeys(reason for reason in raw_reasons[:50]
            if type(reason) is str and reason in CHECK_REASONS))
        unknown_reason = any(type(reason) is not str or reason not in CHECK_REASONS for reason in raw_reasons[:50])
        if state == 'matched_internal_only' and code == 'matched_internal_only' and not raw_reasons:
            message = '付款訂單已核對配對；安排送修前仍須確認付款與雲端同步狀態。'
        elif state == 'duplicate' and code == 'already_matched_internal_only' and not raw_reasons:
            message = '此訂單已有相同配對紀錄，未重複計入付款；目前結果請見付款狀態。'
        else:
            if not reasons and code in CHECK_REASONS:
                reasons = [code]
            descriptions = [CHECK_REASONS[reason] for reason in reasons]
            if 'refunded' in reasons:
                facts = result.get('facts') if type(result.get('facts')) is dict else {}
                refund = facts.get('providerPaymentStatus')
                refund = refund if type(refund) is str else ''
                descriptions[reasons.index('refunded')] = {
                    'refunding': '商城已受理退款（平台狀態：退款中），依公司流程視為已退款，停止派車。',
                    'refunded': '商城回報已退款，此訂單不能作為可用付款，停止派車。',
                    'partially_refunded': '商城回報部分退款，需客服確認退款處理，目前停止派車。',
                }.get(refund, CHECK_REASONS['refunded'])
            elif reasons == ['missing_remark'] and not unknown_reason:
                descriptions.append('請先核實客戶資料與付款訂單，再使用「漏填下單備註」人工配對。')
            message = ' '.join(descriptions) or '核對結果尚未確認，請由管理員重新查詢。'
            if unknown_reason:
                message += ' 另有未識別的核對原因，請由管理員確認。'
        number = row['order_number']
        number = number if type(number) is str and ORDER.fullmatch(number) else ''
        stamp = row['created_at']
        if (type(stamp) is not str or not re.fullmatch(
                r'[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:[+-][0-9]{2}:[0-9]{2}|Z)?', stamp)):
            stamp = ''
        if stamp:
            try:
                datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            except ValueError:
                stamp = ''
        return {'orderNumber': number, 'state': state, 'code': code,
            'reasons': reasons, 'message': message, 'checkedAt': stamp}

    def detail(self, real_id):
        case = self._repair(real_id)
        data = _case_data(case)
        with self.connect() as c:
            link = c.execute('SELECT * FROM wb_prod_links WHERE real_id=?', (real_id,)).fetchone()
        result = {'id': real_id, 'name': data.get('name', ''), 'phone': data.get('phone', ''),
            'model': data.get('model', ''), 'shipping': data.get('shipping', ''), 'address': data.get('pickupAddress') or data.get('returnAddress', ''),
            'lineName': case.get('line_display_name') or data.get('name', ''),
            'managed': 'paymentWorkflow' in data, 'legacy': 'paymentWorkflow' not in data,
            'version': 0, 'quote': None, 'payment': None, 'quoteHistory': [], 'audit': [],
            'receipts': [], 'refundNotices': [], 'notifications': [], 'lastCheck': None,
            'releaseAllowed': self.is_allowed(case), 'canRequoteFree': False,
            'warrantyConfirmationAllowed': False, 'warrantyPolicy': '保固外'}
        if link:
            result['canRequoteFree'] = self.can_requote_free(link['wb_id'])
            result.update(self.warranty_policy(link['wb_id']))
            detail = self.desk.get_case(link['wb_id'])
            result.update(version=detail['case']['version'], quote=detail['case']['latestQuote'],
                quoteHistory=detail['quotes'])
            preview = self.sync.preview(link['wb_id'])
            if preview['rows']:
                payment = preview['rows'][0]
                result['payment'] = {**payment, 'sync': next((q for q in preview['queue'] if q['caseId'] == link['wb_id']), {})}
            with self.connect() as c:
                messages = [dict(r) for r in c.execute('SELECT kind,quote_id,order_number,status,attempts,last_error,accepted_at FROM wb_prod_messages WHERE quote_id IN (SELECT id FROM wb_quotes WHERE case_id=?) ORDER BY id DESC', (link['wb_id'],))]
                check = c.execute('''SELECT order_number,created_at,response FROM wb_real_order_checks
                    WHERE case_id=? AND quote_id=? ORDER BY rowid DESC LIMIT 1''',
                    (link['wb_id'], result['quote']['id'])).fetchone() if result['quote'] else None
            result['lastCheck'] = self._check_display(check) if check else None
            result['notifications'] = messages
            result['quote'] = self._quote_display(result['quote'], messages)
            result['quoteHistory'] = [self._quote_display(quote, messages) for quote in detail['quotes']]
            result['audit'] = self._audit_display(detail['audit'], messages, result['lastCheck'])
            result['receipts'] = [r for r in messages if r['kind'] == 'receipt']
            result['refundNotices'] = [r for r in messages if r['kind'] == 'refund']
            result['refunds'] = self.reconciliation.refund_followups(result['quote']['id']) if result['quote'] else {'followups': []}
        return result

    def state(self, query=''):
        with self.s['connect']() as c:
            rows = [dict(r) for r in c.execute('SELECT * FROM cases ORDER BY created DESC,id DESC LIMIT 1000')]
        query = str(query).strip().lower()[:100]
        selected = []
        for row in rows:
            data = _case_data(row)
            if query and not any(query in str(value).lower() for value in
                    (row['id'], data.get('name'), data.get('phone'), data.get('order'), data.get('model'))):
                continue
            selected.append(self.detail(row['id']))
        return {'enabled': True, 'mode': 'production', 'newCasesEnabled': self.new_cases_enabled,
            'notificationsEnabled': self.setting('notifications_enabled'), 'cases': selected,
            'automation': {'lastScanAt': datetime.fromtimestamp(self.last_scan, TAIPEI).isoformat() if self.last_scan else '',
                'lastError': self.last_error}, 'sheetUrl': SHEET_URL, 'sheet': self.sheet.status()}

    def handle_get(self, handler, path, query):
        if path != '/admin/payments' and not path.startswith('/api/payments/'):
            return False
        user = handler.user()
        if path == '/admin/payments':
            body = (Path(self.s['ROOT']) / 'payments.html').read_bytes()
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.send_header('Cache-Control', 'no-store')
            handler.send_header('Content-Length', str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return True
        if not user or not user.get('admin'):
            handler.send(401, {'error': '請先登入管理員'})
            return True
        try:
            if path == '/api/payments/state':
                query = parse_qs(query) if isinstance(query, str) else query
                handler.send(200, self.state(query.get('q', [''])[0]))
            elif match := re.fullmatch(r'/api/payments/cases/(R[0-9]{8}-[0-9]{4,8})', path):
                handler.send(200, {'mode': 'production', 'case': self.detail(match[1])})
            else:
                handler.send(404, {'error': '找不到付款功能'})
        except Exception:
            handler.send(409, {'error': '付款資料暫時無法完整核對，請更新重試'})
        return True

    def handle_post(self, handler, path, payload, user):
        if not path.startswith('/api/payments/'):
            return False
        if handler.headers.get('Origin') != self.s['BASE']:
            handler.send(403, {'error': '付款操作來源不正確'})
            return True
        if not user or not user.get('admin'):
            handler.send(403, {'error': '需要管理員權限'})
            return True
        try:
            if path == '/api/payments/settings':
                if type(payload) is not dict or set(payload) != {'requestId', 'newCasesEnabled', 'notificationsEnabled'}:
                    raise ValueError('付款啟用選項不正確')
                _uuid(payload['requestId'])
                if any(type(payload[key]) is not bool for key in ('newCasesEnabled', 'notificationsEnabled')):
                    raise ValueError('付款啟用選項不正確')
                with self.connect() as c:
                    for key, field in (('new_cases_enabled', 'newCasesEnabled'), ('notifications_enabled', 'notificationsEnabled')):
                        c.execute('UPDATE wb_prod_settings SET value=? WHERE key=?', ('1' if payload[field] else '0', key))
                self.wake()
                handler.send(200, self.state())
            elif match := re.fullmatch(r'/api/payments/cases/(R[0-9]{8}-[0-9]{4,8})/quote', path):
                if type(payload) is not dict or set(payload) != {'requestId', 'repairFee', 'warranty', 'expectedVersion'}:
                    raise ValueError('核定金額欄位不正確')
                wb = self.enroll(match[1])
                self._current(wb)
                if payload['warranty'] is True and not self.warranty_policy(wb)['warrantyConfirmationAllowed']:
                    raise ValueError('未提供原購買訂單的案件一律屬保固外；可核定免收費，但不能勾選保固內')
                case = self.desk.get_case(wb)['case']
                if type(payload['repairFee']) is not int or payload['repairFee'] + (350 if case['pickup'] else 0) > 100000:
                    raise ValueError('本次應付合計不可超過 100,000 元')
                result = self.desk.approve_quote(wb, payload,
                    allow_free_requote=self.can_requote_free(wb))
                if result['quote']['total']:
                    self._queue_message('quote', result['quote'])
                self.after_payment(result['quote']['id'])
                handler.send(200, {'mode': 'production', 'case': self.detail(match[1])})
            elif match := re.fullmatch(r'/api/payments/quotes/(WQ-[0-9a-f-]{36})/(reconcile|manual-match|refund-refresh|refund-close)', path):
                quote_id, action = match.groups()
                if action in ('reconcile', 'manual-match'):
                    result = self.reconcile(quote_id, payload, user.get('displayName') or '管理員', action == 'manual-match')
                else:
                    expected = {'requestId', 'reason', 'confirm'} if action == 'refund-close' else {'requestId'}
                    if type(payload) is not dict or set(payload) != expected:
                        raise ValueError('退款追蹤欄位不正確')
                    _uuid(payload['requestId'])
                    wrapper = self.wrapper(quote_id, allow_cancelled=True)
                    number = self.reconciliation.bound_order_number(quote_id)
                    if not number:
                        raise ValueError('此案沒有已核對付款訂單')
                    order = self.provider.exact(number)
                    self.reconciliation.record(order, wrapper, str(uuid.uuid4()), provenance={'freshProviderLookup': True, 'readOnly': True})
                    if action == 'refund-close':
                        if not isinstance(payload.get('reason'), str) or len(payload['reason'].strip()) < 8:
                            raise ValueError('退款追蹤結案理由至少 8 字')
                        self.reconciliation.close_refund(quote_id, payload, actor=user.get('displayName') or '管理員')
                    payment = self.after_payment(quote_id)
                    result = {'mode': 'production', 'payment': payment,
                        'refunds': self.reconciliation.refund_followups(quote_id)}
                handler.send(200, result)
            else:
                handler.send(404, {'error': '找不到付款操作'})
        except ProviderBusy:
            handler.send(429, {'error': '商城核對進行中，請稍候數秒再試'})
        except ValueError as error:
            # These exceptions originate from bounded validators; never echo provider IO errors.
            handler.send(409, {'error': str(error)[:180]})
        except Exception:
            handler.send(503, {'error': '付款操作暫時無法完成，原紀錄已保留，請重新整理確認'})
        return True


def start_payments(server):
    config_path = Path(os.environ.get('REPAIR_PAYMENT_CONFIG_SOURCE', '/etc/secrets/payment-config.json'))
    if not config_path.exists():
        return None
    if config_path.stat().st_size > 16384:
        raise ValueError('付款設定檔過大')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    if type(config) is not dict or set(config) != {'shoplineApiToken'}:
        raise ValueError('付款設定檔格式不正確')
    token = config['shoplineApiToken']
    if not isinstance(token, str) or not 20 <= len(token) <= 4096 or any(not 32 < ord(c) < 127 for c in token):
        raise ValueError('商城唯讀憑證格式不正確')
    if server.get('DEMO') or server.get('BASE') != 'https://ad-creative-platform.onrender.com':
        raise ValueError('正式付款只能在正式維修服務啟用')
    return ProductionPayments(server, config)
