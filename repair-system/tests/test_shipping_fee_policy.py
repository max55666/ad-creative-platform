"""Temporary databases, synthetic customers, blocked external network."""
from contextlib import contextmanager
from datetime import datetime
from email.message import Message
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shipping_policy import policy, application_time, application_pickup_fee, stored_pickup_fee, PICKUP
from service_desk import ServiceDesk
from payment_sheet_sync import PaymentSheetSync
from payment_sheet_transport import validate_payment

class FeePolicyTests(unittest.TestCase):
    def test_taipei_cutoff_and_utc_equivalence(self):
        for stamp, fee in [('2026-11-29 23:59:59',350), ('2026-11-30 00:00:00',700),
                           ('2026-11-29T15:59:59Z',350), ('2026-11-29T16:00:00Z',700)]:
            with self.subTest(stamp=stamp):
                self.assertEqual(application_pickup_fee(PICKUP, stamp), fee)
                for mode in ('自行寄送','親自送回'):
                    self.assertEqual(application_pickup_fee(mode, stamp), 0)

    def test_legacy_snapshots_stay_350_and_reject_forged_rates(self):
        self.assertEqual(stored_pickup_fee({'pickup':True}),350)
        for fee in (True, 0, 699, '700'):
            with self.assertRaises(ValueError): stored_pickup_fee({'pickup':True,'pickupFeeTwd':fee})

    def test_old_and_new_quotes_requotes_and_sheet_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            @contextmanager
            def connect():
                c=sqlite3.connect(str(Path(temp)/'offline.db'));c.row_factory=sqlite3.Row
                try:
                    with c: yield c
                finally:c.close()
            desk=ServiceDesk(connect,seed_examples=False);desk.init()
            sync=PaymentSheetSync(connect);sync.init()
            for i,(created,expected) in enumerate([('2026-11-29 23:59:59',350),('2026-11-30 00:00:00',700)]):
                with connect() as c:
                    ident=desk._insert_case(c,{'caseNumber':'R20261130-000'+str(i+1),'name':'離線測試',
                        'phone':'0912345678','address':'離線測試地址','model':'TEST','pickup':True,
                        'lineLinked':True,'lineName':'TEST','source':'snapshot',
                        'pickupFeeTwd':application_pickup_fee(PICKUP,created)})
                for version,fee in ((0,2000),(1,0)):
                    result=desk.approve_quote(ident,{'repairFee':fee,'warranty':fee==0,'expectedVersion':version,'requestId':str(uuid.uuid4())})
                    quote=result['quote']
                    self.assertEqual(quote['pickupFee'],expected)
                    self.assertEqual(quote['total'],fee+expected)
                    self.assertEqual(quote['paymentStatus'],'awaiting_payment')
                    sync.enqueue(ident)
                    projection=sync.preview(ident)['rows'][0]
                    self.assertEqual(projection['pickupFee'],expected)
                    self.assertEqual(projection['amountDue'],fee+expected)

class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();folder=Path(self.temp.name)
        (folder/'server.py').write_text((ROOT/'server.py').read_text(encoding='utf-8'),encoding='utf-8')
        (folder/'settings.json').write_text('{}')
        self.env=patch.dict(os.environ,{'REPAIR_MODE':'demo'},clear=True);self.env.start()
        spec=importlib.util.spec_from_file_location('shipping_offline_'+uuid.uuid4().hex,folder/'server.py')
        self.server=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.server)
        self.server.notify=Mock(return_value='offline')
        self.net=patch('urllib.request.urlopen',side_effect=AssertionError('No external network'));self.net.start()
    def tearDown(self):self.net.stop();self.env.stop();self.temp.cleanup()
    def submit(self,stamp,mode=PICKUP,payload=None):
        module=self.server
        body=payload or {'name':'離線測試','phone':'0912345678','model':'TEST','problem':'TEST','shipping':mode,
            'orderChoice':'missing','rules':[True]*4,'checks':[True]*4,'privacy':True,'requestId':str(uuid.uuid4()),
            'returnCity':'台北市','returnDistrict':'中正區','returnStreet':'中山南路1號',
            'pickupSameAsReturn':True,'shippingPolicyVersion':policy(stamp)['version'],'pickupFeeTwd':1}
        class Handler(module.Handler):
            def __init__(self):
                self.path='/api/cases';raw=json.dumps(body).encode();self.rfile=io.BytesIO(raw)
                self.headers=Message();self.headers['Content-Length']=str(len(raw));self.response=None
            def allowed_origin(self):return True
            def user(self):return {'id':'U'+'1'*32,'admin':False,'displayName':'TEST'}
            def send(self,code,value,headers=None):self.response=(code,value)
        h=Handler()
        with patch.object(module,'application_time',return_value=application_time(stamp)):h.do_POST()
        return h.response,body
    def test_submission_boundary_ignores_client_fee_and_keeps_old_retry(self):
        (code,old),payload=self.submit('2026-11-29 23:59:59')
        self.assertEqual(code,201);self.assertEqual(old['case']['data']['pickupFeeTwd'],350)
        (code,replay),_=self.submit('2026-11-30 00:00:00',payload=payload)
        self.assertEqual(code,200);self.assertEqual(replay['case']['id'],old['case']['id'])
        self.assertEqual(replay['case']['data']['pickupFeeTwd'],350)
        (code,new),_=self.submit('2026-11-30 00:00:00')
        self.assertEqual(code,201);self.assertEqual(new['case']['data']['pickupFeeTwd'],700)
    def test_stale_form_blocks_new_submission_without_creating_case(self):
        _,payload=self.submit('2026-11-29 23:59:59')
        payload['requestId']=str(uuid.uuid4())
        (code,result),_=self.submit('2026-11-30 00:00:00',payload=payload)
        self.assertEqual(code,409);self.assertEqual(result['code'],'SHIPPING_POLICY_CHANGED')
        with self.server.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM cases').fetchone()[0],1)
    def test_dropoff_new_terms_and_self_shipping_have_no_pickup_fee(self):
        for mode in ('親自送回','自行寄送'):
            (code,result),_=self.submit('2026-11-30 00:00:00',mode)
            self.assertEqual(code,201);self.assertIsNone(result['case']['data']['pickupFeeTwd'])
            if mode=='親自送回':self.assertIn('自行領回，不安排寄回',result['case']['data']['shippingNote'])

from test_backend_improvements import Fixture
from production_payment_sender import _ProductionHttpSender

class ProductionFeeBridgeTests(Fixture):
    def test_original_submission_controls_late_enrollment_quote_and_notice(self):
        for i,(stamp,fee) in enumerate([('2026-11-29 23:59:59',350),('2026-11-30 00:00:00',700)]):
            number='R20261130-008'+str(i)
            self.add_case(number,pickup=True)
            with self.repair_connect() as c:
                c.execute('UPDATE cases SET created=? WHERE id=?',(stamp,number))
            # Enrollment happens later; it must use the original application's date.
            with patch('shipping_policy.application_time',wraps=application_time) as clock:
                wb=self.runtime.enroll(number)
                self.assertTrue(any(call.args==(stamp,) for call in clock.call_args_list))
            status,result=self.post_quote({'repairFee':2000,'warranty':False,
                'expectedVersion':0,'requestId':str(uuid.uuid4())},number)
            self.assertEqual(status,200)
            saved=self.runtime.desk.get_case(wb)
            quote=saved['case']['latestQuote']
            self.assertEqual(quote['pickupFee'],fee)
            self.assertEqual(quote['total'],2000+fee)
            self.assertEqual(self.runtime.detail(number)['pickupFeeTwd'],fee)
            listed=next(c for c in self.runtime.list_state()['cases'] if c['id']==number)
            self.assertEqual(listed['pickupFeeTwd'],fee)
            notice=quote
            sender=_ProductionHttpSender(token_getter=lambda:'offline',user_id='U'+'1'*32,
                label='TEST',kind='notice',opener=Mock(side_effect=AssertionError('offline')),
                clock=lambda:0)
            _,payload=sender._payload(notice)
            message=payload['messages'][0]['contents']['body']['contents'][0]['text']
            self.assertIn('NT$'+format(2000+fee,','),message)
            self.assertIn('收送運費（收件350＋寄回350）' if fee==700 else '派車回收費',message)

if __name__=='__main__':unittest.main()
