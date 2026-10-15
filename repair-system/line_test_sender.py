"""Single-recipient LINE push adapter for the isolated payment workbench.

This module never discovers credentials or recipients. The host must explicitly
provide one verified test user, opt in to actual test sending, and pass a saved,
approved workbench quote. Do not expose ``send`` as a client-payload passthrough.
Only the fixed LINE push endpoint can be called; all test messages prominently
say not to pay. Request bookkeeping is process-local, so the host should also
keep its durable notification ledger before calling this adapter.

Official protocol references:
https://developers.line.biz/en/docs/messaging-api/retrying-api-request/
https://developers.line.biz/en/reference/messaging-api/#send-push-message
https://developers.line.biz/en/reference/messaging-api/#clipboard-action
"""
import hashlib
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid


PUSH_URL = 'https://api.line.me/v2/bot/message/push'
PRODUCT_URL = 'https://www.zoko.com.tw/products/petpivot-maintenance-1'
TEST_RECIPIENT_LABEL = 'Max🚀'
TEST_PREFIX = ('【內部測試，請勿付款】\n測試接收人：Max🚀\n'
               '以下為隔離測試報價，不是正式客戶通知。')
FLAGS = {'mode': 'allowlisted_test_only', 'simulation': False,
         'internalOnly': True, 'realPayment': False, 'releaseAllowed': False}
MAX_ATTEMPTS = 10
MAX_REQUESTS = 1000
RETRY_WINDOW = 23 * 60 * 60
GLOBAL_COOLDOWN = 3.0
QUOTE_COOLDOWN = 60.0


def _uuid4(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError('內部測試識別碼不正確')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ValueError('內部測試識別碼不正確') from None
    if str(parsed) != value or parsed.version != 4:
        raise ValueError('內部測試識別碼不正確')
    return value


def _units(value):
    return len(value.encode('utf-16-le')) // 2


def _safe_text(value, maximum, multiline=False):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('內部測試通知內容不正確')
    if any((ord(c) < 32 and not (multiline and c == '\n')) or
           ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError('內部測試通知內容不正確')
    if _units(value) > maximum:
        raise ValueError('內部測試通知內容超過限制')
    return value


def _token_valid(token):
    return (isinstance(token, str) and 1 <= len(token) <= 4096 and
            token.isascii() and all(32 < ord(c) < 127 for c in token))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token to a redirect, even to the same host.
        return None


def _default_opener(request, timeout):
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect())
    return opener.open(request, timeout=timeout)


def _header(headers, name):
    if headers is None:
        return ''
    try:
        for key, value in headers.items():
            if str(key).lower() == name.lower():
                return value if isinstance(value, str) else ''
    except (AttributeError, TypeError):
        pass
    return ''


class LineTestSender:
    """Opt-in, allowlisted test sender with no recipient/message API parameters.

    ``opener`` is an injectable ``(urllib.request.Request, timeout=10)`` callable.
    It must not follow redirects. ``send`` receives a server-loaded quote, not
    the browser's request dictionary. Quote contract: safety flags, approved
    ``status='active'``, ``id`` (WQ-UUID4), ``caseId`` (WB-UUID4),
    ``caseNumber``, ``name``, server-built
    ``message``, and ``clipboardText`` matching the case and name.
    """

    def __init__(self, *, token_getter=None, token=None, allowed_user_id='',
                 recipient_label=TEST_RECIPIENT_LABEL, allow_actual_test=False,
                 opener=None, clock=time.monotonic):
        if token_getter is not None and (not callable(token_getter) or token is not None):
            raise ValueError('測試通知憑證設定不正確')
        if (not isinstance(allowed_user_id, str) or
                (allowed_user_id and not re.fullmatch(r'U[0-9a-fA-F]{32}', allowed_user_id))):
            raise ValueError('僅可設定單一已核對的測試 LINE 使用者')
        if recipient_label != TEST_RECIPIENT_LABEL:
            raise ValueError('此介面僅提供 Max 測試通知')
        if type(allow_actual_test) is not bool:
            raise ValueError('測試通知啟用設定不正確')
        if opener is not None and not callable(opener):
            raise ValueError('測試通知傳送設定不正確')
        self._token_getter = token_getter if token_getter is not None else lambda: token
        self._allowed_user_id = allowed_user_id
        self._allowed = allow_actual_test
        self._opener = opener or _default_opener
        self._clock = clock
        self._lock = threading.Lock()
        self._records = {}
        self._quote_accepted = {}
        self._quote_pending = {}
        self._last_attempt = None

    def _token(self):
        try:
            token = self._token_getter()
        except Exception:
            return None
        return token if _token_valid(token) else None

    def status(self):
        configured = bool(self._allowed_user_id and self._token())
        enabled = self._allowed and configured
        message = ('僅向 Max🚀 發送標示「內部測試，請勿付款」的通知。'
                   if enabled else '尚未啟用指定收件人的實際 LINE 內測通知。')
        return {**FLAGS, 'configured': configured, 'enabled': enabled,
                'canSend': enabled, 'recipientLabel': TEST_RECIPIENT_LABEL,
                'message': message, 'idempotencyStorage': 'process_memory',
                'globalCooldownSeconds': GLOBAL_COOLDOWN,
                'quoteCooldownSeconds': QUOTE_COOLDOWN}

    def _result(self, state, code, message, request_id='', quote_id='',
                retryable=False, **extra):
        return {**FLAGS, 'state': state, 'code': code, 'message': message,
                'requestId': request_id, 'quoteId': quote_id,
                'recipientLabel': TEST_RECIPIENT_LABEL,
                'retryable': retryable, **extra}

    def _payload(self, quote):
        if not isinstance(quote, dict):
            raise ValueError('僅可傳送已核定的內部報價')
        for key, required in (('internalOnly', True), ('simulation', True),
                              ('realPayment', False), ('releaseAllowed', False)):
            if quote.get(key) is not required:
                raise ValueError('僅可傳送隔離測試報價')
        if quote.get('status') != 'active' or quote.get('paymentStatus') != 'awaiting_payment':
            raise ValueError('請先核定內部報價')
        quote_id = quote.get('id', '')
        if not isinstance(quote_id, str) or not quote_id.startswith('WQ-'):
            raise ValueError('僅可傳送內部工作台報價')
        _uuid4(quote_id[3:])
        case_id = quote.get('caseId', '')
        if not isinstance(case_id, str) or not case_id.startswith('WB-'):
            raise ValueError('僅可使用隔離工作台案件')
        _uuid4(case_id[3:])
        if (type(quote.get('total')) is not int or not 1 <= quote['total'] <= 100350 or
                quote.get('currency') != 'TWD' or type(quote.get('version')) is not int or
                not 1 <= quote['version'] <= 1000000):
            raise ValueError('僅可測試正額新臺幣付款通知')
        case = _safe_text(quote.get('caseNumber'), 80)
        if not re.fullmatch(r'(?:TEST-)?R[0-9]{8}-[0-9]{4,8}', case):
            raise ValueError('內部報價案件編號不正確')
        name = _safe_text(quote.get('name'), 80)
        clipboard = '送修編號：' + case + '\n申請人姓名：' + name
        if quote.get('clipboardText') != clipboard:
            raise ValueError('內部報價下單備註不一致')
        _safe_text(clipboard, 1000, True)
        message = _safe_text(quote.get('message'), 3500, True)
        # A server-built quote may contain the fixed shop URL. Reject every
        # other explicit network URL rather than sending an unintended link.
        urls = re.findall(r'(?i)(?:https?|ftp)://[^\s<>「」]+', message)
        if any(url.rstrip('。,.') != PRODUCT_URL for url in urls):
            raise ValueError('內部報價含有未核准的連結')
        text = TEST_PREFIX + '\n\n' + message
        _safe_text(text, 4500, True)
        bubble = {
            'type': 'bubble',
            'body': {'type': 'box', 'layout': 'vertical', 'spacing': 'md',
                     'contents': [
                         {'type': 'text', 'text': TEST_PREFIX, 'wrap': True,
                          'weight': 'bold', 'color': '#A24120', 'size': 'sm'},
                         {'type': 'separator'},
                         {'type': 'text', 'text': message, 'wrap': True,
                          'size': 'sm', 'color': '#193D35'}]},
            'footer': {'type': 'box', 'layout': 'vertical', 'spacing': 'sm',
                       'contents': [
                           {'type': 'button', 'style': 'secondary',
                            'action': {'type': 'clipboard', 'label': '複製下單備註',
                                       'clipboardText': clipboard}},
                           {'type': 'button', 'style': 'secondary',
                            'action': {'type': 'uri', 'label': '查看測試付款頁',
                                       'uri': PRODUCT_URL}}]}}
        if len(_json(bubble)) > 29000:
            raise ValueError('內部測試卡片超過限制')
        payload = {'to': self._allowed_user_id, 'messages': [
            {'type': 'flex', 'altText': '【內部測試，請勿付款】維修付款通知',
             'contents': bubble}]}
        return quote_id, payload

    def send(self, approved_quote, request_id):
        """Send once to the configured test user; never accepts a target or URL.

        Unknown outcomes may be retried only with the original UUID and exact
        immutable quote. Expired retry keys remain blocked rather than risking
        duplicate delivery. No retries happen automatically.
        """
        try:
            _uuid4(request_id)
            quote_id, payload = self._payload(approved_quote)
        except (ValueError, TypeError, OverflowError, UnicodeError):
            return self._result('failed', 'invalid_quote',
                                '內部測試報價或識別碼不正確，未傳送。')
        if not self._allowed or not self._allowed_user_id:
            return self._result('failed', 'test_disabled', '尚未啟用實際 LINE 內測通知。',
                                request_id, quote_id)
        token = self._token()
        if not token:
            return self._result('failed', 'not_configured', '測試通知尚未完成設定。',
                                request_id, quote_id)
        immutable = {key: approved_quote[key] for key in
                     ('id', 'caseId', 'version', 'total', 'currency')}
        fingerprint = hashlib.sha256(_json({'quote': immutable, 'payload': payload})).hexdigest()
        if not self._lock.acquire(blocking=False):
            return self._result('needs_review', 'send_busy', '另一則測試通知正在傳送，請稍後再試。',
                                request_id, quote_id, True)
        try:
            now = self._clock()
            prior = self._records.get(request_id)
            if prior:
                if prior['fingerprint'] != fingerprint or prior['quoteId'] != quote_id:
                    return self._result('failed', 'request_conflict',
                                        '此測試傳送識別碼已用於不同報價，未傳送。', request_id, quote_id)
                if prior['result']['state'] == 'accepted':
                    return {**prior['result'], 'state': 'duplicate',
                            'code': 'already_accepted',
                            'message': 'LINE API 已接受此測試通知，未重複傳送。'}
                if not prior['result'].get('retryable'):
                    return dict(prior['result'])
                if now - prior['created'] >= RETRY_WINDOW or prior['attempts'] >= MAX_ATTEMPTS:
                    return self._result('needs_review', 'retry_expired',
                                        '測試傳送結果仍待確認，已停止重試以避免重複訊息。',
                                        request_id, quote_id)
                retry_delay = min(60.0, GLOBAL_COOLDOWN * 2 ** (prior['attempts'] - 1))
                if now - prior['lastAttempt'] < retry_delay:
                    return self._result('needs_review', 'retry_cooldown',
                                        '請稍後使用同一筆傳送識別碼重試。', request_id, quote_id, True)
            else:
                pending = self._quote_pending.get(quote_id)
                if pending:
                    return self._result('needs_review', 'use_original_request',
                                        '這筆報價有一則待確認通知，請使用原傳送識別碼重試。',
                                        pending, quote_id, True)
                accepted_at = self._quote_accepted.get(quote_id)
                if accepted_at is not None and now - accepted_at < QUOTE_COOLDOWN:
                    return self._result('duplicate', 'quote_cooldown',
                                        '這筆報價剛送出測試通知，未重複傳送。', request_id, quote_id)
                if len(self._records) >= MAX_REQUESTS:
                    return self._result('failed', 'session_limit',
                                        '本次內部測試傳送數已達上限，請由管理員檢查。', request_id, quote_id)
            if self._last_attempt is not None and now - self._last_attempt < GLOBAL_COOLDOWN:
                return self._result('needs_review', 'send_cooldown',
                                    '測試通知傳送過於頻繁，請稍後再試。', request_id, quote_id, True)
            record = prior or {'fingerprint': fingerprint, 'quoteId': quote_id,
                               'created': now, 'attempts': 0}
            record['lastAttempt'] = now
            record['attempts'] += 1
            self._records[request_id] = record
            self._last_attempt = now
            request = urllib.request.Request(
                PUSH_URL, data=_json(payload), method='POST',
                headers={'Authorization': 'Bearer ' + token,
                         'Content-Type': 'application/json',
                         'X-Line-Retry-Key': request_id})
            result = self._perform(request, request_id, quote_id)
            record['result'] = result
            if result['state'] == 'accepted':
                self._quote_accepted[quote_id] = now
                self._quote_pending.pop(quote_id, None)
            elif result['state'] == 'needs_review':
                self._quote_pending[quote_id] = request_id
            else:
                self._quote_pending.pop(quote_id, None)
            return dict(result)
        finally:
            self._lock.release()

    def _perform(self, request, request_id, quote_id):
        response = None
        try:
            try:
                response = self._opener(request, timeout=10)
                status = getattr(response, 'status', None)
                if status is None:
                    status = response.getcode()
                final_url = response.geturl() if hasattr(response, 'geturl') else PUSH_URL
                headers = getattr(response, 'headers', {})
            except urllib.error.HTTPError as error:
                response = error
                status = error.code
                final_url = error.geturl()
                headers = error.headers
            if final_url != PUSH_URL or 300 <= status < 400:
                return self._result('failed', 'redirect_blocked',
                                    'LINE 測試通知的重新導向已阻擋，未繼續傳送。', request_id, quote_id)
            if status in (200, 202):
                return self._result('accepted', 'api_accepted',
                                    'LINE API 已接受測試通知；尚未確認收件人收到或已讀。',
                                    request_id, quote_id)
            if status == 409:
                accepted_id = _header(headers, 'x-line-accepted-request-id')
                try:
                    parsed = uuid.UUID(accepted_id)
                    valid = str(parsed) == accepted_id
                except (ValueError, AttributeError):
                    valid = False
                if valid:
                    return self._result('accepted', 'api_previously_accepted',
                                        'LINE API 已接受先前的測試請求，未重複傳送。', request_id, quote_id)
                return self._result('needs_review', 'conflict_unconfirmed',
                                    'LINE 回應有衝突，請使用原識別碼檢查測試結果。',
                                    request_id, quote_id, True)
            if status >= 500:
                return self._result('needs_review', 'provider_unavailable',
                                    'LINE 測試通知結果待確認；僅可使用原識別碼重試。',
                                    request_id, quote_id, True)
            code = {400: 'invalid_request', 401: 'unauthorized',
                    403: 'forbidden', 429: 'rate_limited'}.get(status, 'provider_rejected')
            return self._result('failed', code, 'LINE 未接受本次測試通知，請由管理員檢查設定。',
                                request_id, quote_id)
        except (TimeoutError, socket.timeout, urllib.error.URLError, OSError):
            return self._result('needs_review', 'network_unknown',
                                '網路未回覆測試通知結果；僅可使用原識別碼重試。',
                                request_id, quote_id, True)
        except Exception:
            # Provider bodies, exception strings, and headers may contain
            # credentials or private content. Never pass them to the UI/log.
            return self._result('needs_review', 'unexpected_response',
                                '測試通知結果無法確認，請由管理員檢查。', request_id, quote_id, True)
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
