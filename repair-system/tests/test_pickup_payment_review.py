"""Isolated SQLite/provider/LINE tests. Never contact a real service."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pickup_payment_review as review
from line_support import _group_messages_bytes

MAX = 'U' + 'a' * 32
OTHER = 'U' + 'b' * 32
GROUP = 'C' + 'a' * 32
CASE = 'R20261101-0001'


def fixture():
    case = {'id': CASE, 'name': '測試客戶', 'phone': '0912345678', 'model': 'AS11',
            'shipping': review.PICKUP, 'managed': True, 'releaseAllowed': False,
            'quote': {'id': 'WQ-11111111-1111-4111-8111-111111111111', 'version': 1, 'total': 2050,
                      'repairFee': 1700, 'pickupFee': 350, 'currency': 'TWD', 'createdAt': '2026-11-01 15:00:00',
                      'status': 'active', 'paymentStatus': 'awaiting_payment', 'acceptedOrderId': ''},
            'payment': {'paymentStatus': '待付款', 'amountDue': 2050, 'amountPaid': 0, 'quoteVersion': 1, 'paymentOrderNumber': ''},
            'quoteHistory': [], 'receipts': [], 'refundNotices': []}
    raw = {'id': CASE, 'status': '已申請', 'user_id': MAX,
           'data': {'name': case['name'], 'phone': case['phone'], 'model': 'AS11', 'shipping': review.PICKUP,
                    'pickupAddress': '測試取件地址', 'returnAddress': '不同寄回地址', 'order': 'original', 'paymentWorkflow': 'payment-v1'}}
    order = {'id': 'a' * 24, 'orderNumber': '20261102215728098', 'customerName': case['name'], 'recipientName': case['name'],
             'customerPhone': '+886912345678', 'recipientPhone': '', 'address': '測試地址', 'currency': 'TWD',
             'total': 2050, 'productValid': True, 'reviewReasons': [], 'reportedPaymentStatus': 'completed',
             'reportedPaidAt': '2026-11-02T21:57:40+00:00', 'createdAt': '2026-11-02T21:57:28+00:00', 'orderRemarks': ''}
    return case, raw, order


class Provider:
    def __init__(self, order):
        self.orders = [order]
        self.truncated = False

    def fetch(self, filters):
        return {'status': 'ok', 'truncated': self.truncated, 'orders': deepcopy(self.orders)}


class Payments:
    def __init__(self, case, order):
        self.cases = [case]
        self.provider = Provider(order)
        self.calls = []
        self.before_guard = None

    def state(self):
        return {'cases': deepcopy(self.cases)}

    def detail(self, ident):
        return deepcopy(next(c for c in self.cases if c['id'] == ident))

    def reconcile(self, quote_id, payload, actor, manual=False, authorization_guard=None, authorization_lock=None, reviewed_note=False):
        case = self.cases[0]
        order = deepcopy(self.provider.orders[0])
        if self.before_guard:
            self.before_guard(order)
        if not authorization_guard(order, {'quote': case['quote']}):
            raise ValueError('guard_rejected')
        self.calls.append({'quote': quote_id, 'payload': payload, 'actor': actor, 'manual': manual, 'reviewed_note': reviewed_note})
        case['quote']['acceptedOrderId'] = order['id']
        case['quote']['paymentStatus'] = 'paid'
        case['payment'].update(paymentStatus='已付款', amountPaid=case['quote']['total'], paymentOrderNumber=order['orderNumber'])
        return {'result': {'state': 'matched_internal_only'}}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'cases.db'
        self.now = datetime.fromisoformat('2026-11-03T21:55:00+08:00').timestamp()
        self.case, self.raw, self.order = fixture()
        self.payment = Payments(self.case, self.order)
        self.group = {'group_id': GROUP, 'name': '派車用', 'active': 1, 'event_stamp': int(self.now * 1000) - 1000, 'verified_event_stamp': int(self.now * 1000) - 1000}
        self.sent, self.reads = [], []
        self.push_result = 'accepted'
        self.read_ok = True
        with self.connect() as c:
            c.executescript('CREATE TABLE cases(id TEXT PRIMARY KEY,status TEXT,user_id TEXT,data TEXT); CREATE TABLE pickup_outbox(case_id TEXT PRIMARY KEY,state TEXT);')
            c.execute('INSERT INTO cases VALUES(?,?,?,?)', (CASE, '已申請', MAX, json.dumps(self.raw['data'])))
        self.server = {'connect': self.connect, 'PICKUP_NOTIFICATION_LOCK': threading.Lock(),
                       'selected_pickup_group': lambda c: self.group, 'active_pickup_group': lambda g: bool(g and g['active'] and g['event_stamp'] == g['verified_event_stamp']),
                       'pickup_notification_available': lambda: True, 'pickup_eligible': lambda row: self.payment.detail(row['id'])['releaseAllowed']}
        self.r = review.PickupPaymentReview(self.server, self.payment, clock=lambda: self.now, sender=self.send, reader=self.read)
        self.r.init()
        self.r.configure(True, [MAX])

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def send(self, group, messages, key):
        _group_messages_bytes(group, messages)
        self.sent.append((group, deepcopy(messages), key))
        if self.push_result == 'accepted':
            return {'state': 'accepted', 'httpStatus': 200, 'retryKey': key}
        return {'state': 'failed', 'retryable': True}

    def read(self, ids):
        self.reads.append(ids)
        if not self.read_ok:
            return {'state': 'failed'}
        return {'state': 'synced', 'cases': [{'caseId': CASE, 'name': self.raw['data']['name'], 'phone': '0912-345678',
                'address': self.raw['data']['pickupAddress'], 'model': 'AS11', 'status': '', 'date': '2026/11/01'}]}

    def scan(self):
        self.r.scan_now()
        self.r.scan_once()
        with self.connect() as c:
            return dict(c.execute('SELECT * FROM pickup_review_candidates ORDER BY created DESC LIMIT 1').fetchone())

    def event(self, job, action='approve', user=MAX, ident='event-1'):
        return {'type': 'postback', 'webhookEventId': ident, 'timestamp': int(self.now * 1000),
                'source': {'type': 'group', 'groupId': GROUP, 'userId': user},
                'postback': {'data': 'ppr1:' + action + ':' + job['id']}}

    def state(self, job):
        with self.connect() as c:
            return dict(c.execute('SELECT * FROM pickup_review_candidates WHERE id=?', (job['id'],)).fetchone())

    def approve(self):
        job = self.scan()
        self.r.enqueue(self.event(job))
        self.r.approval_once()
        self.now += 4
        self.r.approval_once()
        return job

    def ready(self):
        self.payment.cases[0]['releaseAllowed'] = True
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO pickup_outbox VALUES(?,?)', (CASE, 'synced'))
        self.now += 130

    def test_daily_2200_once_and_no_catchup_on_enable(self):
        self.assertFalse(self.r.schedule_once())
        self.now = datetime.fromisoformat('2026-11-03T22:00:00+08:00').timestamp()
        self.assertTrue(self.r.schedule_once())
        self.assertFalse(self.r.schedule_once())
        self.assertEqual(self.r.status()['nextRunAt'], '2026-11-04T22:00:00+08:00')
        self.now += 86400
        self.assertTrue(self.r.schedule_once())

    def test_after_2200_enable_next_run_tomorrow(self):
        self.now = datetime.fromisoformat('2026-11-03T23:10:00+08:00').timestamp()
        self.r.configure(False, [MAX])
        self.r.configure(True, [MAX])
        self.assertFalse(self.r.schedule_once())
        self.assertEqual(self.r.status()['nextRunAt'], '2026-11-04T22:00:00+08:00')

    def test_scan_only_card_no_mutation_and_unchanged_quiet(self):
        job = self.scan()
        self.assertEqual(self.payment.calls, [])
        self.assertEqual(self.state(job)['state'], 'pending')
        self.r.push_once()
        self.assertEqual(len(self.sent), 1)
        msg = json.dumps(self.sent[0][1], ensure_ascii=False)
        self.assertIn('同意派車', msg)
        self.assertIn('不同意派車', msg)
        self.assertNotIn(MAX, msg)
        self.assertNotIn('0912345678', msg)
        self.assertNotIn('WQ-', msg)
        self.scan()
        self.r.push_once()
        self.assertEqual(len(self.sent), 1)

    def test_free_text_note_has_explicit_approval_and_whole_note(self):
        self.order['orderRemarks'] = '取件地址：捷比達公司'
        job = self.scan()
        item = json.loads(job['payload'])
        self.assertTrue(item['approveSafe'])
        self.assertTrue(item['reviewedNoteRequired'])
        self.assertFalse(item['manualRequired'])
        self.assertEqual(self.payment.calls, [])
        self.r.push_once()
        card = self.sent[0][1][0]['contents']
        self.assertEqual([b['action']['label'] for b in card['footer']['contents']], ['同意派車', '不同意派車'])
        self.assertIn(self.order['orderRemarks'], json.dumps(card, ensure_ascii=False))
        self.r.enqueue(self.event(job))
        self.r.approval_once()
        self.now += 4
        self.r.approval_once()
        self.assertEqual(len(self.payment.calls), 1)
        self.assertTrue(self.payment.calls[0]['reviewed_note'])
        self.assertEqual(self.state(job)['state'], 'syncing')
        self.ready()
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'completed')

    def test_free_text_note_still_requires_designated_approver(self):
        self.order['orderRemarks'] = '取件地址：捷比達公司'
        job = self.scan()
        self.r.enqueue(self.event(job, user=OTHER))
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'pending')
        self.assertEqual(self.payment.calls, [])

    def test_note_changed_after_approval_is_blocked(self):
        self.order['orderRemarks'] = '取件地址：捷比達公司'
        job = self.scan()
        self.r.enqueue(self.event(job))
        self.order['orderRemarks'] = '更換取件地點'
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'blocked')
        self.assertEqual(self.payment.calls, [])

    def test_reject_never_reconciles_and_does_not_repeat_next_night(self):
        job = self.scan()
        self.r.enqueue(self.event(job, 'reject'))
        self.r.approval_once()
        self.assertEqual(self.payment.calls, [])
        self.assertEqual(self.state(job)['state'], 'rejected')
        self.now += 86400
        self.scan()
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM pickup_review_candidates').fetchone()[0], 1)

    def test_other_member_cannot_approve(self):
        job = self.scan()
        self.r.enqueue(self.event(job, user=OTHER))
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'pending')
        self.assertEqual(self.payment.calls, [])

    def test_other_group_and_old_event_ignored(self):
        job = self.scan()
        event = self.event(job)
        event['source']['groupId'] = 'C' + 'b' * 32
        self.r.enqueue(event)
        event = self.event(job, ident='old')
        event['timestamp'] -= 700000
        self.r.enqueue(event)
        self.assertEqual(self.state(job)['state'], 'pending')

    def test_webhook_duplicate_and_double_click_only_once(self):
        job = self.scan()
        event = self.event(job)
        self.r.enqueue(event)
        self.r.enqueue(event)
        self.r.enqueue(self.event(job, ident='double'))
        self.r.approval_once()
        self.now += 4
        self.r.approval_once()
        self.assertEqual(len(self.payment.calls), 1)

    def test_success_waits_actual_sheet_readback(self):
        job = self.approve()
        self.assertEqual(len(self.payment.calls), 1)
        self.assertEqual(self.state(job)['state'], 'syncing')
        self.assertTrue(self.payment.calls[0]['manual'])
        self.assertEqual(self.payment.calls[0]['payload']['confirm'], True)
        self.now += 10
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'syncing')
        self.ready()
        self.read_ok = False
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'syncing')
        self.read_ok = True
        self.now += 40
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'completed')
        with self.connect() as c:
            msg = c.execute("SELECT messages FROM pickup_review_push WHERE kind='completed'").fetchone()[0]
        self.assertIn('未派車', msg)
        self.assertEqual(self.reads[-1], [CASE])

    def test_refund_before_approval_blocks(self):
        job = self.scan()
        self.r.enqueue(self.event(job))
        self.payment.provider.orders[0]['reportedPaymentStatus'] = 'refunding'
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'blocked')
        self.assertEqual(self.payment.calls, [])

    def test_quote_changed_before_approval_blocks(self):
        job = self.scan()
        self.r.enqueue(self.event(job))
        self.payment.cases[0]['quote']['version'] = 2
        self.payment.cases[0]['payment']['quoteVersion'] = 2
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'blocked')
        self.assertEqual(self.payment.calls, [])

    def test_permission_change_after_fresh_scan_cancels(self):
        job = self.scan()
        self.r.enqueue(self.event(job))
        self.r.approval_once()
        self.r.configure(True, [OTHER])
        self.now += 4
        self.r.approval_once()
        self.assertEqual(self.payment.calls, [])
        self.assertEqual(self.state(job)['state'], 'cancelled')

    def test_guard_rechecks_order_after_provider_lookup(self):
        job = self.scan()
        self.r.enqueue(self.event(job))
        self.r.approval_once()
        self.payment.before_guard = lambda order: order.update(customerPhone='0999999999')
        self.now += 4
        self.r.approval_once()
        self.assertEqual(self.payment.calls, [])
        self.assertEqual(self.state(job)['state'], 'validated')

    def test_guard_rechecks_group_during_provider_lookup(self):
        job = self.scan()
        self.r.enqueue(self.event(job))
        self.r.approval_once()
        self.payment.before_guard = lambda order: self.group.update(active=0)
        self.now += 4
        self.r.approval_once()
        self.assertEqual(self.payment.calls, [])

    def test_phone_mismatch_and_ambiguity_have_no_approve_button(self):
        self.payment.provider.orders[0]['customerPhone'] = '0999999999'
        job = self.scan()
        self.r.push_once()
        actions = self.sent[0][1][0]['contents']['footer']['contents']
        self.assertEqual([a['action']['label'] for a in actions], ['不同意派車'])
        self.r.enqueue(self.event(job))
        self.assertEqual(self.state(job)['state'], 'pending')

    def test_ambiguous_orders_no_approve(self):
        duplicate = deepcopy(self.order)
        duplicate['id'], duplicate['orderNumber'] = 'b' * 24, '20261103000000001'
        self.payment.provider.orders.append(duplicate)
        self.scan()
        with self.connect() as c:
            rows = c.execute('SELECT payload FROM pickup_review_candidates').fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not json.loads(r['payload'])['approveSafe'] for r in rows))

    def test_complete_valid_remark_stays_existing_auto_flow(self):
        self.payment.provider.orders[0]['orderRemarks'] = '送修編號：' + CASE + '\n申請人姓名：測試客戶'
        self.r.scan_now()
        self.r.scan_once()
        self.r.push_once()
        self.assertEqual(self.payment.calls, [])
        self.assertEqual(self.sent, [])
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM pickup_review_candidates').fetchone()[0], 0)

    def test_annotated_order_still_counts_for_ambiguity(self):
        annotated = deepcopy(self.order)
        annotated.update(id='b' * 24, orderNumber='20261103000000001', orderRemarks='送修編號：' + CASE + '\n申請人姓名：測試客戶')
        rows = review.candidates([self.case], [self.raw], [self.order, annotated])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['orderNumber'], self.order['orderNumber'])
        self.assertFalse(rows[0]['approveSafe'])

    def test_mixed_or_refunded_or_unpaid_orders_never_candidate(self):
        for field, value in [('total', 2051), ('productValid', False), ('reviewReasons', ['mixed_cart']),
                             ('reportedPaymentStatus', 'pending'), ('reportedPaymentStatus', 'refunding')]:
            order = deepcopy(self.order)
            order[field] = value
            self.assertEqual(review.candidates([self.case], [self.raw], [order]), [])

    def test_changed_candidate_new_card_old_expires(self):
        old = self.scan()
        self.payment.provider.orders[0]['customerPhone'] = '0912-345678'
        self.now += 10
        new = self.scan()
        self.assertNotEqual(old['id'], new['id'])
        self.assertEqual(self.state(old)['state'], 'expired')
        self.r.enqueue(self.event(old))
        self.assertEqual(self.payment.calls, [])

    def test_scan_incomplete_not_reported_as_zero(self):
        self.payment.provider.truncated = True
        self.r.scan_now()
        for _ in range(6):
            self.r.scan_once()
            self.now += 61
        status = self.r.status()
        self.assertEqual(status['lastScan']['state'], 'failed')
        self.assertEqual(status['lastScan']['error'], 'scan_incomplete')
        with self.connect() as c:
            message = c.execute('SELECT messages FROM pickup_review_push').fetchone()[0]
        self.assertIn('不能判定沒有', message)

    def test_push_retry_reuses_uuid(self):
        self.scan()
        self.push_result = 'failed'
        self.r.push_once()
        self.now += 31
        self.push_result = 'accepted'
        self.r.push_once()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0][2], self.sent[1][2])

    def test_completion_push_suppressed_after_refund(self):
        job = self.approve()
        self.ready()
        self.r.approval_once()
        self.assertEqual(self.state(job)['state'], 'completed')
        self.payment.cases[0]['payment']['paymentStatus'] = '已退款'
        self.payment.cases[0]['releaseAllowed'] = False
        for _ in range(5):
            self.r.push_once()
        self.assertFalse(any('【派車審核已完成】' in json.dumps(m, ensure_ascii=False) for _, m, _ in self.sent))
        with self.connect() as c:
            row = c.execute("SELECT state FROM pickup_review_push WHERE kind='completed'").fetchone()
        self.assertEqual(row['state'], 'cancelled')

    def test_text_command_only_unique_candidate(self):
        job = self.scan()
        event = self.event(job)
        event.update(type='message', message={'type': 'text', 'text': '同意派車 ' + CASE})
        del event['postback']
        self.r.enqueue(event)
        self.assertEqual(self.state(job)['state'], 'approved')

    def test_status_redacts_sensitive_fields(self):
        self.scan()
        value = json.dumps(self.r.status(), ensure_ascii=False)
        for secret in (MAX, GROUP, '0912345678', '測試取件地址', 'WQ-', 'sourceHash', 'orderHash'):
            self.assertNotIn(secret, value)


if __name__ == '__main__':
    unittest.main()
