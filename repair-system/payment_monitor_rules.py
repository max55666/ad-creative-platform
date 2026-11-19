from collections import Counter
from datetime import datetime,timedelta,timezone
import json,re
from order_matching import normalize_name,normalize_phone
TAIPEI = timezone(timedelta(hours=8))
PICKUP = '由客服派遣物流回收'
SHIPPING_METHODS = {PICKUP, '自行寄送', '親自送回'}
OPEN_CASE_STATES = {'已申請', '待收件', '待補資料', '待客戶確認報價', '已收件', '檢測中', '維修中', '待寄回'}
PENDING = {'待付款', '需人工核對'}


def timestamp(value, local=False):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=TAIPEI) if local else None
        return dt
    except (ValueError, TypeError, AttributeError):
        return None


def positive_int(value):
    return type(value) is int and value > 0


def used_orders(cases):
    numbers, identifiers = set(), set()
    for case in cases:
        payment = case.get('payment') or {}
        if payment.get('paymentOrderNumber'):
            numbers.add(payment['paymentOrderNumber'])
        for quote in [case.get('quote') or {}, *case.get('quoteHistory', [])]:
            if quote.get('acceptedOrderId'):
                identifiers.add(quote['acceptedOrderId'])
        for receipt in case.get('receipts', []) + case.get('refundNotices', []):
            if receipt.get('order_number'):
                numbers.add(receipt['order_number'])
    return numbers, identifiers


def find_candidates(cases, repair_cases, orders):
    repairs = {r['id']: r for r in repair_cases}
    numbers, identifiers = used_orders(cases)
    result = []
    eligible = 0
    for case in cases:
        repair = repairs.get(case.get('id'), {})
        data = repair.get('data') or {}
        if isinstance(data, str):
            data = json.loads(data)
        quote, payment = case.get('quote') or {}, case.get('payment') or {}
        name = normalize_name(case.get('name', ''))
        quote_time = timestamp(quote.get('createdAt'), local=True)
        if not (case.get('managed') is True and case.get('shipping') in SHIPPING_METHODS
                and repair.get('status') in OPEN_CASE_STATES and data.get('shipping') == case.get('shipping')
                and name and normalize_name(data.get('name','')) == name
                and quote.get('status') == 'active' and quote.get('paymentStatus') == 'awaiting_payment'
                and not quote.get('acceptedOrderId') and positive_int(quote.get('total'))
                and positive_int(quote.get('version'))
                and quote.get('currency') == 'TWD' and payment.get('paymentStatus') in PENDING
                and type(payment.get('amountDue')) is int and payment['amountDue'] == quote['total']
                and type(payment.get('quoteVersion')) is int and payment['quoteVersion'] == quote.get('version')
                and not payment.get('paymentOrderNumber') and quote_time):
            continue
        eligible += 1
        phone = normalize_phone(case.get('phone', ''))
        for order in orders:
            created = timestamp(order.get('createdAt'))
            if not (order.get('orderNumber') and order.get('id')
                    and order['orderNumber'] not in numbers and order['id'] not in identifiers
                    and order.get('reportedPaymentStatus') == 'completed'
                    and order.get('currency') == 'TWD' and order.get('productValid') is True
                    and order.get('reviewReasons') == [] and positive_int(order.get('total'))
                    and order['total'] == quote['total'] and created and created >= quote_time
                    and name in [normalize_name(order.get(k,'')) for k in ('customerName','recipientName')]):
                continue
            phone_matches = bool(phone) and any(phone == normalize_phone(order.get(k,'')) for k in ('customerPhone','recipientPhone'))
            remark = order.get('orderRemarks') or ''
            references = sorted(set(re.findall(r'R[0-9]{8}-[0-9]{4,8}', remark)))
            warnings = []
            if not phone_matches:
                warnings.append('聯絡電話未吻合或資料不足，須另行確認身分')
            if references and references != [case['id']]:
                warnings.append('訂單備註含不同案件編號，須確認用途')
            remark_names = [normalize_name(v) for v in re.findall(r'(?:申請人姓名|申請人)[：:]\s*([^\r\n]+)', remark)]
            if any(v and v != name for v in remark_names):
                warnings.append('訂單備註的申請人姓名與本案不同，須另行核實')
            result.append({'caseNumber':case['id'], 'name':case['name'],
                'shippingMethod':case['shipping'], 'requiresPickup':case['shipping'] == PICKUP,
                'quoteId':quote['id'], 'quoteVersion':quote['version'],
                'repairFee':quote.get('repairFee'), 'pickupFee':quote.get('pickupFee'),
                'amountDue':quote['total'], 'orderNumber':order['orderNumber'],
                'amountPaid':order['total'], 'providerPaymentStatus':'completed',
                'orderCreatedAt':created.astimezone(TAIPEI).isoformat(),
                'paidAt':timestamp(order.get('reportedPaidAt')).astimezone(TAIPEI).isoformat() if timestamp(order.get('reportedPaidAt')) else '',
                'nameMatches':True, 'phoneMatches':phone_matches,
                'remarkEmpty':not bool(remark.strip()), 'remarkCaseNumbers':references,
                'warnings':warnings, 'requiresHumanApproval':True})
    order_counts = Counter(c['orderNumber'] for c in result)
    case_counts = Counter(c['caseNumber'] for c in result)
    for candidate in result:
        if order_counts[candidate['orderNumber']] > 1:
            candidate['warnings'].append('同一付款訂單符合多筆案件，請勿重複使用')
        if case_counts[candidate['caseNumber']] > 1:
            candidate['warnings'].append('本案件符合多筆付款訂單，須確認正確訂單')
    return result, eligible

