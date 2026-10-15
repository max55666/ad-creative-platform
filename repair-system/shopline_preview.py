"""Admin-only, volatile, read-only SHOPLINE order preview.

Credentials and customer previews live in memory only. This service has no
payment, binding, case-writing, notification or dispatch dependency.
"""
import copy
import re
import threading
import time

from order_matching import rank_candidates

FLAGS = {'enabled': True, 'simulation': False, 'readOnly': True,
         'internalOnly': True, 'realPayment': False, 'releaseAllowed': False}
STATUSES = {'ok', 'unauthorized', 'forbidden', 'rate_limited',
            'unavailable', 'invalid_response'}
ORDER_FIELDS = {'id', 'orderNumber', 'customerName', 'customerPhone',
                'recipientName', 'recipientPhone', 'address', 'orderRemarks',
                'currency', 'total', 'productValid', 'reportedPaymentStatus',
                'reportedPaidAt', 'createdAt', 'paymentVerified',
                'verificationStatus', 'reviewReasons'}


class PreviewBusy(ValueError):
    pass


class ShoplinePreview:
    def __init__(self, token_getter, case_reader, fetcher, clock=time.monotonic):
        self._token_getter, self._case_reader = token_getter, case_reader
        self._fetcher, self._clock = fetcher, clock
        self._lock = threading.RLock()
        self._fetch_lock = threading.Lock()
        self._token = None
        self._orders, self._last_fetched = [], ''
        self._status, self._truncated, self._next = 'not_checked', False, 0

    def _credential(self):
        return self._token if self._token is not None else self._token_getter()

    def configure(self, payload):
        if type(payload) is not dict or set(payload) != {'token'}:
            raise ValueError('Invalid configuration')
        token = payload['token']
        if (type(token) is not str or not 1 <= len(token) <= 4096
                or any(not 33 <= ord(char) <= 126 for char in token)):
            raise ValueError('Invalid credential')
        if not self._fetch_lock.acquire(blocking=False):
            raise PreviewBusy('Preview busy')
        try:
            with self._lock:
                self._token = token
                self._orders, self._last_fetched = [], ''
                self._status, self._truncated = 'not_checked', False
        finally:
            self._fetch_lock.release()
        return self.state()

    def state(self):
        with self._lock:
            orders = copy.deepcopy(self._orders)
            configured = bool(self._credential())
            status = self._status if configured else 'not_configured'
            stamp, truncated = self._last_fetched, self._truncated
        # A fresh snapshot lets candidates reflect current case data without
        # changing either the source cases or imported order metadata.
        cases = self._case_reader()
        for order in orders:
            order['paymentVerified'] = False
            order['verificationStatus'] = 'not_verified'
            matcher_order = dict(order)
            remarks = order.get('orderRemarks') or ''
            references = set(re.findall(r'(?:送修編號|維修案件編號|案件編號)[：:]\s*(R\d{8}-\d{4,})', remarks))
            matcher_order['remarkCaseId'] = (next(iter(references)) if len(references) == 1
                                            else 'CONFLICT' if references else '')
            order['matching'] = rank_candidates(matcher_order, cases)
            order['fetchedAt'] = stamp
        return {**FLAGS, 'configured': configured, 'orders': orders,
                'status': status, 'lastFetchedAt': stamp, 'truncated': truncated,
                'source': 'shopline_read_only', 'credentialStorage': 'process_memory',
                'automaticBindingEnabled': False,
                'caseCandidateCount': len(cases),
                'caseAmountsAvailable': any(type(case.get('total')) is int for case in cases),
                'matchingScope': 'identity_suggestions_only'}

    def fetch(self, filters):
        if type(filters) is not dict or set(filters) not in ({'days'}, {'orderNumber'}):
            raise ValueError('Invalid search filters')
        if 'days' in filters and (type(filters['days']) is not int or not 1 <= filters['days'] <= 30):
            raise ValueError('Invalid search window')
        if 'orderNumber' in filters and (type(filters['orderNumber']) is not str
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', filters['orderNumber'])):
            raise ValueError('Invalid order number')
        if not self._fetch_lock.acquire(blocking=False):
            raise PreviewBusy('Preview busy')
        try:
            with self._lock:
                token = self._credential()
                if not token:
                    return self.state()
                now = self._clock()
                if now < self._next:
                    raise PreviewBusy('Please wait before retrying')
                self._next = now + 30
            try:
                result = self._fetcher(token, filters)
                if type(result) is not dict or result.get('status') not in STATUSES:
                    raise ValueError('Unexpected provider result')
                status = result['status']
                orders = result.get('orders', [])
                if status == 'ok':
                    if type(orders) is not list or len(orders) > 100:
                        raise ValueError('Unexpected provider orders')
                    cleaned = []
                    for order in orders:
                        if type(order) is not dict or not re.fullmatch(r'[0-9a-f]{24}', order.get('id', '')):
                            raise ValueError('Unexpected provider order')
                        item = {key: copy.deepcopy(value) for key, value in order.items() if key in ORDER_FIELDS}
                        item['paymentVerified'] = False
                        item['verificationStatus'] = 'not_verified'
                        cleaned.append(item)
                    ids = [order['id'] for order in cleaned]
                    if len(ids) != len(set(ids)):
                        raise ValueError('Duplicate provider orders')
                    with self._lock:
                        self._orders = cleaned
                        self._last_fetched = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time.time() + 8 * 3600))
                        self._truncated = result.get('truncated') is True
                with self._lock:
                    self._status = status
            except Exception:
                with self._lock:
                    self._status = 'invalid_response'
            return self.state()
        finally:
            self._fetch_lock.release()
