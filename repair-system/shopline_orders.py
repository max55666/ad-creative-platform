"""Read scoped SHOPLINE repair orders without verifying or changing payments.

Only the fixed one-dollar repair product is eligible for returned contact data.
The caller supplies credentials; importing this module performs no I/O. Provider
payment statuses are reported as observations, never as proof of settlement.

Reference: https://open-api.docs.shoplineapp.com/docs/search-orders
Money: https://open-api.docs.shoplineapp.com/docs/money (TWD cents are dollars).
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

from shopline_readonly import (
    _RejectRedirects, _http_status, _read_json, _valid_token,
)


PRODUCT_ID = '6ad05b22cda4796778761cd2'
_SEARCH_URL = 'https://open.shopline.io/v1/orders/search'
_PER_PAGE = 20
_MAX_PAGES = 5
_TIMEOUT_SECONDS = 10
_MAX_AMOUNT = 100000
_OBJECT_ID = re.compile(r'[0-9a-fA-F]{24}\Z')
_ORDER_NUMBER = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_PAYMENT_STATUSES = frozenset({
    'temp', 'pending', 'failed', 'expired', 'completed', 'refunding',
    'refunded', 'partially_refunded',
})


def _result(status, orders=None, truncated=False):
    return {
        'status': status,
        'readOnly': True,
        'orders': orders if status == 'ok' and orders is not None else [],
        'truncated': bool(truncated) if status == 'ok' else False,
    }


def _filters(filters, now):
    if filters is None:
        filters = {}
    if type(filters) is not dict or set(filters) - {'orderNumber', 'days'}:
        raise ValueError('Invalid order search filters')
    days = filters.get('days', 7)
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('Invalid order search filters')
    order_number = filters.get('orderNumber')
    if ('orderNumber' in filters
            and (type(order_number) is not str
                 or _ORDER_NUMBER.fullmatch(order_number) is None)):
        raise ValueError('Invalid order search filters')
    if now is None:
        now = datetime.now(timezone.utc)
    if (not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() is None):
        raise ValueError('Invalid order search time')
    try:
        since = now.astimezone(timezone.utc) - timedelta(days=days)
    except (ValueError, OverflowError):
        raise ValueError('Invalid order search time') from None
    return order_number, since.strftime('%Y-%m-%d %H:%M:%S')


def _text(value, limit=200, multiline=False):
    if type(value) is not str or len(value) > limit:
        return ''
    if any((ord(char) < 32 and not (multiline and char in '\n\t'))
           or ord(char) == 127 for char in value):
        return ''
    return value.strip()


def _date(value):
    value = _text(value, 64)
    if not value:
        return ''
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value if parsed.tzinfo is not None and parsed.utcoffset() is not None else ''
    except (ValueError, OverflowError):
        return ''


def _integer(value, minimum=0, maximum=_MAX_AMOUNT):
    if type(value) is int:
        return value if minimum <= value <= maximum else None
    if (type(value) is float and math.isfinite(value)
            and value.is_integer() and minimum <= value <= maximum):
        return int(value)
    return None


def _money(value):
    # TWD has no minor-unit conversion: {cents: 500} means NT$500, not NT$5.
    # Missing, conflicting, or foreign values remain unknown instead of guessed.
    if type(value) is not dict or value.get('currency_iso') != 'TWD':
        return None
    amount = _integer(value.get('cents'))
    if amount is None:
        return None
    if 'dollars' in value and value['dollars'] is not None:
        if _integer(value['dollars']) != amount:
            return None
    return amount


def _finite_json(payload):
    pending = [payload]
    while pending:
        value = pending.pop()
        if type(value) is float and not math.isfinite(value):
            raise ValueError('Invalid numeric response')
        if type(value) is dict:
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)


def _items(payload, page):
    if (type(payload) is not dict or 'items' not in payload
            or set(payload) - {'items', 'pagination'}
            or type(payload['items']) is not list
            or len(payload['items']) > _PER_PAGE):
        raise ValueError('Invalid order response')
    if any(type(item) is not dict for item in payload['items']):
        raise ValueError('Invalid order response')
    pagination = payload.get('pagination', {})
    if type(pagination) is not dict:
        raise ValueError('Invalid pagination')
    allowed = {'current_page', 'per_page', 'total_count', 'total_pages'}
    if set(pagination) - allowed:
        raise ValueError('Invalid pagination')
    for key, value in pagination.items():
        if type(value) is not int or value < 0:
            raise ValueError('Invalid pagination')
        if key == 'current_page' and value != page:
            raise ValueError('Invalid pagination')
        if key == 'per_page' and value != _PER_PAGE:
            raise ValueError('Invalid pagination')
    total_pages = pagination.get('total_pages')
    if total_pages is not None:
        if (total_pages == 0 and payload['items']) or (0 < total_pages < page):
            raise ValueError('Invalid pagination')
    if ('total_count' in pagination
            and pagination['total_count'] < len(payload['items'])):
        raise ValueError('Invalid pagination')
    return payload['items']


def _mixed_repair_allocation(order, lines, total, payment_total):
    """Evidence for explicit staff allocation only; never makes a cart auto-valid.

    Initially support undiscounted product-only carts whose item amounts exactly
    explain the entire paid order. Ambiguous credits/fees/discounts fail closed.
    """
    if (not 2 <= len(lines) <= 100 or type(total) is not int or total <= 0
            or payment_total != total or _money(order.get('subtotal')) != total):
        return None
    if any(_money(order.get(key)) != 0 for key in
           ('order_discount', 'user_credit', 'total_tax_fee')):
        return None
    if order.get('custom_discount_items') != []:
        return None
    promotions = order.get('promotion_items')
    if (type(promotions) is not list or any(type(p) is not dict
            or _money(p.get('discounted_amount')) != 0 for p in promotions)):
        return None
    evidence, repair = [], None
    for line in lines:
        if type(line) is not dict or line.get('item_type') != 'Product':
            return None
        ident, qty = line.get('item_id'), line.get('quantity')
        price, gross, net = (_money(line.get(k)) for k in
                             ('item_price', 'total', 'discounted_total'))
        if (type(ident) is not str or not _OBJECT_ID.fullmatch(ident)
                or type(qty) is not int or not 1 <= qty <= _MAX_AMOUNT
                or price is None or price <= 0 or gross != qty * price or net != gross
                or any(line.get(k) is not None and _money(line[k]) != price
                       for k in ('order_discounted_price', 'discounted_price'))):
            return None
        item = {'productId': ident.lower(), 'quantity': qty, 'unitPrice': price,
                'gross': gross, 'net': net}
        evidence.append(item)
        if ident.lower() == PRODUCT_ID:
            if repair is not None or price != 1:
                return None
            repair = item
    if repair is None or sum(item['net'] for item in evidence) != total:
        return None
    other = total - repair['net']
    if other <= 0:
        return None
    canonical = {'lines': sorted(evidence, key=lambda item: json.dumps(item, sort_keys=True)),
                 'orderTotal': total, 'paymentTotal': payment_total}
    return {'schema': 'repair-allocation-v1', 'productId': PRODUCT_ID,
            'quantity': repair['quantity'], 'unitPrice': 1,
            'repairAmount': repair['net'], 'otherAmount': other,
            'orderTotal': total, 'paymentTotal': payment_total,
            'fingerprint': hashlib.sha256(json.dumps(canonical, sort_keys=True,
                separators=(',', ':')).encode('utf-8')).hexdigest()}


def _normalize(order, order_number, token):
    # Scope before touching customer fields, regardless of provider filtering.
    lines = order.get('subtotal_items')
    if type(lines) is not list:
        return None
    repair_lines = [line for line in lines
                    if type(line) is dict
                    and type(line.get('item_id')) is str
                    and line['item_id'].lower() == PRODUCT_ID]
    if not repair_lines:
        return None
    if order_number is not None and not any(
            type(order.get(key)) is str and order[key] == order_number
            for key in ('order_number', 'merchant_order_number')):
        return None
    identity = order.get('id')
    if type(identity) is not str or _OBJECT_ID.fullmatch(identity) is None:
        raise ValueError('Invalid order identity')

    reasons = []
    product_reasons = []
    number = order.get('order_number')
    if type(number) is not str or _ORDER_NUMBER.fullmatch(number) is None:
        number = order.get('merchant_order_number')
    if type(number) is not str or _ORDER_NUMBER.fullmatch(number) is None:
        number = ''
        reasons.append('invalid_order_number')
    currency = order.get('currency_iso')
    if type(currency) is not str or re.fullmatch('[A-Z]{3}', currency) is None:
        currency = ''
    total = _money(order.get('total')) if currency == 'TWD' else None
    if currency != 'TWD':
        product_reasons.append('non_twd' if currency else 'missing_currency')
    if total is None:
        product_reasons.append('invalid_total')
    if len(lines) != 1 or len(repair_lines) != 1:
        product_reasons.append('mixed_cart')
    line = repair_lines[0]
    if line.get('item_type') != 'Product':
        product_reasons.append('unsupported_item_type')
    if _money(line.get('item_price')) != 1:
        product_reasons.append('invalid_unit_price')
    quantity = line.get('quantity')
    if type(quantity) is not int or not 1 <= quantity <= _MAX_AMOUNT:
        quantity = None
        product_reasons.append('invalid_quantity')
    line_total = _money(line.get('total'))
    if line_total is None or quantity is None or line_total != quantity:
        product_reasons.append('invalid_item_total')
    if total is not None and quantity is not None and total != quantity:
        product_reasons.append('order_total_mismatch')

    payment = order.get('order_payment')
    if type(payment) is not dict:
        payment = {}
    if 'total' in payment and payment['total'] is not None:
        payment_total = _money(payment['total'])
        if payment_total is None:
            product_reasons.append('invalid_payment_total')
        elif total is None or payment_total != total:
            product_reasons.append('payment_total_mismatch')
    status = payment.get('status')
    if type(status) is not str or status not in _PAYMENT_STATUSES:
        status = 'unknown'
        reasons.append('unknown_payment_status')
    delivery = order.get('delivery_address')
    if type(delivery) is not dict:
        delivery = {}
    normalized = {
        'id': identity.lower(),
        'orderNumber': number,
        'customerName': _text(order.get('customer_name')),
        'customerPhone': _text(order.get('customer_phone'), 64),
        'recipientName': _text(delivery.get('recipient_name')),
        'recipientPhone': _text(delivery.get('recipient_phone'), 64),
        'address': {
            'countryCode': _text(delivery.get('country_code'), 8),
            'city': _text(delivery.get('city'), 100),
            'district': _text(delivery.get('district'), 100),
            'address1': _text(delivery.get('address_1'), 500),
            'address2': _text(delivery.get('address_2'), 500),
            'postcode': _text(delivery.get('postcode'), 32),
        },
        'orderRemarks': _text(order.get('order_remarks'), 2000, multiline=True),
        'currency': currency,
        'total': total,
        'productValid': not product_reasons,
        'reportedPaymentStatus': status,
        'reportedPaidAt': _date(payment.get('paid_at')),
        'createdAt': _date(order.get('created_at')),
        'paymentVerified': False,
        'verificationStatus': 'not_verified',
        'reviewReasons': product_reasons + reasons,
    }
    if set(product_reasons) == {'mixed_cart', 'order_total_mismatch'}:
        allocation = _mixed_repair_allocation(order, lines, total, _money(payment.get('total')))
        if allocation is not None:
            normalized['repairAllocation'] = allocation
    # Protect against a compromised provider reflecting the bearer credential
    # into an otherwise allowed text field. Raw payloads are never returned.
    if token in json.dumps(normalized, ensure_ascii=False):
        raise ValueError('Invalid reflected credential')
    return normalized


def fetch_repair_orders(token, filters=None, opener=None, now=None, *, max_pages=_MAX_PAGES):
    """GET at most 100 scoped orders; return no partial data after any failure.

    ``filters`` accepts ``days`` (1..30, default 7), or an exact ``orderNumber``
    (1..64 ASCII letters, digits, underscore, hyphen). Exact number
    searches deliberately have no date bound. Invalid filters raise a sanitized
    ValueError. Every returned order remains paymentVerified=False.

    An injected opener is trusted test infrastructure. Default urllib transport
    uses normal TLS verification and refuses redirects before forwarding headers.
    No database, environment, filesystem, or external write operation is used.
    """
    order_number, created_after = _filters(filters, now)
    if type(max_pages) is not int or not 1 <= max_pages <= 250:
        raise ValueError('Invalid bounded order pagination')
    if not _valid_token(token):
        return _result('unauthorized')
    try:
        if opener is None:
            opener = urllib.request.build_opener(_RejectRedirects())
        elif isinstance(opener, urllib.request.OpenerDirector):
            if not any(isinstance(handler, _RejectRedirects)
                       for handler in opener.handlers):
                opener.add_handler(_RejectRedirects())
        orders = []
        seen = {}
        for page in range(1, max_pages + 1):
            parameters = {'item_id': PRODUCT_ID, 'per_page': _PER_PAGE, 'page': page}
            if order_number is None:
                parameters['created_after'] = created_after
            else:
                parameters['order_number'] = order_number
            url = _SEARCH_URL + '?' + urllib.parse.urlencode(parameters)
            request = urllib.request.Request(
                url, method='GET', headers={
                    'Authorization': 'Bearer ' + token,
                    'Accept': 'application/json',
                })
            with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
                code = getattr(response, 'status', None)
                if type(code) is not int:
                    return _result('invalid_response')
                if code != 200:
                    return _result(_http_status(code))
                if response.geturl() != url:
                    return _result('invalid_response')
                try:
                    payload = _read_json(response)
                    _finite_json(payload)
                    items = _items(payload, page)
                    for raw in items:
                        normalized = _normalize(raw, order_number, token)
                        if normalized is None:
                            continue
                        identity = normalized['id']
                        if identity in seen:
                            if seen[identity] != normalized:
                                raise ValueError('Conflicting order response')
                            continue
                        seen[identity] = normalized
                        orders.append(normalized)
                except (ValueError, UnicodeError, RecursionError, TypeError):
                    return _result('invalid_response')
            if len(items) < _PER_PAGE:
                return _result('ok', orders)
            if page == max_pages:
                return _result('ok', orders, truncated=True)
        return _result('ok', orders)
    except urllib.error.HTTPError as error:
        status = _http_status(error.code)
        try:
            error.close()
        except Exception:
            pass
        return _result(status)
    except Exception:
        # Exceptions may contain credentials or provider data; expose neither.
        return _result('unavailable')
