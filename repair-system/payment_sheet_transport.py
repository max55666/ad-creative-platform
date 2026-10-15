"""Opt-in payment projection transport; importing performs no network or I/O.

The caller must supply its server-owned queue record, endpoint, secret, and an
explicit destination allowlist. This module discovers no settings or secrets
and does not start a worker. It never mutates a repair case or a payment order.
"""
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from cloud_support import GoogleContentRedirect


SCHEMA = 'petpivot-payment-v1'
FIELDS = ('caseId', 'name', 'status', 'repairFee', 'pickupFee', 'amountDue',
          'amountPaid', 'orderNumber', 'paidAt', 'checkedAt', 'quoteVersion', 'revision')
STATUSES = frozenset(('待核價', '待付款', '已付款', '需人工核對', '免付款', '退款需處理', '已退款'))
MAX_BODY = 32768
MAX_ACK = 8192
MAX_SAFE_INTEGER = 9007199254740991


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_SAFE_INTEGER


def _timestamp(value, allow_empty):
    if value == '' and allow_empty:
        return True
    if not isinstance(value, str) or len(value) > 40:
        return False
    match = re.fullmatch(r'(\d{4})-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
                         r'(?:\.\d{1,3})?(Z|[+-](\d{2}):(\d{2}))', value)
    if not match or not 2000 <= int(match[1]) <= 2200:
        return False
    if match[2] != 'Z' and (int(match[3]) > 14 or int(match[4]) > 59
                            or int(match[3]) == 14 and int(match[4]) != 0):
        return False
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False


def validate_payment(record):
    """Validate the same twelve fixed fields as the standalone GAS receiver."""
    if not isinstance(record, dict) or set(record) != set(FIELDS):
        raise ValueError('invalid_payment')
    if not isinstance(record['caseId'], str) or not re.fullmatch(r'R[0-9]{8}-[0-9]{4,8}', record['caseId']):
        raise ValueError('invalid_payment')
    name = record['name']
    if (not isinstance(name, str) or not 1 <= len(name) <= 120 or name.strip() != name
            or re.search(r'[\x00-\x1f\x7f]', name)):
        raise ValueError('invalid_payment')
    status = record['status']
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError('invalid_payment')
    for key in ('repairFee', 'pickupFee', 'amountDue', 'amountPaid'):
        if not _integer(record[key]):
            raise ValueError('invalid_payment')
    if (record['pickupFee'] not in (0, 350)
            or not _integer(record['repairFee'] + record['pickupFee'])
            or record['amountDue'] != record['repairFee'] + record['pickupFee']
            or record['amountPaid'] > record['amountDue']):
        raise ValueError('invalid_payment')
    if (not _integer(record['revision'], 1)
            or not _integer(record['quoteVersion'], 0 if status == '待核價' else 1)):
        raise ValueError('invalid_payment')
    order = record['orderNumber']
    if not isinstance(order, str) or order and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', order):
        raise ValueError('invalid_payment')
    if (not _timestamp(record['paidAt'], True)
            or not _timestamp(record['checkedAt'], status not in ('已付款', '退款需處理', '已退款'))):
        raise ValueError('invalid_payment')
    if status == '已付款':
        if record['amountDue'] <= 0 or record['amountPaid'] != record['amountDue'] or not order:
            raise ValueError('invalid_payment')
    elif status in ('退款需處理', '已退款'):
        if not order:
            raise ValueError('invalid_payment')
    elif record['amountPaid'] != 0 or record['paidAt'] != '':
        raise ValueError('invalid_payment')
    if status == '免付款' and record['amountDue'] != 0:
        raise ValueError('invalid_payment')
    return {key: record[key] for key in FIELDS}


def _failed(code):
    messages = {
        'invalid_settings': '付款狀態同步設定或固定欄位格式錯誤',
        'invalid_ack': '雲端付款狀態尚未確認寫入',
        'stale': '雲端已有較新付款版本，這筆舊版未寫入',
        'unauthorized': '雲端付款同步未授權',
        'busy': '雲端付款同步忙碌，請稍後重試',
        'conflict': '雲端付款欄位或版本衝突，請由管理員確認',
        'unavailable': '雲端付款狀態同步暫時無法連線',
    }
    return {'state': 'failed', 'code': code, 'error': messages[code]}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_ack_key')
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError('non_json_number')


def send_payment(endpoint, secret, sheet_id, record, *, allowed_sheet_id, opener=None):
    """POST only an explicitly supplied server record; return sanitized results.

    A stale acknowledgement is deliberately a failure: it must not certify the
    queued revision as written. The queue decides retry/conflict handling.
    """
    try:
        if not isinstance(endpoint, str):
            raise ValueError('endpoint')
        parsed = urllib.parse.urlsplit(endpoint)
        if (parsed.scheme != 'https' or parsed.netloc != 'script.google.com'
                or parsed.query or parsed.fragment
                or not re.fullmatch(r'/macros/s/[A-Za-z0-9_-]{20,300}/exec', parsed.path)):
            raise ValueError('endpoint')
        if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', secret):
            raise ValueError('secret')
        if (not isinstance(sheet_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', sheet_id)
                or not isinstance(allowed_sheet_id, str) or sheet_id != allowed_sheet_id):
            raise ValueError('destination')
        payment = validate_payment(record)
        payload = {'secret': secret, 'sheetId': sheet_id, 'schema': SCHEMA,
                   'operation': 'upsertPayment', 'payment': payment}
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(body) > MAX_BODY:
            raise ValueError('body')
    except (ValueError, TypeError, KeyError, OverflowError):
        return _failed('invalid_settings')
    request = urllib.request.Request(endpoint, data=body, method='POST', headers={
        'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'})
    try:
        transport = opener if opener is not None else urllib.request.build_opener(GoogleContentRedirect())
        with transport.open(request, timeout=25) as response:
            raw = response.read(MAX_ACK + 1)
            if response.status != 200 or len(raw) > MAX_ACK:
                return _failed('invalid_ack')
            result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if not isinstance(result, dict):
            return _failed('invalid_ack')
        if result.get('ok') is not True:
            code = result.get('error')
            if code == 'unauthorized':
                return _failed('unauthorized')
            if code == 'busy':
                return _failed('busy')
            if code in ('duplicate_case', 'revision_conflict', 'header_mismatch', 'metadata_invalid', 'payment_row_missing'):
                return _failed('conflict')
            return _failed('invalid_ack')
        if (set(result) != {'ok', 'sheetId', 'schema', 'caseId', 'revision', 'status', 'action'}
                or result.get('sheetId') != sheet_id or result.get('schema') != SCHEMA
                or result.get('caseId') != payment['caseId']
                or type(result.get('revision')) is not int or result['revision'] != payment['revision']
                or result.get('status') != payment['status']):
            return _failed('invalid_ack')
        if result.get('action') == 'stale':
            return _failed('stale')
        if result.get('action') not in ('inserted', 'updated', 'unchanged'):
            return _failed('invalid_ack')
        return {'state': 'synced', 'action': result['action'], 'ack': result}
    except urllib.error.HTTPError as error:
        return _failed('unauthorized' if error.code in (401, 403) else 'busy' if error.code == 429 else 'unavailable')
    except Exception:
        # Do not expose response bodies, request bodies, URLs, or exceptions.
        return _failed('unavailable')
