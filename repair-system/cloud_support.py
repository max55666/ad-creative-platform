"""Google Sheets delivery helpers. Importing this module performs no network I/O.

The Apps Script secret is server-only. Never return it, a request body, or an
upstream response body to the browser or application logs.
"""
import hashlib
import datetime
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request


HEADERS = [
    '案件編號', '建立時間', 'LINE User ID', 'LINE顯示名稱', '電子郵件地址',
    '客戶姓名', '聯絡電話', '收件/回寄地址', '訂單編號', '購買憑證與附件',
    '機器故障現象描述', '其他補充說明', '寄送內容物確認', '機器清潔狀態確認',
    '包裝與運送責任聲明', '收送件資格與時間說明', '配送日期', '配送狀態',
    '維修狀態', '付款連結', 'LINE通知狀態', '最後更新時間', '商品型號',
    '商品序號', '購買通路', '訂單提供狀態', '維修處理', '寄送方式', '取件地址',
    '回收運費', '寄送注意事項', 'LINE摘要收件時間',
]
CASE_FIELDS = {
    'id', 'createdAt', 'lineUserId', 'lineDisplayName', 'email', 'name', 'phone',
    'returnAddress', 'order', 'problem', 'extra', 'contentConfirmation',
    'cleaningConfirmation', 'packingConfirmation', 'shippingConfirmation',
    'status', 'lineNotification', 'updatedAt', 'model', 'serial', 'purchaseChannel',
    'orderChoice', 'repairPolicy', 'shipping', 'pickupAddress', 'pickupFeeTwd',
    'shippingNote', 'lineSummaryReceivedAt', 'revision',
}
MAX_BODY = 120000
PRIMARY_SHEET_ID = '1C5gGI4cL4lgw-GqSXRcQuicM2e5FvDHp-bnfqpMcnqI'
PICKUP_SHEET_ID = '11T4F5krGq2rzDRy9ICE6dQA1f7f2xX22OoLhHK117-Q'
PICKUP_SHEET_GID = 1272115939
ACKS = [
    '我已確認箱內只有主機本體與電源線。',
    '我已理解清潔規範。',
    '我已詳閱包裝運送說明。',
    '我已了解寄送方式與資訊。',
]


def validate_endpoint(value):
    """Accept only a deployed Google Apps Script web app, without query secrets."""
    if not isinstance(value, str):
        raise ValueError('Google 雲端同步網址格式錯誤')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname != 'script.google.com'
            or parsed.netloc != 'script.google.com' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/macros/s/[A-Za-z0-9_-]{20,300}/exec', parsed.path)):
        raise ValueError('請填寫 Google Apps Script 的 HTTPS 部署網址（結尾為 /exec）')
    return value


def validate_secret(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', value):
        raise ValueError('雲端同步金鑰必須為 32–128 位英數字、底線或連字號')
    return value


def format_sheet_phone(value):
    """Display Taiwanese mobile numbers without changing the source data."""
    if not isinstance(value, str):
        return value
    digits = re.sub(r'[\s-]', '', value)
    if re.fullmatch(r'09[0-9]{8}', digits):
        return digits[:4] + '-' + digits[4:]
    return value


def build_payload(case, revision=1, updated_at=None):
    """Build a strict cloud record from a server-owned case, never browser input.

    Staff-managed purchase attachments, dispatch date/status and payment link
    are intentionally omitted so Google Sheets edits survive future updates.
    """
    if not isinstance(case, dict):
        case = dict(case)
    data = case.get('data', {})
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError('案件資料格式錯誤')
    record = {
        'id': case.get('id', ''), 'createdAt': case.get('created', ''),
        'lineUserId': case.get('user_id', ''),
        'lineDisplayName': data.get('lineDisplayName', ''),
        'email': data.get('email', ''), 'name': data.get('name', ''),
        'phone': format_sheet_phone(data.get('phone', '')), 'returnAddress': data.get('returnAddress', ''),
        'order': data.get('order', ''), 'problem': data.get('problem', ''),
        'extra': data.get('extra', ''), 'status': case.get('status', ''),
        'lineNotification': case.get('notification', ''),
        'updatedAt': updated_at or case.get('updated') or case.get('created', ''),
        'model': data.get('model', ''), 'serial': data.get('serial', ''),
        'purchaseChannel': data.get('purchase', ''),
        'orderChoice': {'provided': '有訂單編號', 'missing': '無訂單編號／不記得了'}.get(data.get('orderChoice'), '待客服確認（舊案件）'),
        'repairPolicy': data.get('repairPolicy', '待客服確認（舊案件）'),
        'shipping': data.get('shipping', ''), 'pickupAddress': data.get('pickupAddress', ''),
        'pickupFeeTwd': '' if data.get('pickupFeeTwd') is None else str(data['pickupFeeTwd']),
        'shippingNote': data.get('shippingNote', ''),
        'lineSummaryReceivedAt': case.get('lineSummaryReceivedAt', ''),
        'revision': revision,
    }
    accepted = data.get('rules') == [True] * 4 and data.get('checks') == [True] * 4
    for key, text in zip(('contentConfirmation', 'cleaningConfirmation',
                          'packingConfirmation', 'shippingConfirmation'), ACKS):
        record[key] = text if accepted else '待客服確認（舊案件）'
    validate_record(record)
    return record


def validate_record(record):
    if not isinstance(record, dict) or set(record) != CASE_FIELDS:
        raise ValueError('雲端案件欄位格式錯誤')
    if not re.fullmatch(r'R\d{8}-\d{4,}', record['id'] if isinstance(record['id'], str) else ''):
        raise ValueError('雲端案件編號格式錯誤')
    revision = record.get('revision')
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= 9007199254740991:
        raise ValueError('雲端案件版本格式錯誤')
    for key, value in record.items():
        if key != 'revision' and (not isinstance(value, str) or len(value) > 8000):
            raise ValueError('雲端案件內容格式錯誤')
    for key in ('createdAt', 'updatedAt'):
        if not _valid_timestamp(record[key]):
            raise ValueError('雲端案件時間格式錯誤')
    if record['lineSummaryReceivedAt'] and not _valid_timestamp(record['lineSummaryReceivedAt']):
        raise ValueError('雲端案件時間格式錯誤')
    if record['pickupFeeTwd'] not in ('', '350'):
        raise ValueError('雲端回收費用格式錯誤')
    if len(json.dumps(record, ensure_ascii=False).encode('utf-8')) > MAX_BODY - 500:
        raise ValueError('雲端案件內容過長')
    return record


def _valid_timestamp(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        return False
    try:
        datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        return True
    except ValueError:
        return False


def payload_hash(record):
    validate_record(record)
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


class GoogleContentRedirect(urllib.request.HTTPRedirectHandler):
    """Follow Google's ContentService response using GET, never forward its secret."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if (code not in (301, 302, 303) or target.scheme != 'https'
                or target.netloc != 'script.googleusercontent.com'
                or not target.path.startswith('/macros/echo')):
            raise urllib.error.URLError('Google redirect rejected')
        return urllib.request.Request(newurl, method='GET', headers={'Accept': 'application/json'})


def _send(endpoint, secret, sheet_id, operation, record=None, opener=None):
    """Return sanitized delivery state; failures never remove the locally saved case."""
    try:
        validate_endpoint(endpoint)
        validate_secret(secret)
        if not isinstance(sheet_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,100}', sheet_id):
            raise ValueError('sheet id')
        if operation not in ('ping', 'upsert', 'pingPickup', 'upsertPickup'):
            raise ValueError('operation')
        pickup_operation = operation in ('pingPickup', 'upsertPickup')
        write_operation = operation in ('upsert', 'upsertPickup')
        if pickup_operation and sheet_id != PRIMARY_SHEET_ID:
            raise ValueError('pickup request scope')
        if write_operation:
            validate_record(record)
        if operation == 'upsertPickup' and (
                record['shipping'] != '由客服派遣物流回收'
                or not re.fullmatch(r'U[0-9a-f]{32}', record['lineUserId'])):
            raise ValueError('pickup eligibility')
    except (ValueError, TypeError, KeyError):
        return {'state': 'failed', 'error': '雲端同步設定或案件格式錯誤'}
    payload = {'secret': secret, 'sheetId': sheet_id, 'operation': operation}
    if write_operation:
        payload['case'] = record
    body = json.dumps(payload,
                      ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(body) > MAX_BODY:
        return {'state': 'failed', 'error': '雲端案件內容過長'}
    request = urllib.request.Request(endpoint, data=body, method='POST', headers={
        'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'})
    try:
        opener = opener or urllib.request.build_opener(GoogleContentRedirect())
        with opener.open(request, timeout=25) as response:
            raw = response.read(8193)
            if response.status != 200 or len(raw) > 8192:
                raise ValueError('invalid response')
            result = json.loads(raw)
        expected_schema = 'petpivot-pickup-v1' if pickup_operation else 'petpivot-v1'
        valid = (isinstance(result, dict) and result.get('ok') is True
                 and result.get('sheetId') == sheet_id and result.get('schema') == expected_schema)
        if pickup_operation:
            valid = (valid and result.get('pickupSheetId') == PICKUP_SHEET_ID
                     and type(result.get('pickupSheetGid')) is int
                     and result.get('pickupSheetGid') == PICKUP_SHEET_GID)
        if write_operation:
            valid = (valid and result.get('caseId') == record['id']
                     and result.get('revision') == record['revision']
                     and result.get('action') in ('inserted', 'updated', 'unchanged', 'stale'))
            if pickup_operation:
                valid = valid and type(result.get('revision')) is int
        if not valid:
            if isinstance(result, dict) and result.get('error') == 'unauthorized':
                return {'state': 'failed', 'error': '雲端同步金鑰不符'}
            if isinstance(result, dict) and result.get('error') == 'schema_mismatch':
                return {'state': 'failed', 'error': 'Google 試算表欄位與系統不符'}
            if isinstance(result, dict) and result.get('error') == 'sheet_mismatch':
                return {'state': 'failed', 'error': 'Google 同步接收器連結到其他試算表'}
            if isinstance(result, dict) and result.get('error') in ('duplicate_case_id', 'ownership_conflict', 'revision_conflict'):
                return {'state': 'failed', 'error': 'Google 試算表案件或版本資料衝突，請由管理員確認'}
            return {'state': 'failed', 'error': 'Google 雲端同步未確認成功'}
        return {'state': 'synced', 'action': result.get('action', 'verified')}
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            message = 'Google 部署未開放系統存取，請確認部署設定'
        elif error.code == 429:
            message = 'Google 暫時限制同步，稍後自動重試'
        else:
            message = 'Google 雲端同步暫時無法連線'
        return {'state': 'failed', 'error': message}
    except Exception:
        return {'state': 'failed', 'error': 'Google 雲端同步暫時無法連線'}


def ping(endpoint, secret, sheet_id, opener=None):
    """Read-only, authenticated header/receiver-binding check; no case is written."""
    return _send(endpoint, secret, sheet_id, 'ping', opener=opener)


def upsert(endpoint, secret, sheet_id, record, opener=None):
    return _send(endpoint, secret, sheet_id, 'upsert', record, opener)


def pickup_ping(endpoint, secret, sheet_id, opener=None):
    """Read-only check of the fixed pickup file, using the existing deployment."""
    return _send(endpoint, secret, sheet_id, 'pingPickup', opener=opener)


def upsert_pickup(endpoint, secret, sheet_id, record, opener=None):
    """Deliver an eligible, already enrolled new case to the fixed pickup file."""
    return _send(endpoint, secret, sheet_id, 'upsertPickup', record, opener)


def upsert_case(endpoint, secret, record, sheet_id=None, opener=None):
    """Compatibility wrapper; the configured sheet id is required for binding."""
    return upsert(endpoint, secret, sheet_id, record, opener)


def init_queue(connection):
    """Use the existing case DB connection, inside the application's transaction."""
    connection.execute('''CREATE TABLE IF NOT EXISTS cloud_outbox (
        case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
        synced_at TEXT NOT NULL DEFAULT '')''')


def queue_case(connection, case, updated_at=None):
    """Atomically enqueue with the case mutation; collapse superseded versions."""
    ident = case['id']
    prior = connection.execute('SELECT revision FROM cloud_outbox WHERE case_id=?', (ident,)).fetchone()
    revision = (prior[0] if prior else 0) + 1
    record = build_payload(case, revision, updated_at or time.strftime('%Y-%m-%d %H:%M:%S'))
    connection.execute('''INSERT INTO cloud_outbox(case_id,revision,payload)
        VALUES(?,?,?) ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,
        payload=excluded.payload,state='pending',attempts=0,next_attempt=0,last_error='' ''',
        (ident, revision, json.dumps(record, ensure_ascii=False)))
    return revision


def process_queue_once(db_path, endpoint, secret, sheet_id=None, sender=upsert, now=None):
    """Lease one persistent job; safe after crashes and concurrent case updates."""
    if not endpoint or not secret:
        return {'state': 'not_configured', 'processed': False}
    stamp = time.time() if now is None else now
    connection = sqlite3.connect(db_path, timeout=15)
    try:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('''SELECT case_id,revision,payload,attempts
                FROM cloud_outbox WHERE state IN ('pending','working') AND next_attempt<=?
                ORDER BY next_attempt,case_id LIMIT 1''', (stamp,)).fetchone()
            if not row:
                return {'state': 'idle', 'processed': False}
            ident, revision, raw, attempts = row
            connection.execute("UPDATE cloud_outbox SET state='working',next_attempt=? WHERE case_id=? AND revision=?", (stamp + 90, ident, revision))
        try:
            result = sender(endpoint, secret, sheet_id, json.loads(raw))
            if not isinstance(result, dict) or result.get('state') not in ('synced', 'failed'):
                raise ValueError('invalid sender result')
        except Exception:
            result = {'state': 'failed', 'error': 'Google 雲端同步暫時無法連線'}
        with connection:
            if result['state'] == 'synced':
                connection.execute("UPDATE cloud_outbox SET state='synced',last_error='',synced_at=? WHERE case_id=? AND revision=?", (time.strftime('%Y-%m-%d %H:%M:%S'), ident, revision))
            else:
                # sender errors are already sanitized. Never save upstream bodies.
                error = result.get('error', 'Google 雲端同步未確認成功')
                connection.execute("UPDATE cloud_outbox SET state='pending',attempts=?,next_attempt=?,last_error=? WHERE case_id=? AND revision=?", (attempts + 1, stamp + min(3600, 30 * 2 ** min(attempts, 7)), error, ident, revision))
        return {'state': result['state'], 'processed': True}
    finally:
        connection.close()
