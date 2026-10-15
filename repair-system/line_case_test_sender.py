"""Route internal test notices through a server-verified case binding only."""
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


class CaseBoundTestSender:
    def __init__(self, *, token, recipient_resolver, opener=None, clock=time.monotonic):
        if not callable(recipient_resolver) or not callable(clock) or (opener is not None and not callable(opener)):
            raise ValueError('內測通知服務設定不正確')
        self.token, self.resolve, self.opener = token, recipient_resolver, opener
        self.lock, self.senders = threading.Lock(), {}
        self.clock, self.last_attempt = clock, None
        self.requests, self.quote_targets = {}, {}

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
        try:
            _uuid4(request_id)
            target = self.binding(quote)
            uid, label = target['userId'], target['displayName']
            key = hashlib.sha256(uid.encode('ascii')).hexdigest()
            if not self.lock.acquire(blocking=False):
                return self._blocked('send_busy', True)
            try:
                if key not in self.senders:
                    if len(self.senders) >= 100:
                        return self._blocked('session_limit')
                    self.senders[key] = _BoundSender(token=self.token, allowed_user_id=uid,
                        allow_actual_test=True, label=label, opener=self.opener, clock=self.clock)
                sender = self.senders[key]
                # Validate the same server-loaded quote that the actual sender
                # will serialize before reserving any retry/recipient binding.
                quote_id, payload = sender._payload(quote)
                immutable = {field: quote[field] for field in ('id', 'caseId', 'version', 'total', 'currency')}
                fingerprint = hashlib.sha256(_json({'quote': immutable, 'payload': payload})).hexdigest()
                prior = self.requests.get(request_id)
                if prior and prior[:3] != (quote_id, uid, fingerprint):
                    return self._blocked('request_conflict')
                if self.quote_targets.get(quote_id, uid) != uid:
                    return self._blocked('recipient_changed')
                if not prior and len(self.requests) >= MAX_REQUESTS:
                    return self._blocked('session_limit')
                now = self.clock()
                if (not (prior and prior[3] == 'accepted') and self.last_attempt is not None
                        and now - self.last_attempt < GLOBAL_COOLDOWN):
                    return self._blocked('send_cooldown', True)
                self.quote_targets[quote_id] = uid
                previous_attempt = sender._last_attempt
                result = sender.send(quote, request_id)
                self.requests[request_id] = (quote_id, uid, fingerprint,
                                            'accepted' if result.get('state') in ('accepted', 'duplicate') else result.get('state'))
                if sender._last_attempt != previous_attempt:
                    self.last_attempt = now
                return result
            finally:
                self.lock.release()
        except Exception:
            return self._blocked()
