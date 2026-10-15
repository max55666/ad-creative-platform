"""Taiwan address validation and mainland-only pickup rules.

The public address catalogue contains no runtime configuration or credentials.
Existing free-text addresses remain readable; only new submissions are validated.
"""
import json
import re
from functools import lru_cache
from pathlib import Path


PICKUP_SHIPPING = '由客服派遣物流回收'
OFFSHORE_PICKUP_ERROR = '客服物流回收服務僅限台灣本島；離島地區無配合物流，請選擇自行寄送，可使用郵局郵寄。'


def _key(value):
    return value.strip().replace('台', '臺')


@lru_cache(maxsize=1)
def public_address_data():
    """Read the immutable, versioned catalogue shipped alongside this module."""
    payload = json.loads(Path(__file__).with_name('address-data.json').read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or not isinstance(payload.get('cities'), list) or not payload['cities']:
        raise ValueError('地址選單資料尚未準備完成，請稍後再試')
    for city in payload['cities']:
        if (not isinstance(city, dict) or not isinstance(city.get('name'), str)
                or not isinstance(city.get('districts'), list) or not city['districts']
                or any(not isinstance(d, str) or not d for d in city['districts'])):
            raise ValueError('地址選單資料尚未準備完成，請稍後再試')
    if not isinstance(payload.get('offshore'), list):
        raise ValueError('地址選單資料尚未準備完成，請稍後再試')
    return payload


def _catalogue():
    return {_key(row['name']): row for row in public_address_data()['cities']}


def is_offshore(city, district=''):
    for rule in public_address_data()['offshore']:
        if _key(city) != _key(rule['city']):
            continue
        if rule['districts'] == '*' or _key(district) in {_key(d) for d in rule['districts']}:
            return True
    return False


def _legacy_location(address):
    """Recognize an anchored Taiwan city+district, never a substring in a street.

    Postal codes, whitespace and an optional Taiwan country prefix are tolerated.
    A city without its district is insufficient for mainland pickup approval.
    """
    text = re.sub(r'\s+', '', address).replace('台', '臺')
    text = re.sub(r'^[0-9０-９]{3,6}[-－]?', '', text)
    text = re.sub(r'^(?:中華民國)?(?:臺灣(?:省)?)?', '', text)
    text = re.sub(r'^[0-9０-９]{3,6}[-－]?', '', text)
    for city in sorted(_catalogue().values(), key=lambda item: len(item['name']), reverse=True):
        prefix = _key(city['name'])
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix):]
        for district in sorted(city['districts'], key=len, reverse=True):
            if rest.startswith(_key(district)):
                return city['name'], district
        return city['name'], ''
    # A legacy island township without its county is still definitely offshore.
    for rule in public_address_data()['offshore']:
        if rule['districts'] != '*':
            for district in rule['districts']:
                if text.startswith(_key(district)):
                    return rule['city'], district
    return '', ''


def _address(data, prefix, label):
    fields = [prefix + part for part in ('City', 'District', 'Street')]
    structured = any(field in data for field in fields)
    if structured:
        if any(not isinstance(data.get(field), str) or not data[field].strip() for field in fields):
            raise ValueError(f'請完整填寫{label}的縣市、鄉鎮市區與路名門牌')
        city = _catalogue().get(_key(data[fields[0]]))
        if not city:
            raise ValueError(f'請重新選擇{label}的縣市')
        districts = {_key(d): d for d in city['districts']}
        district = districts.get(_key(data[fields[1]]))
        if not district:
            raise ValueError(f'{label}的縣市與鄉鎮市區不符，請重新選擇')
        street = data[fields[2]].strip()
        address = city['name'] + district + street
        location = (city['name'], district)
        values = {fields[0]: city['name'], fields[1]: district, fields[2]: street}
    else:
        address = data.get(prefix + 'Address', '')
        if not isinstance(address, str) or not address.strip():
            raise ValueError(f'請填寫{label}')
        address = address.strip()
        location = _legacy_location(address)
        values = {}
    if len(address) > 1000:
        raise ValueError(f'{label}不可超過 1000 字')
    values[prefix + 'Address'] = address
    return values, location


def validate_case_addresses(data, shipping):
    """Return only trusted address fields, rejecting unsupported pickup locations."""
    result, return_location = _address(data, 'return', '寄回地址')
    if shipping != PICKUP_SHIPPING:
        result['pickupAddress'] = ''
        return result
    pickup, pickup_location = _address(data, 'pickup', '取件地址')
    for city, district in (return_location, pickup_location):
        if is_offshore(city, district):
            raise ValueError(OFFSHORE_PICKUP_ERROR)
    if any(not city or not district for city, district in (return_location, pickup_location)):
        raise ValueError('客服物流回收服務僅限台灣本島；請重新開啟表單，選擇寄回與取件地址的縣市、鄉鎮市區後再送出。')
    result.update(pickup)
    return result
