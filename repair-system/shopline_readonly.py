"""Check SHOPLINE access without requesting an existing order or changing data.

This is a connection check, not a payment verification or a release decision.
The optional opener is a trusted transport dependency for isolated tests. No
configuration is read and no network activity occurs while importing this file.
"""

import json
import urllib.error
import urllib.request
import uuid


_SEARCH_URL = 'https://open.shopline.io/v1/orders/search'
_TIMEOUT_SECONDS = 10
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_TOKEN_LENGTH = 4096


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    # Run before the standard redirect handler, including in an injected opener.
    handler_order = 0

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            request.full_url, code, 'Redirects are disabled', headers, fp)


def _result(status):
    return {
        'connected': status == 'connected',
        'provider': 'shopline',
        'readOnly': True,
        'requestedOrders': 0,
        'status': status,
    }


def _http_status(code):
    if code == 401:
        return 'unauthorized'
    if code == 403:
        return 'forbidden'
    if code == 429:
        return 'rate_limited'
    if isinstance(code, int) and 300 <= code < 400:
        return 'invalid_response'
    return 'unavailable'


def _valid_token(token):
    # Reject spaces, control characters, and non-ASCII header values as well.
    return (type(token) is str and 0 < len(token) <= _MAX_TOKEN_LENGTH
            and all(33 <= ord(character) <= 126 for character in token))


def _reject_constant(_value):
    raise ValueError('Non-standard JSON value')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _read_json(response):
    parts = []
    received = 0
    while True:
        remaining = _MAX_RESPONSE_BYTES + 1 - received
        chunk = response.read(min(65536, remaining))
        if not isinstance(chunk, bytes) or len(chunk) > min(65536, remaining):
            raise ValueError('Invalid response stream')
        if not chunk:
            break
        received += len(chunk)
        if received > _MAX_RESPONSE_BYTES:
            raise ValueError('Response is too large')
        parts.append(chunk)
    return json.loads(b''.join(parts).decode('utf-8'),
                      parse_constant=_reject_constant,
                      object_pairs_hook=_unique_object)


def _valid_empty_search(payload):
    # Search Orders documents an object with items, not a bare JSON list. An
    # unexpected real order also fails closed: the random filter was not honored.
    if (type(payload) is not dict or 'items' not in payload
            or set(payload) - {'items', 'pagination'}
            or type(payload['items']) is not list or payload['items']):
        return False
    if 'pagination' not in payload:
        return True
    pagination = payload['pagination']
    expected = {
        'current_page': {1}, 'per_page': {1},
        'total_count': {0}, 'total_pages': {0, 1},
    }
    if type(pagination) is not dict or set(pagination) - set(expected):
        return False
    return all(type(value) is int and value in expected[key]
               for key, value in pagination.items())


def inspect_connection(token, opener=None):
    """Return safe metadata for one GET of a fresh, nonexistent order number.

    Never creates orders, registers webhooks, verifies payment, or returns any
    provider response body. Invalid credentials and transport failures are
    represented only by the fixed public status values.
    """
    if not _valid_token(token):
        return _result('unauthorized')

    try:
        order_number = 'PAYMENT-LAB-AUTH-' + uuid.uuid4().hex
        url = _SEARCH_URL + '?per_page=1&order_number=' + order_number
        request = urllib.request.Request(
            url, method='GET',
            headers={'Authorization': 'Bearer ' + token,
                     'Accept': 'application/json'})
        if opener is None:
            opener = urllib.request.build_opener(_RejectRedirects())
        elif isinstance(opener, urllib.request.OpenerDirector):
            if not any(isinstance(handler, _RejectRedirects)
                       for handler in opener.handlers):
                opener.add_handler(_RejectRedirects())

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
                valid = _valid_empty_search(payload)
            except (ValueError, UnicodeError, RecursionError, TypeError):
                return _result('invalid_response')
            return _result('connected' if valid else 'invalid_response')
    except urllib.error.HTTPError as error:
        status = _http_status(error.code)
        try:
            error.close()
        except Exception:
            pass
        return _result(status)
    except Exception:
        # Do not expose exception strings: transports can include credentials,
        # request headers, or provider bodies in their errors.
        return _result('unavailable')
