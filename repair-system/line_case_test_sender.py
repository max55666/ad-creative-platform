"""Route internal test notices through a server-verified case binding only."""
from datetime import datetime
import hashlib
import re
import threading
import time

from line_test_sender import (LineTestSender, GLOBAL_COOLDOWN, MAX_REQUESTS,
                              _json, _safe_text, _token_valid, _uuid4)


class _BoundSender(LineTestSender):
    def __init__(self, *, label, **kwargs):
        super().__init__(**kwargs)
        self.label = _safe_text(label, 80)

    def _payload(self, quote):
        quote_id, payload = super()._payload(quote)
        prefix = ('【內部測試，請勿付款】\n測試接收人：' + self.label +
                  '\n以下為隔離測試報價，不是正式客戶通知。')
        bubble = payload['messages'][0]['contents']
        bubble['body']['contents'][0]['text'] = prefix
        return quote_id, payload

    def _result(self, *args, **kwargs):
        result = super()._result(*args, **kwargs)
        result['recipientLabel'] = self.label
        return result


class _ReceiptBoundSender(_BoundSender):
    """Typed, link-free receipt payload using the proven push retry engine."""
    def _payload(self, receipt):
        required = {'id', 'caseId', 'caseNumber', 'name', 'version', 'total',
            'currency', 'orderNumber', 'paidAt', 'source', 'internalOnly',
            'realPayment', 'releaseAllowed', 'simulation'}
        if type(receipt) is not dict or set(receipt) != required:
            raise ValueError('付款確認只接受伺服器已核對的固定欄位')
        for key, expected in (('internalOnly', True), ('simulation', True),
                              ('realPayment', False), ('releaseAllowed', False)):
            if receipt.get(key) is not expected:
                raise ValueError('付款確認僅限隔離內測')
        quote_id, case_id = receipt.get('id'), receipt.get('caseId')
        if not isinstance(quote_id, str) or not quote_id.startswith('WQ-'):
            raise ValueError('付款確認報價識別碼不正確')
        if not isinstance(case_id, str) or not case_id.startswith('WB-'):
            raise ValueError('付款確認案件識別碼不正確')
        _uuid4(quote_id[3:])
        _uuid4(case_id[3:])
        if (type(receipt.get('total')) is not int or not 1 <= receipt['total'] <= 100350
                or type(receipt.get('version')) is not int or not 1 <= receipt['version'] <= 1000000
                or receipt.get('currency') != 'TWD'
                or receipt.get('source') not in ('shopline_api_completed', 'shopline_api_manual_completed')):
            raise ValueError('付款確認金額或核對來源不正確')
        case_number = _safe_text(receipt.get('caseNumber'), 80)
        if not re.fullmatch(r'R[0-9]{8}-[0-9]{4,8}', case_number):
            raise ValueError('付款確認案件編號不正確')
        name = _safe_text(receipt.get('name'), 80)
        if re.search(r'(?i)(?:https?|ftp)://|www\.', name):
            raise ValueError('付款確認不得包含連結')
        order = _safe_text(receipt.get('orderNumber'), 64)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', order):
            raise ValueError('付款訂單編號不正確')
        paid_at = _safe_text(receipt.get('paidAt'), 64)
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
                           r'(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?', paid_at):
            raise ValueError('付款時間不正確')
        datetime.fromisoformat(paid_at.replace('Z', '+00:00'))
        text = ('【內部測試｜付款確認】\n\n維修編號：' + case_number
            + '\n付款訂單編號：' + order
            + '\n付款金額：NT$' + format(receipt['total'], ',')
            + '\n\n付款已核對完成，後續由客服安排送修。')
        _safe_text(text, 1000, True)
        return quote_id, {'to': self._allowed_user_id,
            'messages': [{'type': 'text', 'text': text}]}

    def _result(self, state, code, *args, **kwargs):
        # The router pins one immutable receipt per quote and recipient, so a
        # same-receipt cooldown is evidence of a previous accepted receipt.
        if state == 'duplicate' and code == 'quote_cooldown':
            code = 'already_accepted'
        result = super()._result(state, code, *args, **kwargs)
        result['notificationKind'] = 'payment_receipt'
        return result


class CaseBoundTestSender:
    def __init__(self, *, token, recipient_resolver, opener=None, clock=time.monotonic):
        if not callable(recipient_resolver) or not callable(clock) or (opener is not None and not callable(opener)):
            raise ValueError('內測通知服務設定不正確')
        self.token, self.resolve, self.opener = token, recipient_resolver, opener
        self.lock, self.senders = threading.Lock(), {}
        self.receipt_senders = {}
        self.clock, self.last_attempt = clock, None
        self.requests, self.quote_targets = {}, {}
        self.quote_identities, self.quote_fingerprints = {}, {}

    def status(self):
        configured = _token_valid(self.token)
        return {'configured': configured, 'enabled': configured,
                'canSend': configured, 'recipientMode': 'case_bound_test',
                'recipientLabel': '案件已驗證的內測 LINE 帳號',
                'message': '只通知已接受內測邀請並完成 LINE 驗證的案件申請人。',
                'internalOnly': True, 'realPayment': False, 'releaseAllowed': False}

    def binding(self, quote):
        if not isinstance(quote, dict):
            raise ValueError('僅可傳送伺服器載入的內測報價')
        target = self.resolve(quote.get('caseId', ''))
        if (not isinstance(target, dict) or target.get('verified') is not True
                or not isinstance(target.get('userId'), str)
                or not re.fullmatch(r'U[0-9a-f]{32}', target['userId'])):
            raise ValueError('案件尚未完成內測 LINE 身分綁定')
        _safe_text(target.get('displayName'), 80)
        return target

    @staticmethod
    def _blocked(code='unverified_test_recipient', retryable=False):
        return {'state': 'needs_review' if retryable else 'failed', 'code': code,
                'message': '內測通知尚未傳送，請確認案件身分、原傳送識別碼或稍後重試。',
                'retryable': retryable, 'internalOnly': True,
                'realPayment': False, 'releaseAllowed': False}

    def send(self, quote, request_id):
        return self._send('notice', quote, request_id)

    def send_receipt(self, receipt, request_id):
        return self._send('receipt', receipt, request_id)

    def _send(self, kind, quote, request_id):
        try:
            _uuid4(request_id)
            target = self.binding(quote)
            uid, label = target['userId'], target['displayName']
            key = hashlib.sha256(uid.encode('ascii')).hexdigest()
            if not self.lock.acquire(blocking=False):
                return self._blocked('send_busy', True)
            try:
                senders = self.senders if kind == 'notice' else self.receipt_senders
                sender_class = _BoundSender if kind == 'notice' else _ReceiptBoundSender
                if key not in senders:
                    if len(senders) >= 100:
                        return self._blocked('session_limit')
                    senders[key] = sender_class(token=self.token, allowed_user_id=uid,
                        allow_actual_test=True, label=label, opener=self.opener, clock=self.clock)
                sender = senders[key]
                # Validate the same server-loaded quote that the actual sender
                # will serialize before reserving any retry/recipient binding.
                quote_id, payload = sender._payload(quote)
                immutable = {field: quote[field] for field in ('id', 'caseId', 'version', 'total', 'currency')}
                fingerprint_input = {'quote': immutable, 'payload': payload}
                if kind == 'receipt':
                    fingerprint_input['receipt'] = quote
                fingerprint = hashlib.sha256(_json(fingerprint_input)).hexdigest()
                identity = hashlib.sha256(_json(immutable)).hexdigest()
                prior = self.requests.get(request_id)
                if prior and prior[:4] != (kind, quote_id, uid, fingerprint):
                    return self._blocked('request_conflict')
                if self.quote_targets.get(quote_id, uid) != uid:
                    return self._blocked('recipient_changed')
                if self.quote_identities.get(quote_id, identity) != identity:
                    return self._blocked('quote_changed')
                if self.quote_fingerprints.get((kind, quote_id), fingerprint) != fingerprint:
                    return self._blocked('quote_changed')
                if not prior and len(self.requests) >= MAX_REQUESTS:
                    return self._blocked('session_limit')
                now = self.clock()
                if (not (prior and prior[4] == 'accepted') and self.last_attempt is not None
                        and now - self.last_attempt < GLOBAL_COOLDOWN):
                    return self._blocked('send_cooldown', True)
                self.quote_targets[quote_id] = uid
                self.quote_identities[quote_id] = identity
                self.quote_fingerprints[(kind, quote_id)] = fingerprint
                previous_attempt = sender._last_attempt
                result = sender.send(quote, request_id)
                self.requests[request_id] = (kind, quote_id, uid, fingerprint,
                                            'accepted' if result.get('state') in ('accepted', 'duplicate') else result.get('state'))
                if sender._last_attempt != previous_attempt:
                    self.last_attempt = now
                return result
            finally:
                self.lock.release()
        except Exception:
            return self._blocked()
