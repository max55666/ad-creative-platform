"""Explicit LINE-group review of unmatched pickup payments; never auto-approves.

The server must validate the LINE signature and destination before enqueue().
Private IDs and snapshot hashes stay in SQLite; group cards contain no secrets.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
import threading
import time
import uuid

from order_matching import normalize_name, normalize_phone
from service_desk_reconciliation import _missing_remark_exception, _remark, _reviewed_note_exception

TAIPEI = timezone(timedelta(hours=8))
PICKUP = '由客服派遣物流回收'
OPEN = {'已申請', '待收件', '待補資料', '待客戶確認報價'}
USER = re.compile(r'U[0-9a-f]{32}\Z')
CASE = r'R[0-9]{8}-[0-9]{4,8}'
LIFETIME = 7 * 86400


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode('utf-8')).hexdigest()


def timestamp(value, local=False):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.replace(tzinfo=TAIPEI) if local and result.tzinfo is None else result if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def positive(value):
    return type(value) is int and value > 0


def candidates(cases, repairs, orders):
    """Same strict search as the read-only monitor, plus immutable review hashes."""
    sources = {row['id']: row for row in repairs}
    used_numbers, used_ids = set(), set()
    for row in cases:
        payment = row.get('payment') or {}
        if payment.get('paymentOrderNumber'):
            used_numbers.add(payment['paymentOrderNumber'])
        for quote in [row.get('quote') or {}, *row.get('quoteHistory', [])]:
            if quote.get('acceptedOrderId'):
                used_ids.add(quote['acceptedOrderId'])
        used_numbers.update(r['order_number'] for r in row.get('receipts', []) + row.get('refundNotices', []) if r.get('order_number'))
    found = []
    for case in cases:
        repair = sources.get(case.get('id'), {})
        data = repair.get('data') or {}
        if isinstance(data, str):
            data = json.loads(data)
        quote, payment = case.get('quote') or {}, case.get('payment') or {}
        name, created = normalize_name(case.get('name', '')), timestamp(quote.get('createdAt'), True)
        if not (case.get('managed') is True and case.get('shipping') == PICKUP
                and repair.get('status') in OPEN and data.get('shipping') == PICKUP
                and name and normalize_name(data.get('name', '')) == name
                and quote.get('status') == 'active' and quote.get('paymentStatus') == 'awaiting_payment'
                and not quote.get('acceptedOrderId') and positive(quote.get('total'))
                and positive(quote.get('version')) and quote.get('currency') == 'TWD'
                and payment.get('paymentStatus') in {'待付款', '需人工核對'}
                and type(payment.get('amountDue')) is int and payment['amountDue'] == quote['total']
                and type(payment.get('quoteVersion')) is int and payment['quoteVersion'] == quote['version']
                and not payment.get('paymentOrderNumber') and created):
            continue
        phone = normalize_phone(case.get('phone', ''))
        for order in orders:
            ordered = timestamp(order.get('createdAt'))
            if not (order.get('orderNumber') and order.get('id')
                    and order['orderNumber'] not in used_numbers and order['id'] not in used_ids
                    and order.get('reportedPaymentStatus') == 'completed' and order.get('currency') == 'TWD'
                    and order.get('productValid') is True and order.get('reviewReasons') == []
                    and positive(order.get('total')) and order['total'] == quote['total']
                    and ordered and ordered >= created
                    and name in [normalize_name(order.get(k, '')) for k in ('customerName', 'recipientName')]):
                continue
            match_phone = bool(phone) and any(phone == normalize_phone(order.get(k, '')) for k in ('customerPhone', 'recipientPhone'))
            remark = order.get('orderRemarks') or ''
            references = sorted(set(re.findall(CASE, remark)))
            warnings = []
            if not match_phone:
                warnings.append('電話未吻合，請至付款後台核實')
            if references and references != [case['id']]:
                warnings.append('訂單備註包含其他案件編號')
            remark_names = [normalize_name(v) for v in re.findall(r'(?:申請人姓名|申請人)[：:]\s*([^\r\n]+)', remark)]
            if any(v and v != name for v in remark_names):
                warnings.append('備註姓名與申請人不同')
            manual = _missing_remark_exception(remark, {'caseNumber': case['id'], 'name': case['name']})
            reviewed_note = (not manual and _reviewed_note_exception(
                remark, {'caseNumber': case['id'], 'name': case['name']}))
            remark_case, remark_name, remark_error = _remark(remark)
            # Correctly annotated orders belong to the pre-existing automatic
            # reconciliation flow, not a group review whose rejection it ignores.
            automatic = bool(not manual and not remark_error and remark_case == case['id']
                             and remark_name == case['name'] and match_phone)
            if not manual and not reviewed_note and (remark_error or remark_case != case['id'] or remark_name != case['name']):
                warnings.append('備註內容須至付款後台核實')
            row = {'caseNumber': case['id'], 'name': case['name'], 'model': case.get('model', ''),
                   'quoteId': quote['id'], 'quoteVersion': quote['version'], 'orderNumber': order['orderNumber'],
                   'amountDue': quote['total'], 'repairFee': quote.get('repairFee'), 'pickupFee': quote.get('pickupFee'),
                   'phoneMatches': match_phone, 'remarkEmpty': not bool(remark.strip()), 'warnings': warnings,
                   'manualRequired': manual, 'automaticFlow': automatic,
                   'sourceHash': digest({'id': repair['id'], 'user': repair.get('user_id'), 'data': {
                       k: data.get(k, '') for k in ('name', 'phone', 'model', 'shipping', 'pickupAddress', 'returnAddress', 'order', 'paymentWorkflow')}}),
                   'orderHash': digest({k: order.get(k) for k in ('id', 'orderNumber', 'customerName', 'customerPhone',
                       'recipientName', 'recipientPhone', 'address', 'orderRemarks', 'currency', 'total', 'productValid',
                       'reportedPaymentStatus', 'reportedPaidAt', 'createdAt', 'reviewReasons', 'repairAllocation')})}
            if reviewed_note:
                # Keep the whole bounded note visible to the human approver and
                # bind the approval to this exact note via the existing hashes.
                row.update(reviewedNoteRequired=True, reviewNote=remark)
            found.append(row)
    by_case, by_order = Counter(r['caseNumber'] for r in found), Counter(r['orderNumber'] for r in found)
    for row in found:
        if by_case[row['caseNumber']] > 1:
            row['warnings'].append('同一案件符合多筆訂單，請至付款後台核實')
        if by_order[row['orderNumber']] > 1:
            row['warnings'].append('同一訂單符合多筆案件，請至付款後台核實')
        row['approveSafe'] = not row['warnings']
        row['fingerprint'] = digest(row)
    # Automatic-flow rows still participate in ambiguity detection above.
    return [row for row in found if not row['automaticFlow']]


def card(row, identifier):
    from dispatch_cards import _bubble, _text, _postback, _flex
    case = row['caseNumber']
    lines = [f"維修編號：{case}", f"申請人：{row['name']}", f"付款訂單：{row['orderNumber']}",
             f"核定／付款金額：NT${row['amountDue']:,}", '寄送方式：客服物流回收',
             '電話：吻合' if row['phoneMatches'] else '電話：未吻合',
             '下單備註：未填寫' if row['remarkEmpty'] else '下單備註：已有內容',
             'SHOPLINE 回報付款完成，待確認；尚未加入派車名單。']
    lines += row['warnings']
    if row.get('reviewedNoteRequired'):
        lines += ['訂單備註（請核實）：' + row['reviewNote'],
                  '備註未依指定格式填寫；請確認此訂單屬於本案後，再按「同意派車」。',
                  '取件地址以送修表單為準；如需變更，請先至後台修正。']
    buttons = []
    if row['approveSafe']:
        buttons.append(_postback('同意派車', 'ppr1:approve:' + identifier, '同意派車 ' + case))
    buttons.append(_postback('不同意派車', 'ppr1:reject:' + identifier, '不同意派車 ' + case))
    lines.append('由指定審核者確認後才會配對付款並同步派車名單；不是已完成派車。')
    return [_flex('派車付款待審核：' + case, _bubble('派車付款待審核', [_text('\n'.join(lines))], buttons))]


class PickupPaymentReview:
    def __init__(self, server, payments, clock=time.time, sender=None, reader=None):
        self.s, self.p, self.clock = server, payments, clock
        self.lock, self.wake = threading.Lock(), threading.Event()
        self.started = False
        if sender is None:
            from line_support import send_group_messages
            sender = lambda group, messages, key: send_group_messages(self.s['TOKEN'], group, messages, key)
        self.sender = sender
        if reader is None:
            from cloud_support import read_pickup_dispatch
            def reader(ids):
                values = self.s['cloud_settings']()
                return read_pickup_dispatch(values['googleSheetEndpoint'], values['googleSheetSecret'], values['googleSheetId'], ids)
        self.reader = reader

    def init(self):
        with self.s['connect']() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS pickup_review_settings (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL DEFAULT 0,
              group_id TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'allowlist',
              approvers TEXT NOT NULL DEFAULT '[]', hours TEXT NOT NULL DEFAULT '[22]', enabled_at REAL NOT NULL DEFAULT 0);
            INSERT OR IGNORE INTO pickup_review_settings(singleton) VALUES(1);
            CREATE TABLE IF NOT EXISTS pickup_review_jobs (
              id TEXT PRIMARY KEY, group_id TEXT NOT NULL, created REAL NOT NULL,
              state TEXT NOT NULL DEFAULT 'pending', next_attempt REAL NOT NULL DEFAULT 0,
              attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', completed REAL NOT NULL DEFAULT 0,
              candidate_count INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pickup_review_candidates (
              id TEXT PRIMARY KEY, group_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL, expires REAL NOT NULL,
              actor TEXT NOT NULL DEFAULT '', event_id TEXT NOT NULL DEFAULT '', event_stamp INTEGER NOT NULL DEFAULT 0,
              request_id TEXT UNIQUE NOT NULL, next_attempt REAL NOT NULL DEFAULT 0,
              attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', validated REAL NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS pickup_review_fingerprints ON pickup_review_candidates(group_id,fingerprint);
            CREATE TABLE IF NOT EXISTS pickup_review_events (id TEXT PRIMARY KEY, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS pickup_review_push (
              id TEXT PRIMARY KEY, group_id TEXT NOT NULL, candidate_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
              messages TEXT NOT NULL, retry_key TEXT UNIQUE NOT NULL, created REAL NOT NULL,
              state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
              first_attempt REAL NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
            ''')

    def setting(self, c):
        return dict(c.execute('SELECT * FROM pickup_review_settings WHERE singleton=1').fetchone())

    def group(self, c, setting=None):
        setting = setting or self.setting(c)
        group = self.s['selected_pickup_group'](c)
        if (not setting['enabled'] or not self.s['pickup_notification_available']()
                or not self.s['active_pickup_group'](group) or group['group_id'] != setting['group_id']):
            return None
        return group

    def configure(self, enabled, approvers=None, mode='allowlist', hours=None):
        approvers, hours = approvers or [], [22] if hours is None else hours
        if (type(enabled) is not bool or mode not in ('allowlist', 'group_members')
                or type(approvers) is not list or len(approvers) > 20
                or any(not isinstance(x, str) or not USER.fullmatch(x) for x in approvers)
                or len(set(approvers)) != len(approvers)
                or type(hours) is not list or not hours or len(hours) > 4
                or any(type(h) is not int or not 0 <= h <= 23 for h in hours) or len(set(hours)) != len(hours)
                or enabled and mode == 'allowlist' and not approvers):
            raise ValueError('巡檢時段或審核權限設定不正確')
        with self.s['PICKUP_NOTIFICATION_LOCK']:
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE')
                group = self.s['selected_pickup_group'](c)
                if enabled and (not self.s['active_pickup_group'](group) or not self.s['pickup_notification_available']()):
                    raise ValueError('請先連結派車通知群組')
                old = self.setting(c)
                group_id = group['group_id'] if group else ''
                same = (old['enabled'] == int(enabled) and old['group_id'] == group_id and old['mode'] == mode
                        and json.loads(old['approvers']) == approvers and json.loads(old['hours']) == sorted(hours))
                if not same:
                    c.execute("UPDATE pickup_review_jobs SET state='cancelled',error='settings_changed' WHERE state IN ('pending','working','retry')")
                    c.execute("UPDATE pickup_review_candidates SET state='cancelled',error='settings_changed' WHERE state IN ('pending','approved','validated','syncing')")
                    c.execute("UPDATE pickup_review_push SET state='cancelled',error='settings_changed' WHERE state IN ('pending','working','retry')")
                c.execute('UPDATE pickup_review_settings SET enabled=?,group_id=?,mode=?,approvers=?,hours=?,enabled_at=? WHERE singleton=1',
                          (int(enabled), group_id, mode, dump(approvers), dump(sorted(hours)), old['enabled_at'] if same else self.clock()))
        self.wake.set()
        return self.status()

    def allowed(self, c, job):
        setting = self.setting(c)
        group = self.group(c, setting)
        return bool(group and group['group_id'] == job['group_id'] and USER.fullmatch(job.get('actor', ''))
                    and job['event_stamp'] >= group['event_stamp']
                    and (setting['mode'] == 'group_members' or job['actor'] in json.loads(setting['approvers'])))

    def push(self, c, key, group, messages, kind='feedback', candidate=''):
        c.execute('INSERT OR IGNORE INTO pickup_review_push(id,group_id,candidate_id,kind,messages,retry_key,created) VALUES(?,?,?,?,?,?,?)',
                  (key, group, candidate, kind, dump(messages), str(uuid.uuid4()), self.clock()))

    def feedback(self, c, key, group, text):
        self.push(c, key, group, [{'type': 'text', 'text': text}])

    def scan_now(self):
        with self.s['connect']() as c:
            group = self.group(c)
            if not group:
                raise ValueError('群組付款巡檢尚未啟用')
            existing = c.execute("SELECT id FROM pickup_review_jobs WHERE group_id=? AND state IN ('pending','working','retry')", (group['group_id'],)).fetchone()
            key = existing['id'] if existing else 'manual:' + str(uuid.uuid4())
            c.execute('INSERT OR IGNORE INTO pickup_review_jobs(id,group_id,created) VALUES(?,?,?)', (key, group['group_id'], self.clock()))
        self.wake.set()
        return {'queued': True, 'jobId': key}

    def schedule_once(self):
        now = self.clock()
        local = datetime.fromtimestamp(now, TAIPEI)
        with self.s['connect']() as c:
            setting = self.setting(c)
            group = self.group(c, setting)
            if not group:
                return False
            inserted = False
            for hour in json.loads(setting['hours']):
                due = local.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()
                if due < setting['enabled_at'] or not 0 <= now - due < 3600:
                    continue
                key = f"daily:{local.date().isoformat()}:{hour:02d}"
                inserted |= bool(c.execute('INSERT OR IGNORE INTO pickup_review_jobs(id,group_id,created) VALUES(?,?,?)', (key, group['group_id'], now)).rowcount)
            return inserted

    def inventory(self):
        state = self.p.state()
        with self.s['connect']() as c:
            repairs = [dict(r) for r in c.execute('SELECT * FROM cases')]
        rows = state.get('cases')
        if not isinstance(rows, list) or len(rows) >= 1000 or {r['id'] for r in rows} != {r['id'] for r in repairs}:
            raise ValueError('case_inventory_incomplete')
        return rows, repairs

    def collect(self):
        rows, repairs = self.inventory()
        fetched = self.p.provider.fetch({'days': 30})
        if fetched.get('status') != 'ok' or fetched.get('truncated') is not False or not isinstance(fetched.get('orders'), list):
            raise ValueError('shopline_orders_incomplete')
        return candidates(rows, repairs, fetched['orders'])

    def scan_once(self):
        now = self.clock()
        with self.s['connect']() as c:
            row = c.execute("SELECT * FROM pickup_review_jobs WHERE state IN ('pending','retry','working') AND next_attempt<=? ORDER BY created LIMIT 1", (now,)).fetchone()
            if not row:
                return False
            job = dict(row)
            group = self.group(c)
            if not group or group['group_id'] != job['group_id']:
                c.execute("UPDATE pickup_review_jobs SET state='cancelled',error='group_changed' WHERE id=?", (job['id'],))
                return True
            c.execute("UPDATE pickup_review_jobs SET state='working',attempts=attempts+1,next_attempt=? WHERE id=?", (now + 600, job['id']))
        try:
            found = self.collect()
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE')
                group = self.group(c)
                if not group or group['group_id'] != job['group_id']:
                    c.execute("UPDATE pickup_review_jobs SET state='cancelled',error='group_changed' WHERE id=?", (job['id'],))
                    return True
                current = {r['fingerprint'] for r in found}
                for old in c.execute("SELECT * FROM pickup_review_candidates WHERE group_id=? AND state='pending'", (group['group_id'],)).fetchall():
                    if old['fingerprint'] not in current or old['expires'] <= now:
                        c.execute("UPDATE pickup_review_candidates SET state='expired' WHERE id=?", (old['id'],))
                for item in found:
                    old = c.execute("SELECT * FROM pickup_review_candidates WHERE group_id=? AND fingerprint=? AND state NOT IN ('cancelled','expired') ORDER BY created DESC LIMIT 1", (group['group_id'], item['fingerprint'])).fetchone()
                    if old:
                        continue
                    identifier = secrets.token_urlsafe(18)
                    c.execute('INSERT INTO pickup_review_candidates(id,group_id,fingerprint,payload,created,expires,request_id) VALUES(?,?,?,?,?,?,?)',
                              (identifier, group['group_id'], item['fingerprint'], dump(item), now, now + LIFETIME, str(uuid.uuid4())))
                    self.push(c, 'candidate:' + identifier, group['group_id'], card(item, identifier), 'candidate', identifier)
                c.execute("UPDATE pickup_review_jobs SET state='completed',completed=?,candidate_count=?,error='' WHERE id=?", (self.clock(), len(found), job['id']))
        except Exception:
            with self.s['connect']() as c:
                terminal = job['attempts'] >= 5 or self.clock() - job['created'] > 3600
                c.execute('UPDATE pickup_review_jobs SET state=?,next_attempt=?,error=? WHERE id=?', ('failed' if terminal else 'retry', self.clock() + 60, 'scan_incomplete', job['id']))
                if terminal:
                    self.feedback(c, 'scan-failed:' + job['id'], job['group_id'], '派車付款巡檢未完整完成，不能判定沒有待審核案件。請至付款後台確認；本次未自動配對或派車。')
        return True

    def enqueue(self, event):
        kind, identifier, case_id = None, '', ''
        if event.get('type') == 'postback':
            parsed = re.fullmatch(r'ppr1:(approve|reject):([A-Za-z0-9_-]{24})', (event.get('postback') or {}).get('data', ''))
            if parsed:
                kind, identifier = parsed.groups()
        elif event.get('type') == 'message' and (event.get('message') or {}).get('type') == 'text':
            parsed = re.fullmatch(r'(同意派車|不同意派車)\s*(' + CASE + ')', event['message'].get('text', '').strip())
            if parsed:
                kind, case_id = ('approve' if parsed[1] == '同意派車' else 'reject'), parsed[2]
        if not kind:
            return False
        source, ident, stamp, now = event.get('source') or {}, event.get('webhookEventId'), event.get('timestamp'), self.clock()
        if (source.get('type') != 'group' or not isinstance(ident, str) or not re.fullmatch(r'[!-~]{1,128}', ident)
                or type(stamp) is not int or not now * 1000 - 600000 <= stamp <= now * 1000 + 300000):
            return True
        with self.s['PICKUP_NOTIFICATION_LOCK']:
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE')
                setting = self.setting(c)
                group = self.group(c, setting)
                if not group or source.get('groupId') != group['group_id'] or stamp < group['event_stamp']:
                    return True
                if not c.execute('INSERT OR IGNORE INTO pickup_review_events VALUES(?,?)', (ident, now)).rowcount:
                    return True
                actor = source.get('userId', '')
                authorized = isinstance(actor, str) and USER.fullmatch(actor) and (setting['mode'] == 'group_members' or actor in json.loads(setting['approvers']))
                if not authorized:
                    self.feedback(c, 'event:' + ident, group['group_id'], '這項付款派車審核僅限指定審核者操作，案件維持原狀。')
                    return True
                if identifier:
                    matches = c.execute('SELECT * FROM pickup_review_candidates WHERE id=? AND group_id=?', (identifier, group['group_id'])).fetchall()
                else:
                    matches = [r for r in c.execute("SELECT * FROM pickup_review_candidates WHERE group_id=? AND state='pending' AND expires>?", (group['group_id'], now)) if json.loads(r['payload'])['caseNumber'] == case_id]
                if len(matches) != 1:
                    self.feedback(c, 'event:' + ident, group['group_id'], '找不到唯一有效的待審核項目，請使用最新審核卡片或至付款後台確認。')
                    return True
                job, item = dict(matches[0]), json.loads(matches[0]['payload'])
                if job['state'] != 'pending' or job['expires'] <= now:
                    self.feedback(c, 'event:' + ident, group['group_id'], item['caseNumber'] + '：這張審核卡已處理或失效，未重複配對。')
                elif kind == 'approve' and not item['approveSafe']:
                    self.feedback(c, 'event:' + ident, group['group_id'], item['caseNumber'] + '：資料有歧義，請至付款後台人工核實，尚未配對或派車。')
                else:
                    c.execute('UPDATE pickup_review_candidates SET state=?,actor=?,event_id=?,event_stamp=?,next_attempt=0 WHERE id=? AND state=?',
                              ('approved' if kind == 'approve' else 'rejected', actor, ident, stamp, job['id'], 'pending'))
                    text = '：已收到同意，正在重新核對付款；完成派車名單同步後會另行通知。' if kind == 'approve' else '：已記錄不同意派車，付款與派車名單維持原狀。'
                    self.feedback(c, 'event:' + ident, group['group_id'], item['caseNumber'] + text)
        self.wake.set()
        return True

    def guard(self, job, order, wrapper):
        with self.s['connect']() as c:
            row = c.execute('SELECT * FROM pickup_review_candidates WHERE id=?', (job['id'],)).fetchone()
            if not row or row['state'] != 'validated' or row['expires'] <= self.clock() or not self.allowed(c, dict(row)):
                return False
        item = json.loads(job['payload'])
        if (wrapper.get('quote', {}).get('id') != item['quoteId'] or wrapper['quote'].get('version') != item['quoteVersion']):
            return False
        rows, repairs = self.inventory()
        fresh = candidates(rows, repairs, [order])
        return len([r for r in fresh if r['fingerprint'] == item['fingerprint'] and r['approveSafe']]) == 1

    def bound(self, item):
        detail = self.p.detail(item['caseNumber'])
        payment, quote = detail.get('payment') or {}, detail.get('quote') or {}
        return (quote.get('id') == item['quoteId'] and quote.get('version') == item['quoteVersion']
                and payment.get('paymentStatus') == '已付款' and payment.get('amountPaid') == item['amountDue']
                and payment.get('paymentOrderNumber') == item['orderNumber']), detail

    def block(self, job, code, text):
        with self.s['connect']() as c:
            c.execute("UPDATE pickup_review_candidates SET state='blocked',error=? WHERE id=?", (code, job['id']))
            self.feedback(c, 'blocked:' + job['id'], job['group_id'], json.loads(job['payload'])['caseNumber'] + '：' + text)

    def approval_once(self):
        now = self.clock()
        with self.s['connect']() as c:
            row = c.execute("SELECT * FROM pickup_review_candidates WHERE state IN ('approved','validated','syncing') AND next_attempt<=? ORDER BY created LIMIT 1", (now,)).fetchone()
            if not row:
                return False
            job, item = dict(row), json.loads(row['payload'])
            authorized = self.allowed(c, job)
            if not authorized:
                c.execute("UPDATE pickup_review_candidates SET state='cancelled',error='authorization_changed' WHERE id=?", (job['id'],))
                return True
            c.execute('UPDATE pickup_review_candidates SET attempts=attempts+1,next_attempt=? WHERE id=?', (now + 120, job['id']))
        try:
            already, detail = self.bound(item)
            if already and job['state'] != 'syncing':
                with self.s['connect']() as c:
                    c.execute("UPDATE pickup_review_candidates SET state='syncing',next_attempt=0 WHERE id=?", (job['id'],))
                return True
            if job['state'] != 'syncing' and job['expires'] <= now:
                self.block(job, 'expired', '審核已逾期，請至付款後台重新核實；未放行派車。')
                return True
            if job['state'] == 'approved' or job['state'] == 'validated' and now - job['validated'] > 90:
                fresh = self.collect()
                exact = [r for r in fresh if r['fingerprint'] == item['fingerprint'] and r['approveSafe']]
                if len(exact) != 1:
                    self.block(job, 'candidate_changed', '付款、核價或案件資料已異動，請重新核實；尚未完成派車同步。')
                    return True
                with self.s['connect']() as c:
                    current = c.execute('SELECT * FROM pickup_review_candidates WHERE id=?', (job['id'],)).fetchone()
                    if current and current['state'] in ('approved', 'validated') and self.allowed(c, dict(current)):
                        c.execute("UPDATE pickup_review_candidates SET state='validated',validated=?,next_attempt=? WHERE id=?", (self.clock(), self.clock() + 3, job['id']))
                return True
            if job['state'] == 'validated':
                payload = {'orderNumber': item['orderNumber'], 'requestId': job['request_id']}
                if item['manualRequired']:
                    payload.update(confirm=True, reason='LINE 指定審核者確認姓名、電話及核定金額吻合，補救漏填送修備註。')
                if item.get('reviewedNoteRequired'):
                    payload.update(confirm=True, reason='LINE 指定審核者已閱讀原始訂單備註，確認姓名、電話與核定金額吻合且此訂單屬於本案。')
                note_option = {'reviewed_note': True} if item.get('reviewedNoteRequired') else {}
                result = self.p.reconcile(item['quoteId'], payload, actor='LINE 群組指定審核者',
                                          manual=item['manualRequired'], authorization_guard=lambda order, wrapper: self.guard(job, order, wrapper),
                                          authorization_lock=self.s['PICKUP_NOTIFICATION_LOCK'], **note_option)
                if result.get('result', {}).get('state') not in ('matched_internal_only', 'duplicate'):
                    self.block(job, 'reconciliation_blocked', '最新付款核對未通過，請至付款後台確認；尚未完成派車同步。')
                    return True
                with self.s['connect']() as c:
                    c.execute("UPDATE pickup_review_candidates SET state='syncing',next_attempt=? WHERE id=? AND state='validated'", (self.clock() + 5, job['id']))
                return True
            # Payment workers own synchronization and promotion; this reader never inserts dispatch rows.
            if not already:
                self.block(job, 'payment_changed', '付款狀態已變更，尚未完成派車同步，請至付款後台確認。')
                return True
            with self.s['connect']() as c:
                queued = c.execute('SELECT state FROM pickup_outbox WHERE case_id=?', (item['caseNumber'],)).fetchone()
                source = c.execute('SELECT * FROM cases WHERE id=?', (item['caseNumber'],)).fetchone()
            if source and source['status'] not in OPEN:
                self.block(job, 'case_no_longer_open', '案件已進入其他處理階段，請至付款後台確認；不再回報待派車完成。')
                return True
            if not detail.get('releaseAllowed') or not queued or queued['state'] != 'synced' or not source:
                raise RuntimeError('synchronization_pending')
            data = source['data'] if isinstance(source['data'], dict) else json.loads(source['data'])
            result = self.reader([item['caseNumber']])
            row = (result.get('cases') or [{}])[0]
            valid = (result.get('state') == 'synced' and len(result.get('cases', [])) == 1
                     and row.get('caseId') == item['caseNumber'] and normalize_name(row.get('name', '')) == normalize_name(item['name'])
                     and normalize_phone(row.get('phone', '')) == normalize_phone(data.get('phone', ''))
                     and row.get('address') == (data.get('pickupAddress') or data.get('returnAddress'))
                     and row.get('model') == data.get('model'))
            with self.s['connect']() as c:
                current = c.execute('SELECT * FROM pickup_review_candidates WHERE id=?', (job['id'],)).fetchone()
                if not current or current['state'] != 'syncing' or not self.allowed(c, dict(current)):
                    return True
            still_bound, latest = self.bound(item)
            if not valid or not still_bound or not latest.get('releaseAllowed'):
                raise RuntimeError('dispatch_readback_pending')
            status = row.get('status') or '未派車'
            with self.s['connect']() as c:
                c.execute("UPDATE pickup_review_candidates SET state='completed',error='' WHERE id=? AND state='syncing'", (job['id'],))
                self.push(c, 'completed:' + job['id'], job['group_id'], [{'type': 'text', 'text':
                    f"【派車審核已完成】\n維修編號：{item['caseNumber']}\n申請人：{item['name']}\n付款訂單：{item['orderNumber']}\n核對金額：NT${item['amountDue']:,}\n已完成付款配對，並確認同步至派車名單。\n同步確認時的派車狀態：{status}\n本通知不代表物流已實際派車。"}], 'completed', job['id'])
        except Exception:
            with self.s['connect']() as c:
                current = c.execute('SELECT state FROM pickup_review_candidates WHERE id=?', (job['id'],)).fetchone()
                if current and current['state'] in ('approved', 'validated', 'syncing'):
                    c.execute("UPDATE pickup_review_candidates SET next_attempt=?,error='verification_or_sync_pending' WHERE id=?", (self.clock() + 30, job['id']))
                    if job['attempts'] >= 5:
                        self.feedback(c, 'delayed:' + job['id'], job['group_id'], item['caseNumber'] + '：審核已收到，但付款核對或派車名單同步尚未確認完成。系統將重試，請勿視為已派車。')
        return True

    def push_once(self):
        now = self.clock()
        with self.s['connect']() as c:
            row = c.execute("SELECT * FROM pickup_review_push WHERE state IN ('pending','retry','working') AND next_attempt<=? ORDER BY created,id LIMIT 1", (now,)).fetchone()
            if not row:
                return False
            job = dict(row)
            group = self.group(c)
            candidate = c.execute('SELECT * FROM pickup_review_candidates WHERE id=?', (job['candidate_id'],)).fetchone() if job['candidate_id'] else None
            valid = bool(group and group['group_id'] == job['group_id'])
            if job['kind'] == 'candidate':
                valid = valid and candidate and candidate['state'] == 'pending' and candidate['expires'] > now
            if job['kind'] == 'completed':
                valid = valid and candidate and candidate['state'] == 'completed'
            if not valid:
                c.execute("UPDATE pickup_review_push SET state='cancelled',error='no_longer_current' WHERE id=?", (job['id'],))
                return True
            first = job['first_attempt'] or now
            if now - first >= 23 * 3600 or job['attempts'] >= 12:
                c.execute("UPDATE pickup_review_push SET state='failed',error='push_retry_window_expired' WHERE id=?", (job['id'],))
                return True
            c.execute("UPDATE pickup_review_push SET state='working',first_attempt=?,attempts=attempts+1,next_attempt=? WHERE id=?", (first, now + 90, job['id']))
        try:
            # Serialize the final recipient check with leave/rebind/disable.
            # No SQLite transaction is held across the bounded LINE request.
            with self.s['PICKUP_NOTIFICATION_LOCK']:
                with self.s['connect']() as c:
                    group = self.group(c)
                    queued_push = c.execute('SELECT state FROM pickup_review_push WHERE id=?', (job['id'],)).fetchone()
                    latest = c.execute('SELECT * FROM pickup_review_candidates WHERE id=?', (job['candidate_id'],)).fetchone() if job['candidate_id'] else None
                    valid = bool(group and group['group_id'] == job['group_id'] and queued_push and queued_push['state'] == 'working')
                    if job['kind'] == 'candidate':
                        valid = valid and latest and latest['state'] == 'pending' and latest['expires'] > self.clock()
                    if job['kind'] == 'completed':
                        valid = valid and latest and latest['state'] == 'completed'
                if valid and job['kind'] == 'completed':
                    item = json.loads(latest['payload'])
                    bound, detail = self.bound(item)
                    with self.s['connect']() as c:
                        queued = c.execute('SELECT state FROM pickup_outbox WHERE case_id=?', (item['caseNumber'],)).fetchone()
                        current = c.execute('SELECT * FROM cases WHERE id=?', (item['caseNumber'],)).fetchone()
                        eligible = (current and current['status'] in OPEN and self.s['pickup_eligible'](dict(current)))
                    valid = bool(bound and detail.get('releaseAllowed') and queued and queued['state'] == 'synced' and eligible)
                if not valid:
                    with self.s['connect']() as c:
                        c.execute("UPDATE pickup_review_push SET state='cancelled',error='authorization_or_payment_changed' WHERE id=?", (job['id'],))
                    return True
                result = self.sender(job['group_id'], json.loads(job['messages']), job['retry_key'])
        except Exception:
            result = {'state': 'failed', 'retryable': True}
        accepted = (isinstance(result, dict) and result.get('state') == 'accepted' and result.get('httpStatus') in (200, 409) and result.get('retryKey') == job['retry_key'])
        retry = isinstance(result, dict) and result.get('retryable') is True
        with self.s['connect']() as c:
            c.execute('UPDATE pickup_review_push SET state=?,next_attempt=?,error=? WHERE id=? AND state=?',
                      ('accepted' if accepted else 'retry' if retry else 'failed', self.clock() + min(3600, 30 * 2 ** min(job['attempts'], 7)),
                       '' if accepted else 'line_delivery_unconfirmed', job['id'], 'working'))
        return True

    def status(self):
        with self.s['connect']() as c:
            setting, group = self.setting(c), self.group(c)
            counts = {r['state']: r['n'] for r in c.execute('SELECT state,COUNT(*) n FROM pickup_review_candidates GROUP BY state')}
            push = {r['state']: r['n'] for r in c.execute('SELECT state,COUNT(*) n FROM pickup_review_push GROUP BY state')}
            last = c.execute('SELECT state,error,completed,candidate_count FROM pickup_review_jobs ORDER BY created DESC LIMIT 1').fetchone()
            recent = []
            for row in c.execute('SELECT state,error,created,payload FROM pickup_review_candidates ORDER BY created DESC LIMIT 30'):
                item = json.loads(row['payload'])
                recent.append({'caseId': item['caseNumber'], 'name': item['name'], 'orderNumber': item['orderNumber'],
                               'amount': item['amountDue'], 'state': row['state'], 'error': row['error'],
                               'phoneMatches': item['phoneMatches'], 'remarkEmpty': item['remarkEmpty'],
                               'warnings': item['warnings']})
        next_run = ''
        if group:
            local = datetime.fromtimestamp(self.clock(), TAIPEI)
            scheduled = [local.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(days=d)
                         for d in (0, 1) for h in json.loads(setting['hours'])]
            next_run = min(t for t in scheduled if t.timestamp() > max(self.clock(), setting['enabled_at'])).isoformat(timespec='seconds')
        return {'schema': 'petpivot-pickup-payment-review-v1', 'enabled': bool(setting['enabled']), 'effective': bool(group), 'groupName': group['name'] if group else '',
                'mode': setting['mode'], 'approverCount': len(json.loads(setting['approvers'])), 'hours': json.loads(setting['hours']),
                'timezone': 'Asia/Taipei', 'nextRunAt': next_run, 'counts': counts, 'pushCounts': push,
                'lastScan': dict(last) if last else None, 'candidates': recent}

    def run_once(self):
        if not self.lock.acquire(False):
            return False
        try:
            self.schedule_once()
            self.scan_once()
            self.approval_once()
            self.push_once()
            return True
        finally:
            self.lock.release()

    def start(self):
        if self.started:
            return
        self.started = True
        with self.s['connect']() as c:
            c.execute("UPDATE pickup_review_jobs SET state='retry',next_attempt=0 WHERE state='working'")
            c.execute("UPDATE pickup_review_push SET state='retry',next_attempt=0 WHERE state='working'")
        def worker():
            while True:
                try:
                    self.run_once()
                except Exception:
                    pass
                self.wake.wait(3)
                self.wake.clear()
        threading.Thread(target=worker, name='pickup-payment-review', daemon=True).start()
