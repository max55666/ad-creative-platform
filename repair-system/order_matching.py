"""Pure, conservative order-to-quote suggestions; never authorize a binding.

No provider, database, network, payment verification, or side effects. Scores
describe exact evidence only. Caller-owned payment verification cannot be
inferred from an order's reported status, and even a high result stays manual.
"""
import re
import unicodedata


_UNKNOWN = {'unknown', 'null', 'none', 'n/a', '未提供', '不詳'}
_CITIES = ('台北市', '新北市', '桃園市', '台中市', '台南市', '高雄市',
           '基隆市', '新竹市', '嘉義市', '宜蘭縣', '新竹縣', '苗栗縣',
           '彰化縣', '南投縣', '雲林縣', '嘉義縣', '屏東縣', '台東縣',
           '花蓮縣', '澎湖縣', '金門縣', '連江縣')
_CITY = re.compile(r'^(?:' + '|'.join(_CITIES) + ')')
_UNPAID = {'unpaid', 'pending', 'awaiting_payment', '未付款', '待付款',
           'simulation_pending', 'simulation_review', 'simulation_failed',
           'simulation_cancelled'}
_PAID = {'paid', 'refunded', 'partially_refunded', 'simulation_verified',
         'simulation_refunded', '已付款', '已退款'}


def _text(value, maximum=500):
    if not isinstance(value, str) or len(value) > maximum:
        return ''
    value = unicodedata.normalize('NFKC', value)
    if any(unicodedata.category(char) == 'Cs' or ord(char) == 127
           or (ord(char) < 32 and not char.isspace()) for char in value):
        return ''
    value = ' '.join(value.split())
    return '' if value.casefold() in _UNKNOWN else value


def normalize_phone(value):
    value = re.sub(r'[\s-]', '', _text(value, 40))
    if re.fullmatch(r'\+8869[0-9]{8}', value):
        value = '0' + value[4:]
    elif re.fullmatch(r'8869[0-9]{8}', value):
        value = '0' + value[3:]
    return value if re.fullmatch(r'09[0-9]{8}', value) else ''


def normalize_name(value):
    # Keep internal word boundaries and case: no nickname or fuzzy identity.
    return _text(value, 200)


def _part(value):
    return re.sub(r'\s', '', _text(value)).replace('臺', '台')


def _address(value):
    country, postcode = '', ''
    if isinstance(value, dict):
        country = _text(value.get('countryCode'), 4).upper()
        city, district = _part(value.get('city')), _part(value.get('district'))
        if city and district.startswith(city):
            district = district[len(city):]
        prefix = city + district
        tail = []
        # SHOPLINE Taiwan uses address2 before address1. Remove only exact
        # leading administrative labels; never strip digits, doors or floors.
        for field in ('address2', 'address1'):
            part = _part(value.get(field))
            for label in (city, district):
                if label and part.startswith(label):
                    part = part[len(label):]
            tail.append(part)
        canonical = prefix + ''.join(tail)
        postcode = _text(value.get('postcode'), 10)
        if postcode and not re.fullmatch(r'[0-9]{3}(?:[0-9]{2,3})?', postcode):
            postcode = ''
        display = (postcode + ' ' if postcode else '') + canonical
    else:
        canonical = _part(value)
        display = _text(value)
        # A leading postal code is metadata only when followed by a recognized
        # city. This never removes a house number or a floor from the address.
        match = re.match(r'^([0-9]{3}(?:[0-9]{2,3})?)(?=(?:' + '|'.join(_CITIES) + '))', canonical)
        if match:
            postcode, canonical = match.group(1), canonical[len(match.group(1)):]
    city_match = _CITY.match(canonical)
    if city_match and not country:
        country = 'TW'
    remainder = canonical[city_match.end():] if city_match else ''
    # Matching two identical partial strings does not prove a complete address.
    district_match = re.match(r'^[^0-9]{1,8}?(?:區|鄉|鎮|市)', remainder)
    location = remainder[district_match.end():] if district_match else ''
    door = re.search(r'[0-9一二三四五六七八九十百千]+(?:[-之][0-9]+)?號', location)
    # A bare number immediately after the city/district still lacks a road,
    # lane, village or other delivery locality; it is not a full address.
    locality = bool(door and re.search(r'[\u3400-\u9fffA-Za-z]', location[:door.start()]))
    complete = bool(country == 'TW' and city_match and district_match
                    and locality)
    return {'canonical': canonical, 'display': display, 'country': country,
            'postcode': postcode, 'complete': complete}


def _money(value):
    return value if type(value) is int and 0 <= value <= 100000000 else None


def _add(items, message):
    if message not in items:
        items.append(message)


def rank_candidates(order, candidates):
    """Return bounded, explainable suggestions. Unknown values stay missing.

    Candidates may include inactive or already paid quotes: they remain low
    suggestions with a warning. More than one plausible identity is ambiguous
    regardless of a score difference. No result ever permits automatic bind.
    """
    if not isinstance(candidates, list) or len(candidates) > 1000:
        raise ValueError('候選案件數量或格式不正確')
    order = order if isinstance(order, dict) else {}
    names = [normalize_name(order.get(key)) for key in ('customerName', 'recipientName')]
    phones = [normalize_phone(order.get(key)) for key in ('customerPhone', 'recipientPhone')]
    invalid_phone = any(_text(order.get(key), 40) and not normalize_phone(order.get(key))
                        for key in ('customerPhone', 'recipientPhone'))
    names, phones = [value for value in names if value], [value for value in phones if value]
    address = _address(order.get('address'))
    amount, currency = _money(order.get('total')), _text(order.get('currency'), 3).upper()
    remark = _text(order.get('remarkCaseId'), 100)
    paid = _text(order.get('reportedPaymentStatus'), 40).casefold() in ('paid', 'completed')
    # An omitted product flag is for trusted internal fixtures whose caller
    # has already checked the designated product. An explicit value must be
    # exactly True; a provider's reported paid status is never verification.
    product_valid = order.get('productValid', True) is True
    verified = order.get('paymentVerified') is True and paid and product_valid and currency == 'TWD'
    conflict = []
    if len(set(names)) > 1:
        conflict.append('訂購人與收件人姓名不同')
    if len(set(phones)) > 1:
        conflict.append('訂購人與收件人電話不同')
    rows, seen, duplicate_ids = [], set(), False
    for position, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        quote_id, case_id = _text(candidate.get('quoteId'), 100), _text(candidate.get('caseId'), 100)
        if not case_id:
            continue
        identity_key = 'quote:' + quote_id if quote_id else 'case:' + case_id
        if identity_key in seen:
            duplicate_ids = True
            continue
        seen.add(identity_key)
        name, phone = normalize_name(candidate.get('name')), normalize_phone(candidate.get('phone'))
        target_address = _address(candidate.get('address'))
        target_amount = _money(candidate.get('total'))
        target_currency = _text(candidate.get('currency'), 3).upper()
        status = _text(candidate.get('status'), 40).casefold()
        payment_status = _text(candidate.get('paymentStatus'), 40).casefold()
        reviewable = status == 'active' and payment_status not in _PAID
        eligible = bool(quote_id and reviewable and payment_status in _UNPAID
                        and target_amount is not None and target_amount > 0)
        reasons, mismatches, missing = [], list(conflict), []
        if invalid_phone:
            missing.append('訂單電話格式無效')
        dimensions = []
        for label, source, target, weight in (('姓名', names, name, 20), ('電話', phones, phone, 35)):
            if not source:
                missing.append('訂單' + label)
            if not target:
                missing.append('案件' + label)
            match = bool(source and target and target in source)
            dimensions.append(match)
            if match:
                reasons.append(label + '相同')
            elif source and target:
                mismatches.append(label + '不同')
        if not address['complete']:
            missing.append('訂單完整地址')
        if not target_address['complete']:
            missing.append('案件完整地址')
        address_match = bool(address['complete'] and target_address['complete']
                             and address['canonical'] == target_address['canonical']
                             and address['country'] == target_address['country']
                             and (not address['postcode'] or not target_address['postcode']
                                  or address['postcode'] == target_address['postcode']))
        dimensions.append(address_match)
        if address_match:
            reasons.append('完整地址相同')
        elif address['complete'] and target_address['complete']:
            mismatches.append('完整地址不同')
        if amount is None:
            missing.append('訂單金額')
        if target_amount is None:
            missing.append('案件金額')
        if not currency:
            missing.append('訂單幣別')
        if not target_currency:
            missing.append('案件幣別')
        amount_match = bool(amount is not None and target_amount is not None and currency
                            and currency == target_currency and amount == target_amount)
        dimensions.append(amount_match)
        if amount_match:
            reasons.append('金額相同')
        elif amount is not None and target_amount is not None and amount != target_amount:
            mismatches.append('金額不同')
        if currency and target_currency and currency != target_currency:
            mismatches.append('幣別不同')
        if remark:
            if remark == case_id:
                reasons.append('案件編號相同')
            else:
                mismatches.append('付款備註指向其他案件')
        if not status:
            missing.append('案件有效狀態')
        elif status != 'active':
            mismatches.append('案件並非有效報價')
        if payment_status not in _UNPAID and payment_status not in _PAID:
            missing.append('案件付款狀態')
        elif payment_status in _PAID:
            mismatches.append('案件已有付款或退款紀錄')
        if not quote_id:
            missing.append('正式報價識別碼')
        if not verified:
            missing.append('可信金流付款驗證')
        if not product_valid:
            mismatches.append('指定維修商品未通過核對')
        if currency and currency != 'TWD':
            mismatches.append('僅支援新臺幣報價')
        if not paid:
            mismatches.append('訂單未顯示為已付款')
        score = sum(weight for weight, match in zip((20, 35, 30, 15), dimensions) if match)
        plausible = reviewable and (any(dimensions[:3]) or bool(remark and remark == case_id))
        rows.append({'quoteId': quote_id, 'caseId': case_id, 'name': _text(candidate.get('name'), 200),
                     'phone': _text(candidate.get('phone'), 40), 'address': target_address['display'],
                     'total': target_amount, 'score': score, 'reasons': reasons,
                     'mismatches': mismatches, 'missing': missing, 'level': 'low',
                     'autoBindAllowed': False, '_eligible': eligible,
                     '_reviewable': reviewable,
                     '_plausible': plausible, '_all': all(dimensions), '_position': position})
    identity_rows = [row for row in rows if row['_plausible']]
    unique = len(identity_rows) == 1 and not duplicate_ids
    ambiguous = len(identity_rows) > 1 or duplicate_ids
    for row in rows:
        if ambiguous and row['_plausible']:
            _add(row['reasons'], '有多筆案件符合姓名、電話或地址，需人工確認')
        if row['_all'] and row['_eligible'] and verified and unique and not row['mismatches'] and not row['missing']:
            row['level'] = 'high'
        elif row['_reviewable'] and (row['score'] >= 30 or row['_plausible'] and remark == row['caseId']):
            row['level'] = 'review'
    rows.sort(key=lambda row: (not row['_reviewable'], -row['score'], row['_position']))
    level = 'high' if any(row['level'] == 'high' for row in rows) else 'review' if any(row['level'] == 'review' for row in rows) else 'low'
    if ambiguous:
        reason = '多筆有效案件有相同姓名、電話或地址，分數差不能排除歧義；請人工核對。'
    elif level == 'high':
        reason = '姓名、電話、完整地址及金額唯一完全相符，且付款已驗證；仍須人工確認配對。'
    elif not product_valid:
        reason = '訂單商品尚未通過指定維修商品核對，不能認列付款；請人工確認。'
    elif currency and currency != 'TWD':
        reason = '訂單幣別不是新臺幣，不能認列本系統的維修付款。'
    elif not verified:
        reason = ('平台回報已付款，但付款尚未核實；相符資料僅供人工參考，不能認列已付款。'
                  if paid else '付款尚未取得可信金流驗證；相符資料僅供人工參考，不能認列已付款。')
    elif conflict:
        reason = '訂購人與收件人資料不一致，請人工核對付款人與案件關係。'
    elif level == 'review':
        reason = '部分資料相符，但仍有缺漏或矛盾，請人工核對。'
    else:
        reason = '缺少足以識別案件的完整相符資料，請補充資料後人工核對。'
    output = [{key: value for key, value in row.items() if not key.startswith('_')} for row in rows]
    return {'candidates': output, 'assessment': {'level': level, 'unique': unique,
            'reason': reason, 'autoBindAllowed': False}}
