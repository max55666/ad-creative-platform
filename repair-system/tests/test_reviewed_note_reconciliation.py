"""Explicit note-review tests; temporary databases, no network or live data."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service_desk import ServiceDesk
from service_desk_reconciliation import (
    RealOrderReconciliation, _missing_remark_exception, _remark, _reviewed_note_exception,
)
from payment_sheet_sync import PaymentSheetSync


def rid():
    return str(uuid.uuid4())


class ReviewedNoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'notes.db'
        self.desk = ServiceDesk(self.factory)
        self.desk.init()
        self.recon = RealOrderReconciliation(self.factory)
        self.recon.init()
        self.sync = PaymentSheetSync(self.factory)
        self.sync.init()
        self.case = self.desk.create_case({'requestId': rid(), 'name': '測試客戶',
            'phone': '0900000009', 'address': '測試地址', 'model': 'AS11',
            'pickup': True, 'lineLinked': True, 'lineName': '測試帳號',
            'source': 'snapshot', 'caseNumber': 'R20261106-9001'})['case']
        self.wrapper = self.desk.approve_quote(self.case['id'], {'requestId': rid(),
            'repairFee': 2500, 'warranty': False, 'expectedVersion': self.case['version']})
        created = datetime.fromisoformat(self.wrapper['quote']['createdAt']).replace(
            tzinfo=timezone(timedelta(hours=8))) + timedelta(seconds=1)
        self.order = {'id': 'a' * 24, 'orderNumber': '20261107123456789',
            'customerName': '測試客戶', 'recipientName': '測試客戶',
            'customerPhone': '0900000009', 'recipientPhone': '', 'address': {},
            'orderRemarks': '取件地址：測試公司', 'total': 2850, 'currency': 'TWD',
            'productValid': True, 'reviewReasons': [], 'reportedPaymentStatus': 'completed',
            'reportedPaidAt': created.isoformat(), 'createdAt': created.isoformat(),
            'paymentVerified': False, 'verificationStatus': 'not_verified'}
        self.provenance = {'freshProviderLookup': True, 'readOnly': True}

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def factory(self):
        c = sqlite3.connect(self.path)
        try:
            yield c
        finally:
            c.close()

    def approve(self, order=None, request=None, **kwargs):
        args = {'provenance': self.provenance, 'confirm': True,
                'reason': '指定審核者確認此備註僅為取件指示', 'actor': '測試審核人'}
        args.update(kwargs)
        return self.recon.record_manual_note(order or self.order, self.wrapper,
                                             request or rid(), **args)

    def refresh(self, order=None):
        return self.recon.record(order or self.order, self.wrapper, rid(), provenance=self.provenance)

    def projection(self):
        return self.sync.preview(self.case['id'])['rows'][0]

    def test_plain_instructions_are_explicit_reviewable_only(self):
        for note in ('取件地址：測試公司', '請下午到府取件', '請先按門鈴\n謝謝', '請下午取件\r\n謝謝'):
            self.assertTrue(_reviewed_note_exception(note, self.wrapper['case']))
            self.assertFalse(_missing_remark_exception(note, self.wrapper['case']))
            self.assertTrue(_remark(note)[2])
        self.assertEqual(self.refresh()['result']['state'], 'blocked')
        with self.assertRaises(ValueError):
            self.recon.record_manual(self.order, self.wrapper, rid(), provenance=self.provenance,
                confirm=True, reason='原漏填備註流程仍維持嚴格', actor='測試審核人')

    def test_identity_controls_and_long_notes_remain_blocked(self):
        case_id = self.case['caseNumber']
        for note in ('', '   ', '送修編號：'+case_id, '送修編號：R20261106-9999',
                     'R20261106-9999', 'Ｒ２０２６１１０６－９９９９', 'r 20261106-9999',
                     '申請人姓名：其他人', '姓名：測試客戶', '申請人:測試客戶',
                     '送修編號：\n送修編號：', 'customer name: Other', 'case id: other',
                     '電話：0900111222', '請\x00取件', '請\t取件', '請\r取件',
                     '請\u200b取件', '請\u202e取件', '字' * 501):
            with self.subTest(note=repr(note)):
                self.assertFalse(_reviewed_note_exception(note, self.wrapper['case']))
                with self.assertRaises(ValueError):
                    self.approve({**self.order, 'orderRemarks': note})
        self.assertFalse(_reviewed_note_exception('請取件', {'caseNumber': None, 'name': '測試客戶'}))

    def test_confirm_actor_reason_are_required(self):
        for kwargs in ({'confirm': False}, {'confirm': 1}, {'actor': ''}, {'actor': ' '},
                       {'reason': '短'}, {'reason': '     '}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.approve(**kwargs)

    def test_success_is_durable_audited_and_projects_paid(self):
        result = self.approve()
        self.assertEqual(result['result']['state'], 'matched_internal_only')
        facts = result['result']['facts']
        self.assertTrue(facts['manualNoteException'])
        self.assertTrue(facts['manualNoteCustomerNameMatches'])
        self.assertNotIn('manualRemarkException', facts)
        self.assertEqual(facts['manualNoteHash'], hashlib.sha256(self.order['orderRemarks'].encode()).hexdigest())
        self.assertEqual(self.projection()['paymentStatus'], '已付款')
        self.assertEqual(self.projection()['amountPaid'], 2850)
        with self.factory() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM wb_real_manual_approvals').fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM wb_audit WHERE action='real_order_manual_note_approved'").fetchone()[0], 1)

    def test_saved_note_refresh_and_repeat_approval_are_idempotent(self):
        request = rid()
        self.approve(request=request)
        self.assertTrue(self.approve(request=request)['idempotent'])
        self.assertEqual(self.approve()['result']['state'], 'duplicate')
        self.assertEqual(self.refresh()['result']['state'], 'duplicate')
        self.assertEqual(self.projection()['paymentStatus'], '已付款')
        with self.factory() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM wb_real_manual_approvals').fetchone()[0], 1)

    def test_changed_note_cannot_reuse_saved_approval(self):
        self.approve()
        for note in ('請改成上午取件', '', self.wrapper['quote']['remarkText'], '申請人：其他人'):
            with self.subTest(note=note):
                result = self.refresh({**self.order, 'orderRemarks': note})
                self.assertEqual(result['result']['state'], 'blocked')
                self.assertIn('conflicting_remark', result['result']['reasons'])
                self.assertEqual(self.projection()['paymentStatus'], '需人工核對')

    def test_all_money_time_phone_product_and_refund_guards_remain(self):
        for changes, reason in (({'total': 2849}, 'amount_mismatch'),
                ({'currency': 'USD'}, 'invalid_currency'),
                ({'productValid': False}, 'invalid_product'),
                ({'reviewReasons': ['mixed_cart']}, 'provider_review_required'),
                ({'reportedPaymentStatus': 'pending'}, 'not_completed'),
                ({'reportedPaymentStatus': 'refunding'}, 'refunded'),
                ({'reportedPaymentStatus': 'refunded'}, 'refunded'),
                ({'reportedPaymentStatus': 'partially_refunded'}, 'refunded'),
                ({'customerPhone': '0999999999'}, 'phone_mismatch'),
                ({'createdAt': '2020-01-01T00:00:00Z'}, 'order_predates_quote'),
                ({'customerName': '其他人', 'recipientName': '另一人'}, 'name_mismatch')):
            with self.subTest(changes=changes):
                result = self.approve({**self.order, **changes})
                self.assertEqual(result['result']['state'], 'blocked')
                self.assertIn(reason, result['result']['reasons'])
        with self.factory() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM wb_real_manual_approvals').fetchone()[0], 0)

    def test_saved_approval_name_change_blocks(self):
        self.approve()
        result = self.refresh({**self.order, 'customerName': '其他人', 'recipientName': '另一人'})
        self.assertEqual(result['result']['state'], 'blocked')
        self.assertIn('name_mismatch', result['result']['reasons'])
        self.assertEqual(self.projection()['paymentStatus'], '需人工核對')

    def test_refunding_refresh_overrides_paid_and_retains_refund_hold(self):
        self.approve()
        result = self.refresh({**self.order, 'reportedPaymentStatus': 'refunding'})
        self.assertEqual(result['result']['state'], 'blocked')
        self.assertIn('refunded', result['result']['reasons'])
        self.assertEqual(self.projection()['paymentStatus'], '已退款')
        self.assertEqual(self.recon.refund_followups()['followups'][0]['providerStatus'], 'refunding')
        self.refresh()
        self.assertEqual(self.projection()['paymentStatus'], '已退款')

    def test_changed_note_still_records_refund(self):
        self.approve()
        self.refresh({**self.order, 'reportedPaymentStatus': 'refunding', 'orderRemarks': '備註已異動'})
        self.assertEqual(self.projection()['paymentStatus'], '已退款')

    def test_projection_requires_ledger_and_matching_note_hash(self):
        self.approve()
        with self.factory() as c:
            original = c.execute('SELECT facts FROM wb_real_manual_approvals').fetchone()[0]
            facts = json.loads(original)
            facts['manualNoteHash'] = '0' * 64
            c.execute('UPDATE wb_real_manual_approvals SET facts=?', (json.dumps(facts),))
            c.commit()
        self.assertNotEqual(self.projection()['paymentStatus'], '已付款')
        with self.factory() as c:
            c.execute('UPDATE wb_real_manual_approvals SET facts=?', (original,))
            c.commit()
        self.assertEqual(self.projection()['paymentStatus'], '已付款')
        with self.factory() as c:
            c.execute('DELETE FROM wb_real_manual_approvals')
            c.commit()
        self.assertNotEqual(self.projection()['paymentStatus'], '已付款')

    def test_projection_rejects_false_customer_name_evidence(self):
        self.approve()
        with self.factory() as c:
            facts = json.loads(c.execute('SELECT facts FROM wb_real_manual_approvals').fetchone()[0])
            facts['manualNoteCustomerNameMatches'] = False
            c.execute('UPDATE wb_real_manual_approvals SET facts=?', (json.dumps(facts),))
            c.commit()
        self.assertNotEqual(self.projection()['paymentStatus'], '已付款')

    def test_note_ledger_cannot_be_reused_as_missing_label_approval(self):
        self.approve()
        with self.factory() as c:
            row = c.execute('SELECT id,response FROM wb_real_order_checks').fetchone()
            response = json.loads(row[1])
            facts = response['result']['facts']
            facts.pop('manualNoteException')
            facts['manualRemarkException'] = True
            c.execute('UPDATE wb_real_order_checks SET response=? WHERE id=?', (json.dumps(response), row[0]))
            c.commit()
        self.assertNotEqual(self.projection()['paymentStatus'], '已付款')

    def test_other_order_cannot_reuse_quote(self):
        self.approve()
        result = self.approve({**self.order, 'id': 'b' * 24, 'orderNumber': '20261107123456780'})
        self.assertEqual(result['result']['state'], 'blocked')
        self.assertIn('quote_already_bound', result['result']['reasons'])


if __name__ == '__main__':
    unittest.main()
