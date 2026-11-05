"""Offline real-case bridge tests. No credentials, network or live DB used."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from production_payments import ProductionPayments, WORKFLOW


class Sender:
    def __init__(self): self.sent = []
    def status(self): return {'configured': True}
    def _send(self, payload, request):
        self.sent.append((payload, request))
        return {'state': 'accepted', 'code': 'accepted'}
    send = send_receipt = send_refund_notice = _send


class Sheet:
    def wake(self): pass
    def stop(self): pass
    def status(self): return {'enabled': True}


class Provider:
    def __init__(self): self.order = None; self.reads = 0
    def exact(self, number):
        self.reads += 1
        if not self.order or self.order['orderNumber'] != number: raise ValueError('missing')
        return copy.deepcopy(self.order)
    def fetch(self, filters): return {'status': 'ok', 'truncated': False, 'orders': []}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.repair_path = self.directory / 'repairs.db'
        with self.repair_connect() as c:
            c.execute('CREATE TABLE cases(id TEXT PRIMARY KEY,user_id TEXT,data TEXT,created TEXT,status TEXT,line_display_name TEXT)')
        self.sender, self.provider = Sender(), Provider()
        self.promoted, self.held = [], []
        self.server = {'DATA_DIR': self.directory, 'ROOT': ROOT, 'TOKEN': '',
            'BASE': 'https://ad-creative-platform.onrender.com', 'connect': self.repair_connect,
            'promote_payment_case': self.promoted.append, 'hold_payment_case': self.held.append}
        self.runtime = ProductionPayments(self.server, {'shoplineApiToken': 'fake'},
            sender=self.sender, provider=self.provider, sheet=Sheet(), start_workers=False)
        self.case_id = 'R20261015-0080'
        self.add_case(self.case_id)

    def tearDown(self): self.runtime.stop(); self.temp.cleanup()

    @contextmanager
    def repair_connect(self):
        c = sqlite3.connect(self.repair_path)
        c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally: c.close()

    def add_case(self, number, managed=True, pickup=False, user=None):
        data = {'name': '客服測試', 'phone': '0900000009', 'model': 'AS11',
            'shipping': '由客服派遣物流回收' if pickup else '自行寄送',
            'pickupAddress': '測試地址', 'returnAddress': '測試地址', 'order': ''}
        if managed: data['paymentWorkflow'] = WORKFLOW
        with self.repair_connect() as c:
            c.execute('INSERT INTO cases VALUES(?,?,?,?,?,?)',
                (number, user or 'U'+'1'*32, json.dumps(data), '2026-10-15 00:00:00', '已申請', '測試用戶'))

    def quote(self, case_id=None, total=1):
        wb = self.runtime.enroll(case_id or self.case_id)
        wrapper = self.runtime.desk.approve_quote(wb, {'requestId':str(uuid.uuid4()),
            'repairFee':total, 'warranty':total == 0, 'expectedVersion':0})
        self.runtime.after_payment(wrapper['quote']['id'])
        return wrapper

    def order(self, wrapper, **fields):
        q, c = wrapper['quote'], wrapper['case']
        date = datetime.fromisoformat(q['createdAt']).replace(tzinfo=timezone(timedelta(hours=8))) + timedelta(seconds=1)
        result = {'id':uuid.uuid4().hex[:24], 'orderNumber':'TEST-'+uuid.uuid4().hex[:16],
            'customerName':c['name'],'recipientName':c['name'],'customerPhone':c['phone'],'recipientPhone':c['phone'],
            'orderRemarks':q['remarkText'], 'currency':'TWD','total':q['total'],'productValid':True,
            'reportedPaymentStatus':'completed','reportedPaidAt':date.isoformat(), 'createdAt':date.isoformat(),
            'paymentVerified':False,'verificationStatus':'not_verified','reviewReasons':[]}
        result.update(fields)
        self.provider.order = result
        return result

    def reconcile(self, wrapper, manual=False, **fields):
        self.order(wrapper, **fields)
        payload = {'orderNumber':self.provider.order['orderNumber'],'requestId':str(uuid.uuid4())}
        if manual: payload.update(confirm=True,reason='已向客戶確認案件及本次測試付款資料')
        return self.runtime.reconcile(wrapper['quote']['id'], payload, '測試客服', manual)

    def ack(self, wrapper):
        wb = wrapper['case']['id']
        row = self.runtime.sync.enqueue(wb)['row']
        self.runtime.sync.ack(wb,row['syncRevision'], {'ok':True,'caseId':self.case_id,
            'revision':row['syncRevision'],'status':row['paymentStatus'],'action':'updated'})

    def post_quote(self, payload, case_id=None):
        class Handler:
            headers = {'Origin': 'https://ad-creative-platform.onrender.com'}
            def send(self, status, body):
                self.response = status, body
        handler = Handler()
        self.assertTrue(self.runtime.handle_post(handler,
            '/api/payments/cases/' + (case_id or self.case_id) + '/quote', payload,
            {'admin': True, 'displayName': '測試客服'}))
        return handler.response


from unittest.mock import patch
import payment_sheet_sync as projection
from shopline_orders import PRODUCT_ID

class BackendImprovementsTests(Fixture):
    def make_mixed(self):
        wrapper=self.quote(total=500)
        allocation={'schema':'repair-allocation-v1','productId':PRODUCT_ID,'quantity':500,'unitPrice':1,
            'repairAmount':500,'otherAmount':120,'orderTotal':620,'paymentTotal':620,'fingerprint':'a'*64}
        self.order(wrapper,total=620,productValid=False,reviewReasons=['mixed_cart','order_total_mismatch'],repairAllocation=allocation)
        return wrapper
    def counts(self):
        with self.runtime.connect() as c:
            return tuple(c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['wb_real_order_checks','wb_real_manual_approvals','wb_quotes'])
    def preview(self,wrapper,actor='admin'):
        return self.runtime.mixed_preview(wrapper['quote']['id'],{'orderNumber':self.provider.order['orderNumber']},actor)
    def confirmation(self,preview):
        return {'orderNumber':preview['orderNumber'],'requestId':str(uuid.uuid4()),'confirm':True,
                'reason':'已核對維修費分攤金額及其他商品金額','previewToken':preview['previewToken']}
    def test_list_never_calculates_details_or_history(self):
        self.quote()
        with patch.object(self.runtime,'detail',side_effect=AssertionError('full detail forbidden')),patch.object(self.runtime.sync,'preview',side_effect=AssertionError('projection forbidden')):
            state=self.runtime.list_state()
        self.assertEqual(len(state['cases']),1)
        self.assertEqual(state['cases'][0]['payment']['paymentStatus'],'待付款')
        self.assertNotIn('releaseAllowed',state['cases'][0])
        self.assertNotIn('audit',state['cases'][0])
    def test_phone_search_accepts_dashes_spaces_and_country_code(self):
        with self.repair_connect() as c:
            row=c.execute('SELECT data FROM cases WHERE id=?',(self.case_id,)).fetchone()
            data=json.loads(row[0]);data['phone']='0900-000009'
            c.execute('UPDATE cases SET data=? WHERE id=?',(json.dumps(data),self.case_id))
        for query in ['0900000009','0900-000009','+886 900 000009','886900000009','900000009']:
            with self.subTest(query=query):
                self.assertEqual(len(self.runtime.list_state(query)['cases']),1)
                self.assertEqual(len(self.runtime.state(query)['cases']),1)
        self.assertEqual(self.runtime.list_state('0911111111')['cases'],[])
    def test_list_invalidates_old_quote_version(self):
        wrapper=self.quote()
        with self.runtime.connect() as c:
            c.execute('UPDATE wb_cases SET version=version+1 WHERE id=?',(wrapper['case']['id'],))
        self.assertEqual(self.runtime.list_state()['cases'][0]['payment']['paymentStatus'],'狀態更新中')
    def large_history(self):
        wrapper=self.quote()
        self.reconcile(wrapper,manual=True,orderRemarks='')
        with self.runtime.connect() as c:
            row=dict(c.execute('SELECT * FROM wb_real_order_checks').fetchone())
            response=json.loads(row['response']);response['result'].update(state='duplicate',code='already_matched_internal_only')
            rows=[(str(uuid.uuid4()),str(uuid.uuid4()),row['payload_hash'],row['order_id'],row['order_number'],row['quote_id'],row['case_id'],row['quote_version'],'duplicate',json.dumps(response),row['created_at']) for _ in range(12000)]
            c.executemany('INSERT INTO wb_real_order_checks VALUES(?,?,?,?,?,?,?,?,?,?,?)',rows)
        return wrapper
    def assert_old_projection_equal(self,wrapper):
        fast=self.runtime.sync.preview(wrapper['case']['id'])
        original=projection.PaymentSheetSync._checks
        def full(c,case,quote,due=None):return original(c,case,quote)
        with patch.object(projection.PaymentSheetSync,'_checks',staticmethod(full)):
            complete=self.runtime.sync.preview(wrapper['case']['id'])
        self.assertEqual(fast,complete)
        return fast
    def test_large_paid_history_reads_constant_prefix_and_keeps_all_records(self):
        wrapper=self.large_history();before=self.counts()
        original=projection._object
        with patch.object(projection,'_object',wraps=original) as parse:
            row=self.runtime.sync.preview(wrapper['case']['id'])['rows'][0]
        self.assertEqual(row['paymentStatus'],'已付款');self.assertLess(parse.call_count,20)
        self.assert_old_projection_equal(wrapper);self.assertEqual(self.counts(),before);self.assertEqual(before[0],12001)
    def test_new_refund_and_unrelated_bad_order_preserve_old_projection(self):
        wrapper=self.large_history()
        self.provider.order['reportedPaymentStatus']='refunding'
        self.runtime.reconcile(wrapper['quote']['id'],{'orderNumber':self.provider.order['orderNumber'],'requestId':str(uuid.uuid4())})
        fast=self.assert_old_projection_equal(wrapper)
        self.assertEqual(fast['rows'][0]['paymentStatus'],'已退款')
        self.assertFalse(self.runtime.detail(self.case_id)['releaseAllowed'])
    def test_preview_reads_provider_without_record_or_notification(self):
        wrapper=self.make_mixed();before=self.counts();sent=len(self.sender.sent)
        result=self.preview(wrapper)
        self.assertTrue(result['eligible']);self.assertEqual((result['repairAmount'],result['otherAmount'],result['orderTotal']),(500,120,620))
        self.assertEqual(self.counts(),before);self.assertEqual(len(self.sender.sent),sent)
    def test_mixed_confirmation_refreshes_order_and_requires_sheet_ack(self):
        wrapper=self.make_mixed();preview=self.preview(wrapper);reads=self.provider.reads
        result=self.runtime.confirm_mixed(wrapper['quote']['id'],self.confirmation(preview),'admin')
        self.assertEqual(self.provider.reads,reads+1);self.assertEqual(result['payment']['amountPaid'],500)
        self.assertFalse(self.runtime.detail(self.case_id)['releaseAllowed'])
        self.ack(wrapper);self.assertTrue(self.runtime.detail(self.case_id)['releaseAllowed'])
    def test_changed_order_cannot_reuse_preview(self):
        wrapper=self.make_mixed();preview=self.preview(wrapper);before=self.counts()
        self.provider.order['repairAllocation']['fingerprint']='b'*64
        with self.assertRaises(ValueError):self.runtime.confirm_mixed(wrapper['quote']['id'],self.confirmation(preview),'admin')
        self.assertEqual(self.counts(),before)
    def test_preview_bound_to_actor_case_version_and_expiry(self):
        wrapper=self.make_mixed();preview=self.preview(wrapper);before=self.counts()
        with self.assertRaises(ValueError):self.runtime.confirm_mixed(wrapper['quote']['id'],self.confirmation(preview),'other-admin')
        import time
        with patch('production_payments.time.time',return_value=time.time()+301):
            with self.assertRaises(ValueError):self.runtime.confirm_mixed(wrapper['quote']['id'],self.confirmation(preview),'admin')
        self.assertEqual(self.counts(),before)
    def test_mismatched_identity_or_amount_never_becomes_eligible(self):
        wrapper=self.make_mixed()
        for field,value in [('reportedPaymentStatus','refunding'),('customerName','Another'),('orderRemarks',''),('customerPhone','0911111111')]:
            original=copy.deepcopy(self.provider.order);self.provider.order[field]=value
            if field=='customerName':self.provider.order['recipientName']=value
            if field=='customerPhone':self.provider.order['recipientPhone']=value
            with self.subTest(field=field):self.assertFalse(self.preview(wrapper)['eligible'])
            self.provider.order=original
        self.assertEqual(self.counts()[0],0)
    def test_http_preview_and_confirmation_respect_admin_and_origin(self):
        wrapper=self.make_mixed();base='/api/payments/quotes/'+wrapper['quote']['id']
        class Handler:
            headers={'Origin':'https://ad-creative-platform.onrender.com'}
            def send(self,status,body):self.response=(status,body)
            def user(self):return None
        h=Handler();self.runtime.handle_get(h,'/api/payments/list','');self.assertEqual(h.response[0],401)
        body={'orderNumber':self.provider.order['orderNumber']}
        self.runtime.handle_post(h,base+'/mixed-preview',body,None);self.assertEqual(h.response[0],403)
        h.headers={'Origin':'https://other.invalid'}
        self.runtime.handle_post(h,base+'/mixed-preview',body,{'admin':True});self.assertEqual(h.response[0],403)
        h.headers={'Origin':'https://ad-creative-platform.onrender.com'}
        self.runtime.handle_post(h,base+'/mixed-preview',body,{'admin':True,'id':'admin'})
        self.assertEqual(h.response[0],200);self.assertTrue(h.response[1]['eligible'])
        self.assertEqual(self.counts()[0],0)

if __name__=='__main__':unittest.main()
