"""Pure/mocked tests: this suite never contacts production or SHOPLINE."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import payment_monitor_rules as monitor


def fixture(number='R20261022-0001'):
    case = {
        'id': number, 'name': '測試客戶', 'phone': '0912345678',
        'managed': True, 'shipping': monitor.PICKUP,
        'quote': {'id': 'quote-' + number, 'status': 'active',
                  'paymentStatus': 'awaiting_payment', 'acceptedOrderId': '',
                  'version': 1, 'currency': 'TWD', 'total': 2350,
                  'repairFee': 2000, 'pickupFee': 350,
                  'createdAt': '2026-10-26 17:10:51'},
        'payment': {'paymentStatus': '待付款', 'amountDue': 2350,
                    'quoteVersion': 1, 'paymentOrderNumber': ''},
        'quoteHistory': [], 'receipts': [], 'refundNotices': [],
    }
    repair = {'id': number, 'status': '已申請',
              'data': {'shipping': monitor.PICKUP, 'name': '測試客戶'}}
    order = {'id': 'a' * 24, 'orderNumber': '20261027000000001',
             'customerName': '測試客戶', 'recipientName': '測試客戶',
             'customerPhone': '+886912345678', 'recipientPhone': '',
             'reportedPaymentStatus': 'completed', 'currency': 'TWD',
             'productValid': True, 'reviewReasons': [], 'total': 2350,
             'createdAt': '2026-10-27T10:07:53+00:00',
             'reportedPaidAt': '2026-10-27T10:08:06+00:00', 'orderRemarks': ''}
    return case, repair, order


class CandidateTests(unittest.TestCase):
    def test_conflicting_remark_name_requires_extra_review(self):
        case, repair, order = fixture()
        order['orderRemarks'] = '申請人姓名：不同申請人'
        rows, _ = monitor.find_candidates([case], [repair], [order])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['requiresHumanApproval'])
        self.assertIn('訂單備註的申請人姓名與本案不同，須另行核實', rows[0]['warnings'])

    def test_paid_blank_remark_is_only_a_human_candidate(self):
        case, repair, order = fixture()
        before = deepcopy((case, repair, order))
        rows, eligible = monitor.find_candidates([case], [repair], [order])
        self.assertEqual(eligible, 1)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row['requiresHumanApproval'])
        self.assertTrue(row['remarkEmpty'])
        self.assertTrue(row['phoneMatches'])
        self.assertEqual(row['amountPaid'], 2350)
        self.assertEqual(row['warnings'], [])
        self.assertEqual(row['paidAt'], '2026-10-27T18:08:06+08:00')
        self.assertEqual((case, repair, order), before)
        serialized = json.dumps(rows)
        self.assertNotIn('0912345678', serialized)
        self.assertNotIn('886912345678', serialized)

    def test_nonpaying_refunded_wrong_product_or_currency_never_suggested(self):
        conditions = [
            ('reportedPaymentStatus', 'pending'),
            ('reportedPaymentStatus', 'failed'),
            ('reportedPaymentStatus', 'refunding'),
            ('reportedPaymentStatus', 'refunded'),
            ('reportedPaymentStatus', 'partially_refunded'),
            ('currency', 'USD'), ('productValid', False),
            ('reviewReasons', ['mixed_cart']), ('total', 2351),
            ('total', True), ('total', -2350), ('total', float('nan')),
        ]
        for field, value in conditions:
            with self.subTest(field=field, value=value):
                case, repair, order = fixture()
                order[field] = value
                self.assertEqual(monitor.find_candidates([case], [repair], [order])[0], [])

    def test_name_must_match_and_must_not_be_empty(self):
        for target in ('別位客戶', ''):
            case, repair, order = fixture()
            order['customerName'] = order['recipientName'] = target
            self.assertEqual(monitor.find_candidates([case], [repair], [order])[0], [])
        case, repair, order = fixture()
        case['name'] = repair['data']['name'] = ''
        order['customerName'] = order['recipientName'] = ''
        self.assertEqual(monitor.find_candidates([case], [repair], [order])[0], [])

    def test_order_time_cannot_precede_quote_or_omit_timezone(self):
        for date in ('2026-10-26T09:10:50+00:00', '2026-10-27 18:00:00', '', 'bad'):
            with self.subTest(date=date):
                case, repair, order = fixture()
                order['createdAt'] = date
                self.assertEqual(monitor.find_candidates([case], [repair], [order])[0], [])

    def test_inactive_cases_are_not_candidates(self):
        for status in ('已取消', '不維修退回', '已結案', '已寄回'):
            with self.subTest(status=status):
                case, repair, order = fixture()
                repair['status'] = status
                self.assertEqual(monitor.find_candidates([case], [repair], [order]), ([], 0))

    def test_all_shipping_methods_need_payment_confirmation(self):
        for shipping in ('自行寄送', '親自送回', monitor.PICKUP):
            for status in ('已申請', '已收件', '檢測中', '維修中'):
                with self.subTest(shipping=shipping, status=status):
                    case, repair, order = fixture()
                    case['shipping'] = repair['data']['shipping'] = shipping
                    repair['status'] = status
                    rows, eligible = monitor.find_candidates([case], [repair], [order])
                    self.assertEqual(eligible, 1)
                    self.assertEqual(rows[0]['shippingMethod'], shipping)
                    self.assertEqual(rows[0]['requiresPickup'], shipping == monitor.PICKUP)
                    self.assertTrue(rows[0]['requiresHumanApproval'])

    def test_shipping_mismatch_or_unknown_is_excluded(self):
        case, repair, order = fixture()
        case['shipping'] = '自行寄送'
        self.assertEqual(monitor.find_candidates([case], [repair], [order]), ([], 0))
        case['shipping'] = repair['data']['shipping'] = 'unknown'
        self.assertEqual(monitor.find_candidates([case], [repair], [order]), ([], 0))

    def test_case_payment_or_quote_must_still_be_pending_and_consistent(self):
        conditions = [
            ('payment', 'paymentStatus', '已付款'),
            ('payment', 'paymentStatus', '已退款'),
            ('payment', 'amountDue', 2349),
            ('payment', 'amountDue', True),
            ('payment', 'quoteVersion', 2),
            ('quote', 'status', 'superseded'),
            ('quote', 'paymentStatus', 'no_payment_required'),
            ('quote', 'total', 0), ('quote', 'acceptedOrderId', 'bound'),
        ]
        for group, field, value in conditions:
            with self.subTest(group=group, field=field):
                case, repair, order = fixture()
                case[group][field] = value
                self.assertEqual(monitor.find_candidates([case], [repair], [order])[0], [])

    def test_bound_order_on_another_case_or_old_quote_is_excluded(self):
        for location in ('payment', 'quoteHistory', 'receipts', 'refundNotices'):
            with self.subTest(location=location):
                case, repair, order = fixture()
                prior, prior_repair, _ = fixture('R20261020-0009')
                prior['payment']['paymentStatus'] = '已退款'
                if location == 'payment':
                    prior['payment']['paymentOrderNumber'] = order['orderNumber']
                elif location == 'quoteHistory':
                    prior['quoteHistory'] = [{'acceptedOrderId': order['id']}]
                else:
                    prior[location] = [{'order_number': order['orderNumber']}]
                rows, _ = monitor.find_candidates([case, prior], [repair, prior_repair], [order])
                self.assertEqual(rows, [])

    def test_one_order_multiple_cases_and_multiple_orders_warn(self):
        first, first_repair, order = fixture()
        second, second_repair, _ = fixture('R20261023-0002')
        rows, _ = monitor.find_candidates([first, second], [first_repair, second_repair], [order])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(any('多筆案件' in text for text in r['warnings']) for r in rows))
        other = deepcopy(order)
        other['id'], other['orderNumber'] = 'b' * 24, '20261027000000002'
        rows, _ = monitor.find_candidates([first], [first_repair], [order, other])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(any('多筆付款訂單' in text for text in r['warnings']) for r in rows))

    def test_empty_or_mismatched_phones_require_review_not_false_match(self):
        for case_phone, order_phone in (('', ''), ('0912345678', '0999999999')):
            case, repair, order = fixture()
            case['phone'] = case_phone
            order['customerPhone'] = order['recipientPhone'] = order_phone
            rows, _ = monitor.find_candidates([case], [repair], [order])
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]['phoneMatches'])
            self.assertTrue(any('電話' in warning for warning in rows[0]['warnings']))

    def test_another_case_in_remark_is_flagged(self):
        case, repair, order = fixture()
        order['orderRemarks'] = '送修編號：R20261020-0009'
        rows, _ = monitor.find_candidates([case], [repair], [order])
        self.assertEqual(rows[0]['remarkCaseNumbers'], ['R20261020-0009'])
        self.assertTrue(any('不同案件' in warning for warning in rows[0]['warnings']))

