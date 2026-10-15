"""Formal LINE notices from saved payment facts and a fresh server case binding.

The host owns durable outboxes and their original retry UUIDs. This adapter
accepts no browser recipient or arbitrary message/URL. Its small HTTP-engine
cache may evict entries; the host ledger remains authoritative after restart.
"""
from collections import OrderedDict
from datetime import datetime
import hashlib
import re
import threading
import time

from line_test_sender import (LineTestSender, PRODUCT_URL, RETRY_WINDOW,
    MAX_ATTEMPTS, GLOBAL_COOLDOWN, _default_opener, _json, _safe_text,
    _token_valid, _uuid4)


_FLAGS = {'mode': 'production', 'simulation': False, 'internalOnly': True,
          'realPayment': False, 'releaseAllowed': False}
_SOURCES = ('shopline_api_completed', 'shopline_api_manual_completed')


def _base(value):
    if type(value) is not dict:
        raise ValueError('通知必須使用已保存的案件資料')
    for key, expected in (('internalOnly', True), ('simulation', True),
                          ('realPayment', False), ('releaseAllowed', False)):
        if value.get(key) is not expected:
            raise ValueError('通知計算資料的來源不正確')
    for key, prefix in (('id', 'WQ-'), ('caseId', 'WB-')):
        if type(value.get(key)) is not str or not value[key].startswith(prefix):
            raise ValueError('通知識別碼不正確')
        _uuid4(value[key][3:])
    if (type(value.get('version')) is not int or not 1 <= value['version'] <= 1000000
            or type(value.get('total')) is not int or not 0 <= value['total'] <= 100350
            or value.get('currency') != 'TWD'):
        raise ValueError('通知金額或版本不正確')
    number = _safe_text(value.get('caseNumber'), 80)
    name = _safe_text(value.get('name'), 100)
    if (not re.fullmatch(r'R[0-9]{8}-[0-9]{4,8}', number)
            or re.search(r'(?i)(?:https?|ftp)://|www\.', name)):
        raise ValueError('通知案件資料不正確')
    return number, name


class _ProductionHttpSender(LineTestSender):
    """Reuse the fixed HTTPS transport/retry engine without its test setup/UI."""
    def __init__(self, *, token_getter, user_id, label, kind, opener, clock):
        self._token_getter, self._allowed_user_id = token_getter, user_id
        self._allowed, self._opener, self._clock = True, opener, clock
        self._lock, self._records = threading.Lock(), {}
        self._quote_accepted, self._quote_pending, self._last_attempt = {}, {}, None
        self.label, self.kind = label, kind

    def _payload(self, value):
        number, name = _base(value)
        total = value['total']
        if self.kind == 'notice':
            fee, pickup = value.get('repairFee'), value.get('pickupFee')
            if (value.get('status') != 'active' or value.get('paymentStatus') not in
                    ('awaiting_payment', 'no_payment_required')
                    or type(fee) is not int or not 0 <= fee <= 100000
                    or type(pickup) is not int or pickup not in (0, 350)
                    or fee + pickup != total
                    or (value.get('paymentStatus') == 'no_payment_required') != (total == 0)):
                raise ValueError('請先核定目前報價')
            remark = '送修編號：' + number + '\n申請人姓名：' + name
            if value.get('clipboardText') != remark:
                raise ValueError('下單備註與案件不符')
            text = ('【維修費用付款通知】\n維修編號：' + number + '\n申請人：' + name
                + '\n維修金額：NT$' + format(fee, ',')
                + '\n派車回收費：NT$' + format(pickup, ',')
                + '\n應付合計：NT$' + format(total, ','))
            if not total:
                return value['id'], {'to': self._allowed_user_id, 'messages': [
                    {'type': 'text', 'text': text + '\n\n本次核定無須付款，請依客服指示安排送修。'}]}
            text += ('\n\n請至維修費用一元賣場下單，數量填「' + str(total)
                + '」，結帳總額應為 NT$' + format(total, ',')
                + '。\n\n【訂單備註必填】\n' + remark
                + '\n\n請填本次維修編號與申請人姓名，以便核對付款。'
                + '\n請勿與其他商品合併下單，亦不適用折扣或購物金。'
                + '\n付款完成後，系統核對成功會另發付款確認。')
            _safe_text(text, 3500, True)
            bubble = {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical',
                'contents': [{'type': 'text', 'text': text, 'wrap': True, 'size': 'sm', 'color': '#193D35'}]},
                'footer': {'type': 'box', 'layout': 'vertical', 'spacing': 'sm', 'contents': [
                    {'type': 'button', 'style': 'secondary', 'action': {'type': 'clipboard',
                        'label': '複製下單備註', 'clipboardText': remark}},
                    {'type': 'button', 'style': 'primary', 'color': '#315E51',
                        'action': {'type': 'uri', 'label': '前往維修費用付款', 'uri': PRODUCT_URL}}]}}
            return value['id'], {'to': self._allowed_user_id, 'messages': [
                {'type': 'flex', 'altText': '維修費用付款通知｜' + number, 'contents': bubble}]}
        required = {'id', 'caseId', 'caseNumber', 'name', 'version', 'total',
            'currency', 'orderNumber', 'paidAt', 'source', 'internalOnly',
            'realPayment', 'releaseAllowed', 'simulation'}
        if self.kind == 'refund':
            required.add('providerStatus')
        if set(value) != required or total <= 0:
            raise ValueError('付款結果通知的固定欄位不正確')
        order = _safe_text(value.get('orderNumber'), 64)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', order):
            raise ValueError('付款訂單編號不正確')
        stamp = _safe_text(value.get('paidAt'), 64)
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
                           r'(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?', stamp):
            raise ValueError('付款時間不正確')
        datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if self.kind == 'refund':
            if value.get('source') != 'shopline_api_refund' or value.get('providerStatus') not in ('refunding', 'refunded'):
                raise ValueError('退款通知須由平台回報全額退款中或已退款')
            text = ('【維修退款通知】\n維修編號：' + number + '\n付款訂單編號：' + order
                + '\n退款金額：NT$' + format(total, ',')
                + '\n\n此筆維修付款訂單已取消，已辦理退款。'
                + '\n退款入帳時間依原付款方式與發卡銀行作業為準。')
        else:
            if value.get('source') not in _SOURCES:
                raise ValueError('付款確認須使用已核對的訂單')
            text = ('【維修付款確認】\n維修編號：' + number + '\n付款訂單編號：' + order
                + '\n付款金額：NT$' + format(total, ',')
                + '\n\n付款已核對完成，後續由客服安排送修。')
        _safe_text(text, 1000, True)
        return value['id'], {'to': self._allowed_user_id, 'messages': [{'type': 'text', 'text': text}]}

    def _result(self, state, code, message, request_id='', quote_id='', retryable=False, **extra):
        if state == 'duplicate' and code == 'quote_cooldown':
            code = 'already_accepted'
        text = ('LINE 平台已接受通知；送達或已讀狀態尚未確認。' if state in ('accepted', 'duplicate')
            else '通知傳送結果待確認，請保留原請求識別碼重試。' if retryable
            else '通知尚未送出，請確認案件綁定或連線設定。')
        return {**_FLAGS, 'state': state, 'code': code, 'message': text,
            'requestId': request_id, 'quoteId': quote_id, 'recipientLabel': self.label,
            'notificationKind': {'notice': 'payment_notice', 'receipt': 'payment_receipt', 'refund': 'refund_notice'}[self.kind],
            'retryable': retryable, **extra}


class ProductionPaymentSender:
    """One immutable notice per host-owned outbox; fresh real-case routing only."""
    def __init__(self, token_getter, recipient_resolver, *, opener=None, clock=time.monotonic):
        if (not callable(token_getter) or not callable(recipient_resolver) or not callable(clock)
                or opener is not None and not callable(opener)):
            raise ValueError('正式付款 LINE 設定不正確')
        self.token_getter, self.resolve = token_getter, recipient_resolver
        self.opener, self.clock = opener or _default_opener, clock
        self._lock, self._engines = threading.Lock(), OrderedDict()
        self._requests, self._targets, self._payloads, self._accepted, self._pending = {}, {}, {}, {}, {}
        self._last_attempt = None

    def status(self):
        try:
            configured = _token_valid(self.token_getter())
        except Exception:
            configured = False
        return {**_FLAGS, 'configured': configured, 'enabled': configured, 'canSend': configured,
            'recipientMode': 'production_case_bound', 'recipientLabel': '案件已驗證的客戶 LINE',
            'message': '依正式案件已驗證的 LINE 帳號發送付款與退款通知。',
            'idempotencyStorage': 'host_persistent_outbox', 'retryWindowSeconds': RETRY_WINDOW}

    def binding(self, quote):
        _base(quote)
        target = self.resolve(quote['caseId'])
        if (type(target) is not dict or target.get('verified') is not True
                or type(target.get('userId')) is not str
                or not re.fullmatch(r'U[0-9a-fA-F]{32}', target['userId'])):
            raise ValueError('案件尚未綁定已驗證的客戶 LINE')
        label = _safe_text(target.get('displayName'), 100)
        return {'verified': True, 'userId': target['userId'], 'displayName': label}

    @staticmethod
    def _blocked(code='unverified_recipient', retryable=False):
        return {**_FLAGS, 'state': 'needs_review' if retryable else 'failed', 'code': code,
            'retryable': retryable, 'message': '通知尚未送出，請確認案件綁定或使用原請求重試。'}

    def send(self, quote, request_id):
        return self._send('notice', quote, request_id)

    def send_receipt(self, receipt, request_id):
        return self._send('receipt', receipt, request_id)

    def send_refund_notice(self, receipt, request_id):
        return self._send('refund', receipt, request_id)

    def _send(self, kind, value, request_id):
        try:
            _uuid4(request_id)
            target = self.binding(value)
            uid, label = target['userId'], target['displayName']
            if not self._lock.acquire(blocking=False):
                return self._blocked('send_busy', True)
            try:
                now = self.clock()
                # Identity pins survive cache eviction. They live for this host
                # process; the formal host must also freeze case→UID in its DB.
                if self._targets.get(value['caseId'], uid) != uid:
                    return self._blocked('recipient_changed')
                cache_key = (kind, value['id'])
                engine = self._engines.get(cache_key)
                if engine is None:
                    engine = _ProductionHttpSender(token_getter=self.token_getter,
                        user_id=uid, label=label, kind=kind, opener=self.opener, clock=self.clock)
                quote_id, payload = engine._payload(value)
                fingerprint = hashlib.sha256(_json({'kind': kind, 'quote': {
                    key: value[key] for key in ('id', 'caseId', 'version', 'total', 'currency')},
                    'payload': payload})).hexdigest()
                prior = self._requests.get(request_id)
                if prior and prior['fingerprint'] != fingerprint:
                    return self._blocked('request_conflict')
                if self._payloads.get(cache_key, fingerprint) != fingerprint:
                    return self._blocked('quote_changed')
                if prior and prior['accepted']:
                    return engine._result('duplicate', 'already_accepted', '', request_id, quote_id)
                if cache_key in self._accepted:
                    return engine._result('duplicate', 'already_accepted', '', request_id, quote_id)
                if self._pending.get(cache_key, request_id) != request_id:
                    return self._blocked('use_original_request', True)
                if prior and (prior['attempts'] >= MAX_ATTEMPTS or now - prior['created'] >= RETRY_WINDOW):
                    return self._blocked('retry_expired')
                if self._last_attempt is not None and now - self._last_attempt < GLOBAL_COOLDOWN:
                    return self._blocked('send_cooldown', True)
                self._targets[value['caseId']] = uid
                self._payloads[cache_key] = fingerprint
                self._engines[cache_key] = engine
                self._engines.move_to_end(cache_key)
                while len(self._engines) > 256:
                    self._engines.popitem(last=False)
                record = prior or {'fingerprint': fingerprint, 'created': now, 'attempts': 0, 'accepted': False}
                self._requests[request_id] = record
                before = engine._last_attempt
                result = engine.send(value, request_id)
                if engine._last_attempt != before:
                    record['attempts'] += 1
                    self._last_attempt = now
                record['accepted'] = result.get('state') == 'accepted' or (
                    result.get('state') == 'duplicate' and result.get('code') == 'already_accepted')
                if record['accepted']:
                    self._accepted[cache_key] = fingerprint
                    self._pending.pop(cache_key, None)
                elif result.get('retryable') is True:
                    self._pending[cache_key] = request_id
                else:
                    self._pending.pop(cache_key, None)
                return result
            finally:
                self._lock.release()
        except Exception:
            return self._blocked()
