/**
 * PetPivot repair application -> Google Sheets, one-way authenticated upsert.
 * Set SPREADSHEET_ID, SHEET_NAME=維修案件, SYNC_SECRET in Script Properties.
 * Deploy as Web app, Execute as Me, Access Anyone. Never publish the sheet.
 * No secret or customer data is logged or returned to callers.
 */
const SYNC_SCHEMA = 'petpivot-v1';
const PICKUP_SCHEMA = 'petpivot-pickup-v1';
const PICKUP_SPREADSHEET_ID = '11T4F5krGq2rzDRy9ICE6dQA1f7f2xX22OoLhHK117-Q';
const PICKUP_SHEET_ID = 1272115939;
const PICKUP_SHEET_NAME = '派車回收名單';
const PICKUP_HEADERS = ['案件編號', '日期', '客戶姓名', '聯絡電話', '收件/寄回地址', '訂單編號', '商品型號', '機器故障現象描述'];
const DISPATCH_SCHEMA = 'petpivot-dispatch-v1';
const DISPATCH_LIST_SCHEMA = 'petpivot-dispatch-list-v1';
const DISPATCH_STATUS = '已派車';
const DISPATCH_COLUMN = 9;
const DISPATCH_HEADER = '派車狀態';
const DISPATCH_META_HEADERS = ['case_id', 'command_id', 'before_value', 'state'];
const SYNC_META_HEADERS = ['case_id', 'revision', 'payload_hash', 'created_at', 'user_id', 'state'];
const SYNC_HEADERS = [
  '案件編號', '建立時間', 'LINE User ID', 'LINE顯示名稱', '電子郵件地址',
  '客戶姓名', '聯絡電話', '收件/回寄地址', '訂單編號', '購買憑證與附件',
  '機器故障現象描述', '其他補充說明', '寄送內容物確認', '機器清潔狀態確認',
  '包裝與運送責任聲明', '收送件資格與時間說明', '配送日期', '配送狀態',
  '維修狀態', '付款連結', 'LINE通知狀態', '最後更新時間', '商品型號',
  '商品序號', '購買通路', '訂單提供狀態', '維修處理', '寄送方式', '取件地址',
  '回收運費', '寄送注意事項', 'LINE摘要收件時間'
];
// Canonical schema ordinals, not physical sheet positions. These identify the
// server-owned fields by SYNC_HEADERS; syncMainColumns_ resolves their actual
// locations. Purchase attachments, delivery date/status and payment link stay
// staff-owned even when those columns are moved.
const SYNC_COLUMNS = {
  id: 1, createdAt: 2, lineUserId: 3, lineDisplayName: 4, email: 5, name: 6,
  phone: 7, returnAddress: 8, order: 9, problem: 11, extra: 12,
  contentConfirmation: 13, cleaningConfirmation: 14, packingConfirmation: 15,
  shippingConfirmation: 16, status: 19, lineNotification: 21, updatedAt: 22,
  model: 23, serial: 24, purchaseChannel: 25, orderChoice: 26, repairPolicy: 27,
  shipping: 28, pickupAddress: 29, pickupFeeTwd: 30, shippingNote: 31,
  lineSummaryReceivedAt: 32
};

function syncResult_(object) {
  return ContentService.createTextOutput(JSON.stringify(object))
    .setMimeType(ContentService.MimeType.JSON);
}

function syncFail_(code) { return syncResult_({ok: false, error: code}); }

function syncEqual_(left, right) {
  if (typeof left !== 'string' || typeof right !== 'string') return false;
  let difference = left.length ^ right.length;
  const count = Math.max(left.length, right.length);
  for (let i = 0; i < count; i++) {
    difference |= (left.charCodeAt(i) || 0) ^ (right.charCodeAt(i) || 0);
  }
  return difference === 0;
}

function syncProperties_() {
  const p = PropertiesService.getScriptProperties();
  const id = p.getProperty('SPREADSHEET_ID') || '1C5gGI4cL4lgw-GqSXRcQuicM2e5FvDHp-bnfqpMcnqI';
  const name = p.getProperty('SHEET_NAME') || '維修案件';
  const secret = p.getProperty('SYNC_SECRET');
  if (!/^[A-Za-z0-9_-]{20,100}$/.test(id || '') || name !== '維修案件' ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(secret || '')) throw new Error('configuration');
  return {id: id, name: name, secret: secret};
}

function syncValidateCase_(record) {
  if (!record || typeof record !== 'object' || Array.isArray(record)) return false;
  const allowed = Object.keys(SYNC_COLUMNS).concat(['revision']).sort();
  const actual = Object.keys(record).sort();
  if (JSON.stringify(actual) !== JSON.stringify(allowed)) return false;
  if (!/^R\d{8}-\d{4,}$/.test(record.id) || record.id.length > 50 ||
      !Number.isSafeInteger(record.revision) || record.revision < 1) return false;
  if (!Object.keys(SYNC_COLUMNS).every(function(key) {
    return typeof record[key] === 'string' && record[key].length <= 8000;
  })) return false;
  if (record.pickupFeeTwd !== '' && record.pickupFeeTwd !== '350' && record.pickupFeeTwd !== '700') return false;
  return ['createdAt', 'updatedAt', 'lineSummaryReceivedAt'].every(function(key) {
    if (key === 'lineSummaryReceivedAt' && !record[key]) return true;
    try { syncDate_(record[key]); return true; } catch (_) { return false; }
  });
}

function syncDate_(text) {
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) throw new Error('invalid_case');
  const value = new Date(text.replace(' ', 'T') + '+08:00');
  if (isNaN(value.getTime()) || Utilities.formatDate(value, 'Asia/Taipei', 'yyyy-MM-dd HH:mm:ss') !== text) {
    throw new Error('invalid_case');
  }
  return value;
}

function syncTimestamp_(value) {
  // Google Sheets can infer DATE_TIME even for RichTextValue writes. Preserve
  // creation identity by comparing the timestamp, not a Date object's type.
  if (value instanceof Date) return Utilities.formatDate(value, 'Asia/Taipei', 'yyyy-MM-dd HH:mm:ss');
  if (typeof value === 'number' && Number.isFinite(value) && value >= 1 && value < 2958466) {
    // A plain numeric Sheets date is days since 1899-12-30 in the sheet's local
    // time. Round to seconds to avoid floating-point noise in its time portion.
    const epoch = Date.UTC(1899, 11, 30);
    const date = new Date(epoch + Math.round(value * 86400) * 1000 - 8 * 3600000);
    return Utilities.formatDate(date, 'Asia/Taipei', 'yyyy-MM-dd HH:mm:ss');
  }
  return typeof value === 'string' ? value : '';
}

function syncMainColumns_(sheet) {
  if (!sheet || sheet.getMaxColumns() < SYNC_HEADERS.length) throw new Error('schema_mismatch');
  // Resolve from one header snapshot. Scan all physical columns so a duplicate
  // required header beyond the original A:AF range cannot be silently ignored.
  const headers = sheet.getRange(1, 1, 1, sheet.getMaxColumns()).getDisplayValues()[0];
  const positions = {};
  SYNC_HEADERS.forEach(function(header) {
    const index = headers.indexOf(header);
    if (index < 0 || index !== headers.lastIndexOf(header)) throw new Error('schema_mismatch');
    positions[header] = index + 1;
  });
  const columns = {};
  Object.keys(SYNC_COLUMNS).forEach(function(key) {
    columns[key] = positions[SYNC_HEADERS[SYNC_COLUMNS[key] - 1]];
  });
  return columns;
}

function syncSheet_(config) {
  const spreadsheet = SpreadsheetApp.openById(config.id);
  const sheet = spreadsheet.getSheetByName(config.name);
  const columns = syncMainColumns_(sheet);
  return {spreadsheet: spreadsheet, sheet: sheet, columns: columns};
}

function syncHash_(record) {
  const ordered = {};
  Object.keys(record).sort().forEach(function(key) { ordered[key] = record[key]; });
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(ordered), Utilities.Charset.UTF_8).map(function(byte) {
      return ('0' + (byte & 255).toString(16)).slice(-2);
    }).join('');
}

function syncMeta_(spreadsheet) {
  let sheet = spreadsheet.getSheetByName('_sync');
  if (!sheet) {
    sheet = spreadsheet.insertSheet('_sync');
    sheet.getRange(1, 1, 1, SYNC_META_HEADERS.length).setValues([SYNC_META_HEADERS]);
    sheet.hideSheet();
  }
  const header = sheet.getRange(1, 1, 1, SYNC_META_HEADERS.length).getDisplayValues()[0];
  if (JSON.stringify(header) !== JSON.stringify(SYNC_META_HEADERS)) {
    throw new Error('schema_mismatch');
  }
  return sheet;
}

function syncFindRows_(sheet, id, idColumn) {
  const last = sheet.getLastRow();
  if (last < 2) return [];
  const values = sheet.getRange(2, idColumn || 1, last - 1, 1).getDisplayValues();
  const rows = [];
  values.forEach(function(row, index) { if (row[0] === id) rows.push(index + 2); });
  return rows;
}

function syncEnsureRows_(sheet, row) {
  const missing = row - sheet.getMaxRows();
  if (missing > 0) sheet.insertRowsAfter(sheet.getMaxRows(), Math.max(missing, 100));
}

function syncWriteText_(sheet, row, column, text) {
  // RichTextValue stores literal text, including leading '=' and zeroes.
  // Customer values never pass through setValue/setFormula or formula parsing.
  sheet.getRange(row, column).setRichTextValue(
    SpreadsheetApp.newRichTextValue().setText(text).build());
}

function syncWriteRecord_(sheet, row, record, columns) {
  columns = columns || syncMainColumns_(sheet);
  const cells = Object.keys(SYNC_COLUMNS).map(function(key) {
    return {key: key, column: columns[key], text: record[key]};
  }).sort(function(a, b) { return a.column - b.column; });
  const typedKeys = ['createdAt', 'updatedAt', 'pickupFeeTwd', 'lineSummaryReceivedAt'];
  const textCells = cells.filter(function(cell) { return typedKeys.indexOf(cell.key) < 0; });
  let start = 0;
  while (start < textCells.length) {
    let end = start + 1;
    while (end < textCells.length && textCells[end].column === textCells[end - 1].column + 1) end++;
    const rich = textCells.slice(start, end).map(function(cell) {
      return SpreadsheetApp.newRichTextValue().setText(cell.text).build();
    });
    sheet.getRange(row, textCells[start].column, 1, rich.length).setRichTextValues([rich]);
    start = end;
  }
  cells.filter(function(cell) { return typedKeys.indexOf(cell.key) >= 0; }).forEach(function(cell) {
    const range = sheet.getRange(row, cell.column);
    if (!cell.text) { range.clearContent(); return; }
    if (cell.key === 'pickupFeeTwd') {
      if (cell.text !== '350' && cell.text !== '700') throw new Error('invalid_case');
      range.setValue(Number(cell.text));
    } else {
      range.setValue(syncDate_(cell.text));
    }
  });
}

function syncUpsert_(record, config) {
  const opened = syncSheet_(config);
  const sheet = opened.sheet;
  const columns = opened.columns;
  const meta = syncMeta_(opened.spreadsheet);
  const rows = syncFindRows_(sheet, record.id, columns.id);
  const metaRows = syncFindRows_(meta, record.id);
  if (rows.length > 1 || metaRows.length > 1) throw new Error('duplicate_case_id');
  const old = metaRows.length ? meta.getRange(metaRows[0], 1, 1, SYNC_META_HEADERS.length).getValues()[0] : null;
  const hash = syncHash_(record);
  if (old && Number(old[1]) > record.revision) return 'stale';
  if (old && Number(old[1]) === record.revision && old[2] !== hash) {
    throw new Error('revision_conflict');
  }
  if (old && (syncTimestamp_(old[3]) !== record.createdAt || old[4] !== record.lineUserId)) {
    throw new Error('ownership_conflict');
  }
  if (old && Number(old[1]) === record.revision && old[2] === hash && old[5] === 'synced' && rows.length) {
    return 'unchanged';
  }
  // Preserve immutable ownership/creation even if a future caller has a bug.
  if (rows.length) {
    const created = syncTimestamp_(sheet.getRange(rows[0], columns.createdAt).getValues()[0][0]);
    const existingUserId = sheet.getRange(rows[0], columns.lineUserId).getValues()[0][0];
    const repairing = old && old[5] === 'pending';
    if ((created !== record.createdAt && !(repairing && !created)) ||
        (String(existingUserId) !== record.lineUserId && !(repairing && !existingUserId))) {
      throw new Error('ownership_conflict');
    }
  }
  const row = rows.length ? rows[0] : Math.max(2, sheet.getLastRow() + 1);
  syncEnsureRows_(sheet, row);
  const metaRow = metaRows.length ? metaRows[0] : Math.max(2, meta.getLastRow() + 1);
  syncEnsureRows_(meta, metaRow);
  // Write-ahead metadata records ownership and version before case writes. If
  // execution stops mid-row, the same or newer version safely repairs that row.
  const metadata = [record.id, String(record.revision), hash, record.createdAt, record.lineUserId, 'pending'];
  meta.getRange(metaRow, 1, 1, SYNC_META_HEADERS.length).setNumberFormat('@').setRichTextValues([
    metadata.map(function(text) { return SpreadsheetApp.newRichTextValue().setText(text).build(); })]);
  SpreadsheetApp.flush();
  syncWriteRecord_(sheet, row, record, columns);
  // Flush case values before recording acknowledgment metadata. A retry after
  // interruption finds the same id, repairs the row and preserves staff cells.
  SpreadsheetApp.flush();
  meta.getRange(metaRow, 6).setValue('synced');
  SpreadsheetApp.flush();
  return rows.length ? 'updated' : 'inserted';
}

function syncPickupSheet_() {
  // Destination is fixed by the operator, never supplied by a customer/request.
  const spreadsheet = SpreadsheetApp.openById(PICKUP_SPREADSHEET_ID);
  const sheet = spreadsheet.getSheetById(PICKUP_SHEET_ID);
  if (!sheet || sheet.getName() !== PICKUP_SHEET_NAME || sheet.getMaxColumns() < 8 ||
      JSON.stringify(sheet.getRange(1, 1, 1, 8).getDisplayValues()[0]) !== JSON.stringify(PICKUP_HEADERS)) {
    throw new Error('pickup_schema_mismatch');
  }
  return sheet;
}

function syncPickupEligible_(record) {
  return record.shipping === '由客服派遣物流回收' && /^U[0-9a-f]{32}$/.test(record.lineUserId) &&
    record.pickupAddress.trim().length > 0;
}

function syncPickupMeta_(config) {
  const spreadsheet = SpreadsheetApp.openById(config.id);
  let sheet = spreadsheet.getSheetByName('_pickup_sync');
  if (!sheet) {
    sheet = spreadsheet.insertSheet('_pickup_sync');
    sheet.getRange(1, 1, 1, SYNC_META_HEADERS.length).setValues([SYNC_META_HEADERS]);
    sheet.hideSheet();
  }
  if (JSON.stringify(sheet.getRange(1, 1, 1, SYNC_META_HEADERS.length).getDisplayValues()[0]) !== JSON.stringify(SYNC_META_HEADERS)) {
    throw new Error('pickup_schema_mismatch');
  }
  return sheet;
}

function syncPickupRows_(sheet, id) {
  const last = sheet.getLastRow();
  if (last < 2) return [];
  const rows = [];
  sheet.getRange(2, 1, last - 1, 1).getDisplayValues().forEach(function(row, index) {
    if (String(row[0]).trim() === id) rows.push(index + 2);
  });
  return rows;
}

function syncPickupUpsert_(record, config) {
  const sheet = syncPickupSheet_();
  const meta = syncPickupMeta_(config);
  const rows = syncPickupRows_(sheet, record.id);
  const metaRows = syncPickupRows_(meta, record.id);
  if (rows.length > 1 || metaRows.length > 1) throw new Error('duplicate_case_id');
  const old = metaRows.length ? meta.getRange(metaRows[0], 1, 1, SYNC_META_HEADERS.length).getValues()[0] : null;
  const hash = syncHash_(record);
  if (old && (syncTimestamp_(old[3]) !== record.createdAt || old[4] !== record.lineUserId)) {
    throw new Error('ownership_conflict');
  }
  if (old && Number(old[1]) > record.revision) return 'stale';
  if (old && Number(old[1]) === record.revision && old[2] !== hash) throw new Error('revision_conflict');
  // Missing an already-acknowledged ID might be a human edit or a moved row.
  // Stop instead of guessing a row or silently duplicating staff-managed data.
  if (old && old[5] === 'synced' && !rows.length) throw new Error('pickup_case_missing');
  if (old && Number(old[1]) === record.revision && old[2] === hash && old[5] === 'synced') return 'unchanged';
  const row = rows.length ? rows[0] : Math.max(2, sheet.getLastRow() + 1);
  const metaRow = metaRows.length ? metaRows[0] : Math.max(2, meta.getLastRow() + 1);
  syncEnsureRows_(sheet, row);
  syncEnsureRows_(meta, metaRow);
  if (PropertiesService.getScriptProperties().getProperty(REPEAT_FEATURE_KEY) === '1') {
    const actionCell = sheet.getRange(row, repeatColumns_(sheet,false).action);
    if (!actionCell.getDataValidation()) actionCell.setDataValidation(repeatCheckboxRule_());
  }
  const metadata = [record.id, String(record.revision), hash, record.createdAt, record.lineUserId, 'pending'];
  meta.getRange(metaRow, 1, 1, SYNC_META_HEADERS.length).setNumberFormat('@').setRichTextValues([
    metadata.map(function(text) { return SpreadsheetApp.newRichTextValue().setText(text).build(); })]);
  SpreadsheetApp.flush();
  // Reserve the stable ID before writing other fields so partial retries reuse
  // the same row. Only A:H belong to this integration; I and later never change.
  sheet.getRange(row, 1).setNumberFormat('@');
  syncWriteText_(sheet, row, 1, record.id);
  const values = [record.name, record.phone, record.pickupAddress, record.order, record.model, record.problem];
  sheet.getRange(row, 3, 1, values.length).setNumberFormat('@').setRichTextValues([
    values.map(function(text) { return SpreadsheetApp.newRichTextValue().setText(text).build(); })]);
  const date = sheet.getRange(row, 2);
  const existingDate = date.getValues()[0][0];
  if ((existingDate === '' || existingDate === null) && !date.getFormula()) {
    date.setNumberFormat('yyyy/MM/dd').setValue(new Date(record.createdAt.slice(0, 10) + 'T00:00:00+08:00'));
  }
  SpreadsheetApp.flush();
  meta.getRange(metaRow, 6).setValue('synced');
  SpreadsheetApp.flush();
  return rows.length ? 'updated' : 'inserted';
}

function syncPickupResult_(config, extra) {
  return syncResult_(Object.assign({ok: true, sheetId: config.id, schema: PICKUP_SCHEMA,
    pickupSheetId: PICKUP_SPREADSHEET_ID, pickupSheetGid: PICKUP_SHEET_ID}, extra || {}));
}

function syncDispatchCommandId_(value) {
  // A length check plus invalid-character check also rejects a final newline;
  // JavaScript's '$' anchor alone can accept one before the end of a string.
  return typeof value === 'string' && value.length >= 1 && value.length <= 128 && !/[^!-~]/.test(value);
}

function syncDispatchCaseId_(value) {
  if (typeof value !== 'string' || value.length > 80) return false;
  const match = /^R[0-9]{8}-[0-9]{4,}$/.exec(value);
  return !!match && match[0] === value;
}

function syncValidateDispatch_(dispatch) {
  if (!dispatch || typeof dispatch !== 'object' || Array.isArray(dispatch)) return false;
  const keys = ['caseId', 'commandId'];
  if (Object.prototype.hasOwnProperty.call(dispatch, 'repeatRequestId')) {
    if (!repeatUuid_(dispatch.repeatRequestId)) return false;
    keys.push('repeatRequestId');
  }
  if (!productionPaymentExactKeys_(dispatch, keys)) return false;
  return syncDispatchCaseId_(dispatch.caseId) && syncDispatchCommandId_(dispatch.commandId);
}

function syncValidateDispatchQuery_(query) {
  if (!query || typeof query !== 'object' || Array.isArray(query) ||
      JSON.stringify(Object.keys(query)) !== JSON.stringify(['caseIds']) ||
      !Array.isArray(query.caseIds) || query.caseIds.length > 1000) return false;
  const seen = new Set();
  return query.caseIds.every(function(id) {
    if (!syncDispatchCaseId_(id) || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function syncDispatchSheet_() {
  try {
    const sheet = syncPickupSheet_();
    if (sheet.getMaxColumns() < DISPATCH_COLUMN ||
        sheet.getRange(1, DISPATCH_COLUMN).getDisplayValue() !== DISPATCH_HEADER) {
      throw new Error('dispatch_schema_mismatch');
    }
    return sheet;
  } catch (_) { throw new Error('dispatch_schema_mismatch'); }
}

function syncDispatchMeta_(spreadsheet, name, create) {
  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet && create) {
    sheet = spreadsheet.insertSheet(name);
    sheet.getRange(1, 1, 1, DISPATCH_META_HEADERS.length).setValues([DISPATCH_META_HEADERS]);
    sheet.hideSheet();
  }
  if (sheet && (sheet.getMaxColumns() < DISPATCH_META_HEADERS.length ||
      JSON.stringify(sheet.getRange(1, 1, 1, DISPATCH_META_HEADERS.length).getDisplayValues()[0]) !== JSON.stringify(DISPATCH_META_HEADERS))) {
    throw new Error('dispatch_schema_mismatch');
  }
  return sheet;
}

function syncDispatchEventRows_(sheet, commandId) {
  if (!sheet || sheet.getLastRow() < 2) return [];
  const rows = [];
  sheet.getRange(2, 2, sheet.getLastRow() - 1, 1).getDisplayValues().forEach(function(row, index) {
    if (String(row[0]).trim() === commandId) rows.push(index + 2);
  });
  return rows;
}

function syncDispatchBefore_(value) {
  if (value instanceof Date && Number.isFinite(value.getTime())) return JSON.stringify(['date', value.toISOString()]);
  if (typeof value === 'string' || typeof value === 'boolean' ||
      typeof value === 'number' && Number.isFinite(value) || value === null) {
    return JSON.stringify([value === null ? 'null' : typeof value, value]);
  }
  throw new Error('dispatch_status_conflict');
}

function syncDispatchCachedBefore_(text) {
  // Validate stored write-ahead state without interpreting it as a formula.
  try {
    if (typeof text !== 'string') throw new Error('invalid');
    const value = JSON.parse(text);
    if (!Array.isArray(value) || value.length !== 2) throw new Error('invalid');
    const type = value[0], content = value[1];
    if (type === 'date') {
      const date = new Date(content);
      if (typeof content !== 'string' || !Number.isFinite(date.getTime()) || date.toISOString() !== content) throw new Error('invalid');
    } else if (!(type === 'string' && typeof content === 'string' ||
        type === 'boolean' && typeof content === 'boolean' ||
        type === 'number' && typeof content === 'number' && Number.isFinite(content) ||
        type === 'null' && content === null)) throw new Error('invalid');
    if (JSON.stringify(value) !== text) throw new Error('invalid');
    return text;
  } catch (_) { throw new Error('dispatch_status_conflict'); }
}

function syncDispatchValidation_(range) {
  try {
    const rule = range.getDataValidation();
    if (!rule) return;
    const criteria = rule.getCriteriaType(), values = rule.getCriteriaValues();
    const allowed = SpreadsheetApp.DataValidationCriteria;
    let choices;
    if (criteria === allowed.VALUE_IN_LIST && Array.isArray(values[0])) choices = values[0];
    else if (criteria === allowed.VALUE_IN_RANGE && values[0] && typeof values[0].getValues === 'function') {
      choices = [].concat.apply([], values[0].getValues());
    } else throw new Error('invalid');
    if (choices.indexOf(DISPATCH_STATUS) < 0) throw new Error('invalid');
  } catch (_) { throw new Error('dispatch_validation_conflict'); }
}

function syncDispatchMetaRecord_(old) {
  if (!syncDispatchCommandId_(old[1]) || ['pending', 'synced'].indexOf(old[3]) < 0) {
    throw new Error('dispatch_status_conflict');
  }
  syncDispatchCachedBefore_(old[2]);
  return old;
}

function syncDispatchBlank_(value) { return value === '' || value === null; }

function syncDispatchPendingBefore_(before) {
  return before === syncDispatchBefore_('') || before === syncDispatchBefore_(null) ||
    before === syncDispatchBefore_(DISPATCH_STATUS);
}

function syncDispatchSaveEvent_(spreadsheet, meta, dispatch, before, state) {
  meta = meta || syncDispatchMeta_(spreadsheet, '_pickup_dispatch_events', true);
  const row = Math.max(2, meta.getLastRow() + 1);
  syncEnsureRows_(meta, row);
  const metadata = [dispatch.caseId, dispatch.commandId, before, state];
  meta.getRange(row, 1, 1, metadata.length).setNumberFormat('@').setRichTextValues([
    metadata.map(function(text) { return SpreadsheetApp.newRichTextValue().setText(text).build(); })]);
  SpreadsheetApp.flush();
  return {sheet: meta, row: row};
}

function syncDispatchUpdate_(dispatch, config) {
  const sheet = syncDispatchSheet_();
  const rows = syncPickupRows_(sheet, dispatch.caseId);
  if (rows.length > 1) throw new Error('duplicate_case_id');
  if (!rows.length) throw new Error('dispatch_case_missing');
  const spreadsheet = SpreadsheetApp.openById(config.id);
  let meta = syncDispatchMeta_(spreadsheet, '_pickup_dispatch_events', false);
  const eventRows = syncDispatchEventRows_(meta, dispatch.commandId);
  if (eventRows.length > 1) throw new Error('duplicate_case_id');
  let event = eventRows.length ? syncDispatchMetaRecord_(meta.getRange(eventRows[0], 1, 1, DISPATCH_META_HEADERS.length).getValues()[0]) : null;
  if (event && String(event[0]).trim() !== dispatch.caseId) throw new Error('ownership_conflict');
  const legacy = syncDispatchMeta_(spreadsheet, '_pickup_dispatch', false);
  const legacyCommands = syncDispatchEventRows_(legacy, dispatch.commandId);
  if (legacyCommands.length > 1) throw new Error('duplicate_case_id');
  if (legacyCommands.length && String(legacy.getRange(legacyCommands[0], 1).getValue()).trim() !== dispatch.caseId) {
    throw new Error('ownership_conflict');
  }
  // A completed event is never replayed, even if staff subsequently clear I.
  if (event && event[3] === 'synced') return 'unchanged';

  // Keep the v5 case journal as immutable legacy evidence. Its original
  // completed command must also remain deduplicated after upgrading.
  const legacyRows = legacy ? syncPickupRows_(legacy, dispatch.caseId) : [];
  if (legacyRows.length > 1) throw new Error('duplicate_case_id');
  const old = legacyRows.length ? syncDispatchMetaRecord_(legacy.getRange(legacyRows[0], 1, 1, DISPATCH_META_HEADERS.length).getValues()[0]) : null;
  const legacyEvent = old && old[1] === dispatch.commandId ? old : null;
  if (legacyEvent && legacyEvent[3] === 'synced') return 'unchanged';
  const pending = event || legacyEvent;

  const range = sheet.getRange(rows[0], DISPATCH_COLUMN);
  const current = range.getValue(), before = syncDispatchBefore_(current);
  if (!pending && !syncDispatchBlank_(current)) {
    // Consume a new event without writing any non-empty staff status. This
    // also prevents its later replay from filling a newly-cleared cell.
    syncDispatchSaveEvent_(spreadsheet, meta, dispatch, before, 'synced');
    return 'unchanged';
  }
  if (pending && (!syncDispatchPendingBefore_(pending[2]) ||
      current !== DISPATCH_STATUS && before !== pending[2])) throw new Error('dispatch_status_conflict');
  if (range.getFormula()) throw new Error('dispatch_status_conflict');
  syncDispatchValidation_(range);
  let metaRow = eventRows.length ? eventRows[0] : 0;
  const expected = pending ? pending[2] : before;
  if (!event) {
    const saved = syncDispatchSaveEvent_(spreadsheet, meta, dispatch, expected, 'pending');
    meta = saved.sheet;
    metaRow = saved.row;
  }
  // Only the existing I cell is written. Keep its format, validation and all
  // customer/staff columns untouched; never append a destination case row.
  // Recheck after flushing write-ahead state: staff may have edited the cell
  // or sorted rows while it was saved. The script lock does not lock their UI.
  const latestRows = syncPickupRows_(sheet, dispatch.caseId);
  if (latestRows.length > 1) throw new Error('duplicate_case_id');
  if (!latestRows.length) throw new Error('dispatch_case_missing');
  const latestRange = sheet.getRange(latestRows[0], DISPATCH_COLUMN);
  if (latestRange.getFormula()) throw new Error('dispatch_status_conflict');
  syncDispatchValidation_(latestRange);
  const latest = latestRange.getValue();
  if (latest !== DISPATCH_STATUS && syncDispatchBefore_(latest) !== expected) {
    throw new Error('dispatch_status_conflict');
  }
  let wroteDispatch = false;
  if (latest !== DISPATCH_STATUS) {
    repeatPrepareFirst_(sheet, dispatch.caseId, dispatch.commandId);
    const targetRows = syncPickupRows_(sheet, dispatch.caseId);
    if (targetRows.length !== 1) throw new Error('dispatch_status_conflict');
    const target = sheet.getRange(targetRows[0], DISPATCH_COLUMN);
    const targetValue = target.getValue();
    if (target.getFormula() || (targetValue !== DISPATCH_STATUS && syncDispatchBefore_(targetValue) !== expected)) throw new Error('dispatch_status_conflict');
    syncDispatchValidation_(target);
    if (targetValue !== DISPATCH_STATUS) {
      syncWriteText_(sheet, targetRows[0], DISPATCH_COLUMN, DISPATCH_STATUS);
      wroteDispatch = true;
    }
  }
  SpreadsheetApp.flush();
  // Persist the first observed dispatch before acknowledging this command.
  // When replaying a pending write, an existing history entry is reused.
  if (syncDispatchPendingBefore_(expected) && expected !== syncDispatchBefore_(DISPATCH_STATUS)) {
    repeatCaptureFirst_(sheet, dispatch.caseId, dispatch.commandId);
  }
  meta.getRange(metaRow, 4).setValue('synced');
  SpreadsheetApp.flush();
  return wroteDispatch ? 'updated' : 'unchanged';
}

function syncDispatchResult_(config, extra) {
  return syncResult_(Object.assign({ok: true, sheetId: config.id, schema: DISPATCH_SCHEMA,
    pickupSheetId: PICKUP_SPREADSHEET_ID, pickupSheetGid: PICKUP_SHEET_ID}, extra || {}));
}

function syncDispatchList_(query) {
  let sheet;
  try { sheet = syncDispatchSheet_(); }
  catch (_) { throw new Error('list_schema_mismatch'); }
  if (!query.caseIds.length) return [];
  // Inspect only the ID column to resolve the allowlist. Customer details are
  // read only after every requested ID has a unique existing row.
  const indexed = new Map();
  query.caseIds.forEach(function(id) { indexed.set(id, []); });
  const last = sheet.getLastRow();
  if (last >= 2) {
    sheet.getRange(2, 1, last - 1, 1).getDisplayValues().forEach(function(row, index) {
      const id = String(row[0]).trim();
      if (indexed.has(id)) indexed.get(id).push(index + 2);
    });
  }
  query.caseIds.forEach(function(id) {
    const rows = indexed.get(id);
    if (rows.length > 1) throw new Error('duplicate_case_id');
    if (!rows.length) throw new Error('list_case_missing');
  });
  const repeat = repeatBook_(sheet);
  return query.caseIds.map(function(id) {
    const row = indexed.get(id)[0];
    // One bounded display read per allowlisted row. F/H are deliberately left
    // out of the response; no other row's customer details are read.
    const fields = sheet.getRange(row, 2, 1, 8).getDisplayValues()[0];
    if (!Array.isArray(fields) || fields.length !== 8) throw new Error('list_data_invalid');
    const values = [fields[0], fields[1], fields[2], fields[3], fields[5], fields[7]], limits = [64, 200, 40, 1000, 120, 120];
    if (values.some(function(value, index) {
      return typeof value !== 'string' || value.length > limits[index];
    })) throw new Error('list_data_invalid');
    const result = {caseId: id, date: fields[0], name: fields[1], phone: fields[2], address: fields[3], model: fields[5], status: fields[7]};
    const state = repeat && repeatState_(repeat, id);
    if (state && state.active && result.status === DISPATCH_STATUS) {
      result.status = REPEAT_WAITING;
      result.repeatRequestId = state.active;
      result.repeatRequestedAt = state.requested;
    }
    return result;
  });
}

function syncDispatchListResult_(config, cases) {
  return syncResult_({ok: true, sheetId: config.id, schema: DISPATCH_LIST_SCHEMA,
    pickupSheetId: PICKUP_SPREADSHEET_ID, pickupSheetGid: PICKUP_SHEET_ID, cases: cases});
}

function doPost(e) {
  let request, config;
  try {
    if (!e || !e.postData || typeof e.postData.contents !== 'string' ||
        e.postData.contents.length > 120000 ||
        (e.postData.type || '').split(';')[0] !== 'application/json') return syncFail_('invalid_request');
    request = JSON.parse(e.postData.contents);
    config = syncProperties_();
  } catch (_) { return syncFail_('configuration_or_invalid_request'); }
  if (!request || typeof request !== 'object' || Array.isArray(request) ||
      typeof request.secret !== 'string' || request.secret.length > 128 ||
      !syncEqual_(request.secret, config.secret)) return syncFail_('unauthorized');
  if (request.sheetId !== config.id) return syncFail_('sheet_mismatch');
  if (request.operation === 'pingPayment' || request.operation === 'upsertPayment') {
    return productionPaymentDispatch_(request, config);
  }
  const allowed = ['ping', 'pingPickup', 'pingPickupDispatch'].indexOf(request.operation) >= 0 ? ['operation', 'secret', 'sheetId'] :
    request.operation === 'readPickupDispatch' ? ['operation', 'query', 'secret', 'sheetId'] :
    request.operation === 'updatePickupDispatch' ? ['dispatch', 'operation', 'secret', 'sheetId'] :
      ['case', 'operation', 'secret', 'sheetId'];
  if (JSON.stringify(Object.keys(request).sort()) !== JSON.stringify(allowed.sort())) {
    return syncFail_('invalid_request');
  }
  if (request.operation === 'ping') {
    try {
      syncSheet_(config);
      return syncResult_({ok: true, sheetId: config.id, schema: SYNC_SCHEMA});
    } catch (_) { return syncFail_('schema_mismatch'); }
  }
  if (request.operation === 'pingPickup') {
    try {
      syncPickupSheet_();
      return syncPickupResult_(config, {enabled: true});
    } catch (_) { return syncFail_('pickup_schema_mismatch'); }
  }
  if (request.operation === 'pingPickupDispatch') {
    try {
      syncDispatchSheet_();
      return syncDispatchResult_(config, {enabled: true});
    } catch (_) { return syncFail_('dispatch_schema_mismatch'); }
  }
  if (request.operation === 'readPickupDispatch' && !syncValidateDispatchQuery_(request.query)) return syncFail_('list_data_invalid');
  if (request.operation === 'updatePickupDispatch' && !syncValidateDispatch_(request.dispatch)) return syncFail_('invalid_request');
  if (['updatePickupDispatch', 'readPickupDispatch'].indexOf(request.operation) < 0 &&
      (['upsert', 'upsertPickup'].indexOf(request.operation) < 0 || !syncValidateCase_(request.case))) {
    return syncFail_('invalid_case');
  }
  if (request.operation === 'upsertPickup' && !syncPickupEligible_(request.case)) return syncFail_('invalid_pickup_case');
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(15000)) return syncFail_('busy');
  try {
    if (request.operation === 'readPickupDispatch') return syncDispatchListResult_(config, syncDispatchList_(request.query));
    if (request.operation === 'updatePickupDispatch') {
      const result = repeatDispatchUpdate_(request.dispatch, config);
      return syncDispatchResult_(config, {caseId: request.dispatch.caseId, commandId: request.dispatch.commandId,
        status: result.status, action: result.action});
    }
    if (request.operation === 'upsertPickup') {
      const pickupAction = syncPickupUpsert_(request.case, config);
      return syncPickupResult_(config, {caseId: request.case.id, revision: request.case.revision, action: pickupAction});
    }
    const action = syncUpsert_(request.case, config);
    return syncResult_({ok: true, sheetId: config.id, schema: SYNC_SCHEMA,
      caseId: request.case.id, revision: request.case.revision, action: action});
  } catch (error) {
    const allowedErrors = ['schema_mismatch', 'duplicate_case_id', 'ownership_conflict', 'revision_conflict', 'pickup_schema_mismatch', 'pickup_case_missing',
      'dispatch_schema_mismatch', 'dispatch_case_missing', 'dispatch_status_conflict', 'dispatch_validation_conflict',
      'list_schema_mismatch', 'list_case_missing', 'list_data_invalid'];
    return syncFail_(allowedErrors.indexOf(error.message) >= 0 ? error.message : 'sync_failed');
  } finally { lock.releaseLock(); }
}

function doGet() { return syncFail_('post_required'); }

const PROD_PAYMENT_SCHEMA = 'petpivot-payment-production-v1';
const PROD_PAYMENT_SPREADSHEET_ID = '1C5gGI4cL4lgw-GqSXRcQuicM2e5FvDHp-bnfqpMcnqI';
const PROD_PAYMENT_TIME_ZONE = 'Asia/Taipei';
const PROD_PAYMENT_SHEET_NAME = '付款狀態';
const PROD_PAYMENT_META_NAME = '_payment_sync_production';
const PROD_PAYMENT_HEADERS = [
  '案件編號', '申請人', '付款狀態', '維修費', '派車回收費', '應付合計',
  '已付金額', '付款訂單編號', '付款完成時間', '最近核對時間', '報價版本', '同步版本'
];
const PROD_PAYMENT_META_HEADERS = ['case_id', 'revision', 'payload_sha256'];
const PROD_PAYMENT_FIELDS = [
  'caseId', 'name', 'status', 'repairFee', 'pickupFee', 'amountDue',
  'amountPaid', 'orderNumber', 'paidAt', 'checkedAt', 'quoteVersion', 'revision'
];
const PROD_PAYMENT_STATUSES = ['待核價', '待付款', '已付款', '需人工核對', '免付款', '退款需處理', '已退款'];

function productionPaymentFailure_(code) {
  const error = new Error(code);
  error.productionPaymentCode = code;
  throw error;
}

function productionPaymentJson_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}

function productionPaymentObject_(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function productionPaymentExactKeys_(value, keys) {
  if (!productionPaymentObject_(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = keys.slice().sort();
  return actual.length === expected.length && actual.every(function (key, i) { return key === expected[i]; });
}

function productionPaymentSecretEqual_(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  let difference = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  for (let i = 0; i < length; i++) difference |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return difference === 0;
}

function productionPaymentSafeInteger_(value, minimum) {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum;
}

// Validate provider/server timestamps. Never invent a paid-at time.
function productionPaymentTimestamp_(value, allowEmpty) {
  if (value === '' && allowEmpty) return true;
  if (typeof value !== 'string' || value.length > 40) return false;
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!parts) return false;
  const year = Number(parts[1]), month = Number(parts[2]), day = Number(parts[3]);
  if (year < 2000 || year > 2200 || month < 1 || month > 12 || day < 1 ||
      day > new Date(Date.UTC(year, month, 0)).getUTCDate() ||
      Number(parts[4]) > 23 || Number(parts[5]) > 59 || Number(parts[6]) > 59) return false;
  if (parts[8] !== 'Z' && (Number(parts[10]) > 14 || Number(parts[11]) > 59 ||
      (Number(parts[10]) === 14 && Number(parts[11]) !== 0))) return false;
  return Number.isFinite(new Date(value).getTime());
}

function productionPaymentValidate_(input) {
  if (!productionPaymentExactKeys_(input, PROD_PAYMENT_FIELDS)) productionPaymentFailure_('invalid_payment');
  if (typeof input.caseId !== 'string' || !/^R\d{8}-\d{4,8}$/.test(input.caseId)) productionPaymentFailure_('invalid_payment');
  if (typeof input.name !== 'string' || input.name.trim() !== input.name || input.name.length < 1 ||
      input.name.length > 120 || /[\u0000-\u001f\u007f]/.test(input.name)) productionPaymentFailure_('invalid_payment');
  if (typeof input.status !== 'string' || PROD_PAYMENT_STATUSES.indexOf(input.status) === -1) productionPaymentFailure_('invalid_payment');
  ['repairFee', 'pickupFee', 'amountDue', 'amountPaid'].forEach(function (key) {
    if (!productionPaymentSafeInteger_(input[key], 0)) productionPaymentFailure_('invalid_payment');
  });
  if ((input.pickupFee !== 0 && input.pickupFee !== 350 && input.pickupFee !== 700) ||
      !Number.isSafeInteger(input.repairFee + input.pickupFee) ||
      input.amountDue !== input.repairFee + input.pickupFee || input.amountPaid > input.amountDue) productionPaymentFailure_('invalid_payment');
  if (!productionPaymentSafeInteger_(input.revision, 1) ||
      !productionPaymentSafeInteger_(input.quoteVersion, input.status === '待核價' ? 0 : 1)) productionPaymentFailure_('invalid_payment');
  if (typeof input.orderNumber !== 'string' ||
      (input.orderNumber !== '' && !/^[A-Za-z0-9_-]{1,64}$/.test(input.orderNumber))) productionPaymentFailure_('invalid_payment');
  if (!productionPaymentTimestamp_(input.paidAt, true) ||
      !productionPaymentTimestamp_(input.checkedAt, ['已付款', '退款需處理', '已退款'].indexOf(input.status) === -1)) productionPaymentFailure_('invalid_payment');
  if (input.status === '已付款') {
    if (input.amountDue <= 0 || input.amountPaid !== input.amountDue || input.orderNumber === '') productionPaymentFailure_('invalid_payment');
  } else if (input.status === '退款需處理' || input.status === '已退款') {
    if (input.orderNumber === '') productionPaymentFailure_('invalid_payment');
  } else if (input.amountPaid !== 0 || input.paidAt !== '') productionPaymentFailure_('invalid_payment');
  if (input.status === '免付款' && input.amountDue !== 0) productionPaymentFailure_('invalid_payment');
  const output = {};
  PROD_PAYMENT_FIELDS.forEach(function (key) { output[key] = input[key]; });
  return output;
}

function productionPaymentHash_(payment) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(payment), Utilities.Charset.UTF_8)
    .map(function (byte) { return ('0' + ((byte + 256) % 256).toString(16)).slice(-2); }).join('');
}

function productionPaymentRichText_(value) {
  return SpreadsheetApp.newRichTextValue().setText(String(value)).build();
}

function productionPaymentEnsureSheet_(spreadsheet, name, headers, hidden) {
  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet) sheet = spreadsheet.insertSheet(name);
  if (sheet.getMaxColumns() < headers.length) sheet.insertColumnsAfter(sheet.getMaxColumns(), headers.length - sheet.getMaxColumns());
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, headers.length).setRichTextValues([headers.map(productionPaymentRichText_)]);
    sheet.setFrozenRows(1);
  } else {
    const actual = sheet.getRange(1, 1, 1, headers.length).getDisplayValues()[0];
    if (actual.some(function (value, i) { return value !== headers[i]; })) productionPaymentFailure_('header_mismatch');
  }
  if (hidden) sheet.hideSheet();
  return sheet;
}

function productionPaymentFindRow_(sheet, caseId) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return 0;
  const matches = [];
  sheet.getRange(2, 1, lastRow - 1, 1).getDisplayValues().forEach(function (row, i) {
    if (String(row[0]).trim() === caseId) matches.push(i + 2);
  });
  if (matches.length > 1) productionPaymentFailure_('duplicate_case');
  return matches.length ? matches[0] : 0;
}

function productionPaymentNextRow_(sheet) {
  const row = Math.max(sheet.getLastRow() + 1, 2);
  if (row > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(), row - sheet.getMaxRows());
  return row;
}

function productionPaymentAck_(sheetId, payment, action, gid) {
  return {ok: true, sheetId: sheetId, spreadsheetId: sheetId, schema: PROD_PAYMENT_SCHEMA,
    gid: gid, caseId: payment.caseId, revision: payment.revision, status: payment.status,
    action: action, payloadHash: productionPaymentHash_(payment)};
}

function productionPaymentCellValues_(payment) {
  return PROD_PAYMENT_FIELDS.map(function (key) {
    if (key === 'paidAt' || key === 'checkedAt') return payment[key] === '' ? '' : new Date(payment[key]);
    return payment[key];
  });
}

function productionPaymentRowMatches_(sheet, row, payment) {
  const range = sheet.getRange(row, 1, 1, PROD_PAYMENT_FIELDS.length);
  const actual = range.getValues()[0];
  if (range.getFormulas()[0].some(function (formula) { return formula !== ''; })) return false;
  const expected = productionPaymentCellValues_(payment);
  return expected.every(function (value, i) {
    // Date values remain native dates in typed DATE_TIME columns. Compare the
    // provider instant rather than locale-dependent display strings.
    if (value instanceof Date) return actual[i] instanceof Date && actual[i].getTime() === value.getTime();
    return typeof actual[i] === typeof value && actual[i] === value;
  });
}

function productionPaymentWriteRow_(sheet, row, payment) {
  // Never transiently put text into native CURRENCY/DATE_TIME/DOUBLE columns.
  // Every customer-supplied string is literal RichText, even =,+,-,@ names.
  sheet.getRange(row, 1, 1, 3).setRichTextValues([[
    productionPaymentRichText_(payment.caseId), productionPaymentRichText_(payment.name), productionPaymentRichText_(payment.status)
  ]]);
  sheet.getRange(row, 4, 1, 4).setValues([[
    payment.repairFee, payment.pickupFee, payment.amountDue, payment.amountPaid
  ]]);
  sheet.getRange(row, 8).setRichTextValues([[productionPaymentRichText_(payment.orderNumber)]]);
  sheet.getRange(row, 9, 1, 2).setValues([[
    payment.paidAt === '' ? '' : new Date(payment.paidAt),
    payment.checkedAt === '' ? '' : new Date(payment.checkedAt)
  ]]);
  sheet.getRange(row, 11, 1, 2).setValues([[payment.quoteVersion, payment.revision]]);
  SpreadsheetApp.flush();
  if (!productionPaymentRowMatches_(sheet, row, payment)) productionPaymentFailure_('readback_mismatch');
}

function productionPaymentUpsert_(spreadsheet, sheetId, payment) {
  if (sheetId !== PROD_PAYMENT_SPREADSHEET_ID || spreadsheet.getId() !== PROD_PAYMENT_SPREADSHEET_ID) productionPaymentFailure_('sheet_mismatch');
  if (spreadsheet.getSpreadsheetTimeZone() !== PROD_PAYMENT_TIME_ZONE) productionPaymentFailure_('timezone_mismatch');
  productionPaymentMainCase_(spreadsheet, payment);
  const sheet = productionPaymentEnsureSheet_(spreadsheet, PROD_PAYMENT_SHEET_NAME, PROD_PAYMENT_HEADERS, false);
  const meta = productionPaymentEnsureSheet_(spreadsheet, PROD_PAYMENT_META_NAME, PROD_PAYMENT_META_HEADERS, true);
  const existingRow = productionPaymentFindRow_(sheet, payment.caseId);
  const existingMetaRow = productionPaymentFindRow_(meta, payment.caseId);
  const hash = productionPaymentHash_(payment);
  if (existingMetaRow) {
    if (!existingRow) productionPaymentFailure_('payment_row_missing');
    const prior = meta.getRange(existingMetaRow, 1, 1, 3).getValues()[0];
    const priorRevision = typeof prior[1] === 'number' ? prior[1] : Number(prior[1]);
    if (!Number.isSafeInteger(priorRevision) || priorRevision < 1 || !/^[0-9a-f]{64}$/.test(String(prior[2]))) productionPaymentFailure_('metadata_invalid');
    if (payment.revision < priorRevision) return productionPaymentAck_(sheetId, payment, 'stale', sheet.getSheetId());
    if (payment.revision === priorRevision) {
      if (hash !== String(prior[2])) productionPaymentFailure_('revision_conflict');
      // Metadata cannot certify a manually cleared or changed payment row.
      // Replaying the same trusted projection repairs its owned cells.
      if (productionPaymentRowMatches_(sheet, existingRow, payment)) return productionPaymentAck_(sheetId, payment, 'unchanged', sheet.getSheetId());
    }
  }
  const row = existingRow || productionPaymentNextRow_(sheet);
  productionPaymentWriteRow_(sheet, row, payment);
  const metaRow = existingMetaRow || productionPaymentNextRow_(meta);
  meta.getRange(metaRow, 1, 1, 3).setRichTextValues([[productionPaymentRichText_(payment.caseId), productionPaymentRichText_(payment.revision), productionPaymentRichText_(hash)]]);
  SpreadsheetApp.flush();
  const confirmedMeta = meta.getRange(metaRow, 1, 1, 3).getValues()[0];
  if (confirmedMeta[0] !== payment.caseId || String(confirmedMeta[1]) !== String(payment.revision) ||
      confirmedMeta[2] !== hash || !productionPaymentRowMatches_(sheet, row, payment)) productionPaymentFailure_('readback_mismatch');
  productionPaymentMainCase_(spreadsheet, payment);
  return productionPaymentAck_(sheetId, payment, existingRow ? 'updated' : 'inserted', sheet.getSheetId());
}


// Production-only extension. The original repair/pickup/dispatch routes above
// retain their record schemas and field ownership. Main-sheet physical column
// order is resolved by exact header names. Only the dedicated payment tab and
// its hidden version metadata are written by this extension.
function productionPaymentMainCase_(spreadsheet, payment) {
  const sheet = spreadsheet.getSheetByName('維修案件');
  let columns;
  try { columns = syncMainColumns_(sheet); }
  catch (_) { productionPaymentFailure_('main_schema_mismatch'); }
  const rows = syncFindRows_(sheet, payment.caseId, columns.id);
  if (rows.length !== 1) productionPaymentFailure_(rows.length ? 'duplicate_case' : 'main_case_missing');
  const name = sheet.getRange(rows[0], columns.name).getDisplayValues()[0][0];
  if (name !== payment.name) productionPaymentFailure_('case_identity_mismatch');
}

function productionPaymentOpen_(config) {
  if (config.id !== PROD_PAYMENT_SPREADSHEET_ID) productionPaymentFailure_('sheet_mismatch');
  const spreadsheet = SpreadsheetApp.openById(PROD_PAYMENT_SPREADSHEET_ID);
  if (spreadsheet.getId() !== PROD_PAYMENT_SPREADSHEET_ID) productionPaymentFailure_('sheet_mismatch');
  if (spreadsheet.getSpreadsheetTimeZone() !== PROD_PAYMENT_TIME_ZONE) productionPaymentFailure_('timezone_mismatch');
  return spreadsheet;
}

function productionPaymentDispatch_(request, config) {
  let lock, acquired = false;
  try {
    if (request.schema !== PROD_PAYMENT_SCHEMA) productionPaymentFailure_('schema_mismatch');
    const keys = ['secret', 'sheetId', 'schema', 'operation'];
    if (request.operation === 'upsertPayment') keys.push('payment');
    if (!productionPaymentExactKeys_(request, keys)) productionPaymentFailure_('invalid_request');
    const spreadsheet = productionPaymentOpen_(config);
    if (request.operation === 'pingPayment') {
      // A verification ping performs no writes, creates no tabs or metadata,
      // and never changes native tables, sharing, script properties or scopes.
      const main = spreadsheet.getSheetByName('維修案件');
      try { syncMainColumns_(main); }
      catch (_) { productionPaymentFailure_('main_schema_mismatch'); }
      const sheet = spreadsheet.getSheetByName(PROD_PAYMENT_SHEET_NAME);
      if (sheet && (sheet.getMaxColumns() < PROD_PAYMENT_HEADERS.length ||
          JSON.stringify(sheet.getRange(1, 1, 1, PROD_PAYMENT_HEADERS.length).getDisplayValues()[0]) !== JSON.stringify(PROD_PAYMENT_HEADERS))) productionPaymentFailure_('header_mismatch');
      return syncResult_({ok: true, sheetId: config.id, spreadsheetId: config.id,
        schema: PROD_PAYMENT_SCHEMA, sheetName: PROD_PAYMENT_SHEET_NAME,
        gid: sheet ? sheet.getSheetId() : null, exists: !!sheet});
    }
    if (request.operation !== 'upsertPayment') productionPaymentFailure_('invalid_operation');
    const payment = productionPaymentValidate_(request.payment);
    lock = LockService.getScriptLock();
    acquired = lock.tryLock(10000);
    if (!acquired) productionPaymentFailure_('busy');
    return syncResult_(productionPaymentUpsert_(spreadsheet, config.id, payment));
  } catch (error) {
    return syncResult_({ok: false, schema: PROD_PAYMENT_SCHEMA,
      error: error && error.productionPaymentCode || 'sync_failed'});
  } finally {
    if (acquired) lock.releaseLock();
  }
}

function setupProductionPaymentSheet() {
  // Explicit operator setup only. Normal pingPayment remains read-only.
  const config = syncProperties_();
  const spreadsheet = productionPaymentOpen_(config);
  syncSheet_(config);
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) productionPaymentFailure_('busy');
  try {
    const sheet = productionPaymentEnsureSheet_(spreadsheet, PROD_PAYMENT_SHEET_NAME, PROD_PAYMENT_HEADERS, false);
    productionPaymentEnsureSheet_(spreadsheet, PROD_PAYMENT_META_NAME, PROD_PAYMENT_META_HEADERS, true);
    SpreadsheetApp.flush();
    return {ok: true, sheetId: config.id, spreadsheetId: config.id,
      schema: PROD_PAYMENT_SCHEMA, sheetName: PROD_PAYMENT_SHEET_NAME, gid: sheet.getSheetId()};
  } finally { lock.releaseLock(); }
}

// The physical dispatch status (I) remains the first trip's staff-owned
// status. A second trip is an explicit request with a separate, one-use ID.
const REPEAT_WAITING = '待再次派車';
const REPEAT_ACTION = '申請再次派車';
const REPEAT_FIELDS = ['首次派車時間', REPEAT_ACTION, '再次派車進度', '最近再次申請時間'];
const REPEAT_JOURNAL = '_pickup_repeat_history';
const REPEAT_LOG_HEADERS = ['案件編號', '事件', '事件時間 UTC', '再次申請識別碼', '指令識別碼'];
const REPEAT_FEATURE_KEY = 'PICKUP_REPEAT_VERSION';

function repeatUuid_(value) {
  return typeof value === 'string' && value.length === 36 &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
}

function repeatCheckboxRule_() {
  return SpreadsheetApp.newDataValidation().requireCheckbox().setAllowInvalid(false).build();
}

function repeatColumns_(sheet, setup) {
  const headers = sheet.getRange(1, 1, 1, sheet.getMaxColumns()).getDisplayValues()[0];
  if (setup && REPEAT_FIELDS.every(function(h) {return headers.indexOf(h) === -1;})) {
    // Include data below empty headers so installation never takes a staff column.
    const start = sheet.getLastColumn() + 1, missing = start + REPEAT_FIELDS.length - 1 - sheet.getMaxColumns();
    if (missing > 0) sheet.insertColumnsAfter(sheet.getMaxColumns(), missing);
    sheet.getRange(1, start, 1, REPEAT_FIELDS.length).setValues([REPEAT_FIELDS]);
    return repeatColumns_(sheet, false);
  }
  const columns = REPEAT_FIELDS.map(function(h) {
    const i = headers.indexOf(h);
    if (i < 9 || i !== headers.lastIndexOf(h)) throw new Error('dispatch_schema_mismatch');
    return i + 1;
  });
  return {first:columns[0], action:columns[1], status:columns[2], requested:columns[3]};
}

function repeatJournal_(create) {
  const book = SpreadsheetApp.openById(PROD_PAYMENT_SPREADSHEET_ID);
  let journal = book.getSheetByName(REPEAT_JOURNAL);
  if (!journal && create) {
    journal = book.insertSheet(REPEAT_JOURNAL);
    journal.getRange(1,1,1,REPEAT_LOG_HEADERS.length).setValues([REPEAT_LOG_HEADERS]);
    journal.hideSheet();
  }
  if (!journal || JSON.stringify(journal.getRange(1,1,1,REPEAT_LOG_HEADERS.length).getDisplayValues()[0]) !== JSON.stringify(REPEAT_LOG_HEADERS)) {
    throw new Error('dispatch_schema_mismatch');
  }
  return journal;
}

function repeatLoad_(sheet, columns, journal) {
  const records = new Map(), last = journal.getLastRow();
  if (last > 1) journal.getRange(2,1,last-1,REPEAT_LOG_HEADERS.length).getDisplayValues().forEach(function(row) {
    if (!records.has(row[0])) records.set(row[0], []);
    records.get(row[0]).push(row);
  });
  return {sheet:sheet, columns:columns, journal:journal, records:records};
}

function repeatBook_(sheet) {
  if (PropertiesService.getScriptProperties().getProperty(REPEAT_FEATURE_KEY) !== '1') return null;
  return repeatLoad_(sheet, repeatColumns_(sheet, false), repeatJournal_(false));
}

function repeatState_(book, id) {
  const state = {first:'', legacy:false, active:'', latest:'', requested:'', completed:'', cancelled:false};
  (book.records.get(id) || []).forEach(function(row) {
    const kind=row[1], stamp=row[2], rid=row[3];
    if (kind === '首次派車' && !state.first) state.first = stamp;
    if (kind === '既有派車') state.legacy = true;
    if (kind === '再次申請') Object.assign(state,{active:rid, latest:rid, requested:stamp, completed:'', cancelled:false});
    if (rid && rid === state.active && (kind === '再次派車' || kind === '撤回再次申請')) {
      Object.assign(state,{active:'', completed:stamp, cancelled:kind==='撤回再次申請'});
    }
  });
  return state;
}

function repeatAppend_(book, id, kind, iso, rid, command) {
  const record = [id, kind, iso, rid || '', command || ''];
  const next = book.journal.getLastRow()+1;
  syncEnsureRows_(book.journal,next);
  book.journal.getRange(next,1,1,record.length).setNumberFormat('@').setRichTextValues([
    record.map(function(s) { return SpreadsheetApp.newRichTextValue().setText(s).build(); })]);
  SpreadsheetApp.flush();
  if (!book.records.has(id)) book.records.set(id,[]);
  book.records.get(id).push(record);
}

function repeatDate_(iso) {
  return iso ? Utilities.formatDate(new Date(iso), 'Asia/Taipei', 'yyyy/MM/dd HH:mm:ss') : '';
}

function repeatProject_(book, id) {
  const rows=syncPickupRows_(book.sheet,id);
  if (rows.length !== 1) throw new Error(rows.length?'duplicate_case_id':'dispatch_case_missing');
  const row=rows[0], state=repeatState_(book,id), cols=book.columns;
  function show(col,value) {
    const cell=book.sheet.getRange(row,col);
    if (cell.getFormula() || cell.getDisplayValue() !== value) syncWriteText_(book.sheet,row,col,value);
  }
  show(cols.first, state.first ? repeatDate_(state.first) : state.legacy ? '未留存' : '');
  show(cols.status, state.active ? REPEAT_WAITING : state.cancelled ? '再次申請已撤回' :
       state.completed ? '已再次派車 '+repeatDate_(state.completed) : '');
  show(cols.requested, repeatDate_(state.requested));
  return row;
}

function repeatPrepareFirst_(sheet,id,command) {
  const book=repeatBook_(sheet);
  if (!book) return;
  const state=repeatState_(book,id), records=book.records.get(id) || [];
  if (state.first || state.legacy || records.some(function(r) {return r[1]==='首次回報中' && r[4]===command;})) return;
  repeatAppend_(book,id,'首次回報中',new Date().toISOString(),'',command);
}

function repeatCaptureFirst_(sheet,id,command) {
  const book=repeatBook_(sheet);
  if (!book) return;
  const state=repeatState_(book,id), records=book.records.get(id) || [];
  if (!state.first && !state.legacy) {
    const receipt=records.find(function(r) {return r[1]==='首次回報中' && r[4]===command;});
    repeatAppend_(book,id,receipt?'首次派車':'既有派車',receipt?receipt[2]:'','',command);
  }
  repeatProject_(book,id);
}

function repeatAllowed_(id) {
  const main=SpreadsheetApp.openById(PROD_PAYMENT_SPREADSHEET_ID);
  const meta=main.getSheetByName('_pickup_sync'), cases=main.getSheetByName('維修案件');
  if (!meta || !cases) return false;
  const members=syncPickupRows_(meta,id);
  if (members.length!==1 || meta.getRange(members[0],6).getDisplayValue()!=='synced') return false;
  const cols=syncMainColumns_(cases), rows=syncFindRows_(cases,id,cols.id);
  if (rows.length!==1 || cases.getRange(rows[0],cols.shipping).getDisplayValue()!=='由客服派遣物流回收' ||
      ['已取消','不維修退回','已結案'].includes(cases.getRange(rows[0],cols.status).getDisplayValue())) return false;
  const sheet=main.getSheetByName(PROD_PAYMENT_SHEET_NAME);
  if (!sheet || JSON.stringify(sheet.getRange(1,1,1,PROD_PAYMENT_HEADERS.length).getDisplayValues()[0])!==JSON.stringify(PROD_PAYMENT_HEADERS)) return false;
  const matches=syncPickupRows_(sheet,id);
  if (!matches.length) return true; // Older cases have no payment projection; server rechecks its authoritative workflow.
  if (matches.length!==1) return false;
  const cell=sheet.getRange(matches[0],1,1,PROD_PAYMENT_HEADERS.length);
  if (cell.getFormulas()[0].some(Boolean)) return false;
  const values=cell.getValues()[0];
  return (values[2]==='免付款' && values[5]===0) ||
    (values[2]==='已付款' && Number.isSafeInteger(values[5]) && values[5]>0 && values[5]===values[6] && !!values[7]);
}

function repeatResetCheck_(book,id) {
  const rows=syncPickupRows_(book.sheet,id);
  if (rows.length===1) {
    const cell=book.sheet.getRange(rows[0],book.columns.action);
    if (!cell.getFormula() && cell.getValue()===true) cell.clearContent();
  }
}

function repeatDispatchUpdate_(dispatch,config) {
  const sheet=syncDispatchSheet_(), book=repeatBook_(sheet), id=dispatch.caseId;
  const state=book && repeatState_(book,id), rid=dispatch.repeatRequestId;
  if (!rid && !(state && state.active)) return {status:DISPATCH_STATUS, action:syncDispatchUpdate_(dispatch,config)};
  const rows=syncPickupRows_(sheet,id);
  if (rows.length!==1) throw new Error(rows.length?'duplicate_case_id':'dispatch_case_missing');
  const cell=sheet.getRange(rows[0],DISPATCH_COLUMN), physical=cell.getDisplayValue();
  const stale={status:state && state.active && physical===DISPATCH_STATUS ? REPEAT_WAITING : physical===DISPATCH_STATUS ? DISPATCH_STATUS : '', action:'stale_request'};
  if (!book || !rid || rid!==state.latest || physical!==DISPATCH_STATUS || cell.getFormula()) return stale;
  if (state.completed && !state.cancelled) {
    repeatProject_(book,id);
    return {status:DISPATCH_STATUS,action:'unchanged'};
  }
  if (rid!==state.active || !repeatAllowed_(id)) return stale;
  repeatAppend_(book,id,'再次派車',new Date().toISOString(),rid,dispatch.commandId);
  repeatProject_(book,id);
  return {status:DISPATCH_STATUS,action:'updated'};
}

function setupPickupRepeatDispatch() {
  return setupPickupRepeatDispatchFromEvidence_({});
}

function setupPickupRepeatDispatchFromEvidence_(evidence) {
  const lock=LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('busy');
  try {
    const sheet=syncDispatchSheet_(), columns=repeatColumns_(sheet,true);
    const book=repeatLoad_(sheet,columns,repeatJournal_(true)), n=sheet.getLastRow()-1;
    const ids=n>0?sheet.getRange(2,1,n,1).getDisplayValues():[];
    const statuses=n>0?sheet.getRange(2,DISPATCH_COLUMN,n,1).getDisplayValues():[];
    Object.keys(evidence).forEach(function(id) {
      if (!syncDispatchCaseId_(id) || !productionPaymentTimestamp_(evidence[id],false) ||
          new Date(evidence[id]).getTime()>Date.now() || ids.filter(function(row){return row[0]===id;}).length!==1) throw new Error('invalid_evidence');
      const current=repeatState_(book,id).first;
      if (current && new Date(current).getTime()!==new Date(evidence[id]).getTime()) throw new Error('conflicting_evidence');
    });
    ids.forEach(function(entry,index) {
      const id=entry[0];
      if (!syncDispatchCaseId_(id)) return;
      const first=evidence[id], state=repeatState_(book,id);
      if (!state.first && first) repeatAppend_(book,id,'首次派車',new Date(first).toISOString(),'','verified-history');
      else if (!state.first && !state.legacy && statuses[index][0]===DISPATCH_STATUS) repeatAppend_(book,id,'既有派車','','','');
      if (book.records.has(id)) repeatProject_(book,id);
    });
    // Apply only validation: writing FALSE down the grid would inflate getLastRow()
    // and break automatic pickup appends. Apply the same rule after any grid growth.
    sheet.getRange(2,columns.action,sheet.getMaxRows()-1,1).setDataValidation(repeatCheckboxRule_());
    const existing=ScriptApp.getProjectTriggers().some(function(t) {return t.getHandlerFunction()==='onPickupRepeatDispatchEdit' &&
      t.getTriggerSourceId()===PICKUP_SPREADSHEET_ID && t.getEventType()===ScriptApp.EventType.ON_EDIT;});
    if (!existing) ScriptApp.newTrigger('onPickupRepeatDispatchEdit').forSpreadsheet(PICKUP_SPREADSHEET_ID).onEdit().create();
    PropertiesService.getScriptProperties().setProperty(REPEAT_FEATURE_KEY,'1');
    return {ok:true,firstColumn:columns.first,requestColumn:columns.action};
  } finally {lock.releaseLock();}
}

function onPickupRepeatDispatchEdit(e) {
  if (!e || !e.source || e.source.getId()!==PICKUP_SPREADSHEET_ID || !e.range ||
      e.range.getSheet().getSheetId()!==PICKUP_SHEET_ID || e.range.getNumColumns()!==1 ||
      e.range.getRow()<2) return;
  const col=e.range.getColumn(), first=e.range.getRow();
  const lock=LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('busy');
  try {
    const sheet=syncDispatchSheet_(), book=repeatBook_(sheet);
    if (!book || (col!==book.columns.action && col!==DISPATCH_COLUMN)) return;
    const last=Math.min(sheet.getLastRow(), first+e.range.getNumRows()-1);
    for (let row=first;row<=last;row++) {
      repeatHandleRowEdit_(book,row,col,e.range.getNumRows()===1?e:null);
    }
  } finally {lock.releaseLock();}
}

function repeatHandleRowEdit_(book,row,col,singleEvent) {
    const sheet=book.sheet, cell=sheet.getRange(row,col), value=cell.getValue(), checked=value===true;
    // Ignore a delayed single-cell event when the user already changed that cell again.
    if (cell.getFormula() || (singleEvent && String(value).toUpperCase()!==String(singleEvent.value || '').toUpperCase())) return;
    const id=sheet.getRange(row,1).getDisplayValue(), rows=syncPickupRows_(sheet,id);
    if (!syncDispatchCaseId_(id) || rows.length!==1) {
      if (col===book.columns.action && checked) {
        sheet.getRange(row,book.columns.status).setValue('請確認案件編號唯一且完整'); cell.clearContent();
      }
      return;
    }
    const state=repeatState_(book,id);
    if (col===DISPATCH_COLUMN) {
      if (value===DISPATCH_STATUS && (!singleEvent || singleEvent.oldValue!==DISPATCH_STATUS) && !state.first && !state.legacy) {
        repeatAppend_(book,id,'首次派車',new Date().toISOString(),'','sheet-edit');
      } else if (state.active && value!==DISPATCH_STATUS) {
        repeatAppend_(book,id,'撤回再次申請',new Date().toISOString(),state.active,'sheet-edit');
      }
      repeatProject_(book,id);
    } else if (checked) {
      const physical=sheet.getRange(row,DISPATCH_COLUMN);
      const eligible=!physical.getFormula() && physical.getDisplayValue()===DISPATCH_STATUS && repeatAllowed_(id);
      if (!eligible) {
        sheet.getRange(row,book.columns.status).setValue('未受理，請確認派車狀態、寄送方式及付款狀態');
      } else {
        if (!state.first && !state.legacy) repeatAppend_(book,id,'既有派車','','','');
        if (!state.active) repeatAppend_(book,id,'再次申請',new Date().toISOString(),Utilities.getUuid(),'');
        repeatProject_(book,id);
      }
      // Blank, validated checkbox is unchecked and available for the next cycle.
      repeatResetCheck_(book,id);
    }
}
