"""Pure, bounded LINE dispatch cards. No network, storage, secrets or logging."""

import json
import re


GREEN = "#315e50"
BUTTON_COLOR = "#e4eee8"
_CASE_ID = re.compile(r"R[0-9]{8}-[0-9]{4,}\Z")
_SNAPSHOT = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")
_CASE_FIELDS = {"caseId", "name", "phone", "address", "model"}
_OPTIONAL_FIELDS = {"date", "status"}
_BUBBLE_BYTES = 30000
_CAROUSEL_BYTES = 50000


def _bad():
    raise ValueError("Dispatch card data is invalid or exceeds LINE limits")


def _units(text):
    try:
        return len(text.encode("utf-16-le")) // 2
    except (UnicodeError, AttributeError):
        _bad()


def _text_value(value, maximum=2000, nonempty=False):
    if (not isinstance(value, str) or _units(value) > maximum
            or nonempty and not value.strip()
            or any(ord(c) < 32 and c not in "\r\n\t" for c in value)):
        _bad()
    return value


def _integer(value, minimum=0, maximum=1000):
    if type(value) is not int or not minimum <= value <= maximum:
        _bad()
    return value


def _json_size(value):
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _bad()


def _text(text, size="sm", color="#17352d", weight="regular"):
    return {"type": "text", "text": text, "size": size,
            "color": color, "weight": weight, "wrap": True}


def _postback(label, data, display_text=None):
    _text_value(label, 40, True)
    _text_value(data, 300, True)
    action = {"type": "postback", "label": label, "data": data,
              "displayText": _text_value(label if display_text is None else display_text, 300, True)}
    return {"type": "button", "height": "sm", "style": "secondary",
            "color": BUTTON_COLOR, "action": action}


def _bubble(title, contents, buttons=None):
    bubble = {"type": "bubble", "size": "mega",
              "header": {"type": "box", "layout": "vertical", "backgroundColor": GREEN,
                         "paddingAll": "16px", "contents": [_text(title, "lg", "#ffffff", "bold")]},
              "body": {"type": "box", "layout": "vertical", "spacing": "md",
                       "paddingAll": "18px", "contents": contents}}
    if buttons:
        bubble["footer"] = {"type": "box", "layout": "vertical", "spacing": "sm",
                            "paddingAll": "16px", "contents": buttons}
    if _json_size(bubble) > _BUBBLE_BYTES:
        _bad()
    return bubble


def _flex(alt_text, contents):
    _text_value(alt_text, 1500, True)
    bound = _CAROUSEL_BYTES if contents.get("type") == "carousel" else _BUBBLE_BYTES
    if _json_size(contents) > bound:
        _bad()
    return {"type": "flex", "altText": alt_text, "contents": contents}


def menu_messages(total=None, title="派車工作選單"):
    """One standard Flex menu; None means the current count has not been read."""
    title = _text_value(title, 100, True)
    if total is not None:
        _integer(total)
    line = "請選擇要查詢的內容。" if total is None else "目前未派車：" + str(total) + " 筆"
    contents = [_text(line, "lg", GREEN, "bold"),
                _text("點選後，查詢結果會回覆在聊天室。", color="#6b817b"),
                _text("每次查詢都會讀取最新的試算表狀態。", "xs", "#6b817b")]
    buttons = [_postback("查詢未派車筆數", "pv1:count"),
               _postback("查看未派車名單", "pv1:list")]
    return [_flex(title, _bubble(title, contents, buttons))]


def _telephone(phone):
    # Do not strip arbitrary characters to manufacture a valid telephone number.
    if not re.fullmatch(r"[+0-9()\s-]+", phone):
        return None
    normalized = re.sub(r"[()\s-]", "", phone)
    if re.fullmatch(r"09[0-9]{8}|0[2-8][0-9]{7,8}|\+[1-9][0-9]{7,14}", normalized):
        return "tel:" + normalized
    return None


def _case_bubble(case, title="未派車案件", include_status=False):
    if (not isinstance(case, dict) or not _CASE_FIELDS <= set(case)
            or not set(case) <= _CASE_FIELDS | _OPTIONAL_FIELDS):
        _bad()
    ident = _text_value(case["caseId"], 80, True)
    if not _CASE_ID.fullmatch(ident):
        _bad()
    values = {key: _text_value(case[key], 2000) for key in ("name", "phone", "address", "model")}
    for key in _OPTIONAL_FIELDS & set(case):
        _text_value(case[key], 2000)
    body = [_text(ident, "lg", GREEN, "bold")]
    if include_status:
        status = case.get("status", "")
        body.append({"type": "box", "layout": "vertical", "spacing": "xs", "contents": [
            _text("目前派車狀態", "xs", "#6b817b"), _text(status or "未派車", "md", GREEN, "bold")]})
    for label, key in (("姓名", "name"), ("聯絡電話", "phone"), ("回收地址", "address"), ("機型", "model")):
        body.append({"type": "box", "layout": "vertical", "spacing": "xs", "contents": [
            _text(label, "xs", "#6b817b"), _text(values[key] or "未提供", "md")]})
    buttons = [_postback("標記已派車", "pv1:dispatch:" + ident, "將 " + ident + " 標記為已派車")]
    phone_uri = _telephone(values["phone"])
    if phone_uri:
        buttons.append({"type": "button", "height": "sm", "style": "secondary",
                        "color": BUTTON_COLOR, "action": {"type": "uri", "label": "手機撥打", "uri": phone_uri}})
    address = values["address"]
    if address.strip() and _units(address) <= 1000:
        buttons.append({"type": "button", "height": "sm", "style": "secondary", "color": BUTTON_COLOR,
                        "action": {"type": "clipboard", "label": "複製地址", "clipboardText": address}})
    elif address.strip():
        body.append(_text("地址較長，請直接選取完整地址複製。", "xs", "#6b817b"))
    body.append(_text("複製按鈕請於支援的手機 LINE 使用。", "xs", "#6b817b"))
    return _bubble(title, body, buttons)


def case_messages(case, queried_at):
    """One existing case's actual dispatch status, with no global count claim."""
    queried_at = _text_value(queried_at, 100, True)
    bubble = _case_bubble(case, title="派車案件資料", include_status=True)
    bubble["body"]["contents"].append(_text("查詢時間：" + queried_at, "xs", "#6b817b"))
    return [_flex("派車案件資料｜" + case["caseId"], bubble), *menu_messages()]


def list_messages(cases, total, snapshot_id, page, page_count, queried_at, daily=False):
    """Complete, untruncated rows of a caller-owned, 1-based snapshot page.

    Accept the five display fields or the receiver's seven-field row. No case
    data is placed in pagination tokens. A large page can use two carousels,
    merging navigation into its header to remain at most three messages.
    """
    _integer(total)
    _integer(page, 1, 100)
    _integer(page_count, 1, 100)
    if (not isinstance(cases, list) or len(cases) > 10 or type(daily) is not bool
            or not isinstance(snapshot_id, str)
            or not (total == 0 and not cases and snapshot_id == "" or _SNAPSHOT.fullmatch(snapshot_id))
            or page > page_count):
        _bad()
    queried_at = _text_value(queried_at, 100, True)
    if not cases and total == 0:
        return [{"type": "text", "text": "目前沒有未派車案件。\n查詢時間：" + queried_at},
                *menu_messages(0)]
    buttons = []
    if page < page_count:
        buttons.append(_postback("查看下一頁", "pv1:next:" + snapshot_id + ":" + str(page + 1)))
    buttons.extend([_postback("重新查詢名單", "pv1:refresh"), _postback("返回工作選單", "pv1:menu")])
    if not cases:
        return [{"type": "text", "text": "本頁已無待派車案件，可重新查詢名單。\n目前未派車 " + str(total)
                 + " 筆\n本次名單第 " + str(page) + " / " + str(page_count) + " 頁\n查詢時間：" + queried_at},
                *menu_messages(total),
                _flex("名單操作", _bubble("名單操作", [_text("點選後，查詢結果會回覆在聊天室。")], buttons))]
    bubbles = [_case_bubble(case) for case in cases]
    if len({case["caseId"] for case in cases}) != len(cases):
        _bad()
    chunks = []
    current = []
    for bubble in bubbles:
        candidate = {"type": "carousel", "contents": current + [bubble]}
        if current and _json_size(candidate) > _CAROUSEL_BYTES:
            chunks.append(current)
            current = []
        current.append(bubble)
    if current:
        chunks.append(current)
    if len(chunks) > 2:
        _bad()
    title = "每日派車彙整" if daily else "未派車名單"
    info = [_text("目前未派車 " + str(total) + " 筆", "lg", GREEN, "bold"),
            _text("本次名單第 " + str(page) + " / " + str(page_count) + " 頁 · 左右滑動查看案件"),
            _text("查詢時間：" + queried_at, "xs", "#6b817b"),
            _text("舊卡片不會自動更新；操作前可點「重新查詢名單」。", "xs", "#6b817b")]
    alt = title + "｜目前未派車 " + str(total) + " 筆｜本次名單第 " + str(page) + "/" + str(page_count) + " 頁"
    # Normal pages have a header, one carousel, and a footer. Large pages keep
    # the full data and place their navigation in the header instead.
    messages = [_flex(alt, _bubble(title, info, buttons if len(chunks) > 1 else None))]
    messages.extend(_flex(alt, {"type": "carousel", "contents": chunk}) for chunk in chunks)
    if len(chunks) == 1:
        messages.append(_flex("名單操作", _bubble("名單操作", [_text("點選後，查詢結果會回覆在聊天室。")], buttons)))
    if len(messages) > 3 or _json_size(messages) > 200000:
        _bad()
    return messages
