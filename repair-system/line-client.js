/* Identity and receipt proofs are checked by this site's server. */
window.repairLine = (() => {
  let ready = false;
  let config = {};
  let granted = [];
  let officialEntryExpiresAt = 0;
  const sentCases = new Set();
  const inFlight = new Map();
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function request(path, data) {
    const response = await fetch(path, {method:data?'POST':'GET',
      headers:data?{'Content-Type':'application/json'}:{},
      body:data?JSON.stringify(data):undefined});
    if (!response.ok) throw new Error('LINE 回傳確認暫時無法完成。');
    return response.json();
  }
  async function initialize(settings) {
    config = settings;
    ready = false;
    granted = [];
    officialEntryExpiresAt = 0;
    if (config.demo || !config.liffId || location.pathname === '/admin') return false;
    if (!window.liff) await new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://static.line-scdn.net/liff/edge/2/sdk.js';
      script.onload = resolve;
      script.onerror = () => reject(new Error('LINE 元件載入失敗，請重新開啟申請頁。'));
      document.head.appendChild(script);
    });
    // Desktop and ordinary browsers use this site's server-side LINE Login.
    // Do not initialize an external LIFF session or replace a web-login session.
    if (!liff.isInClient()) return false;
    await liff.init({ liffId: config.liffId });
    ready = true;
    if (config.autoLoginPaused) return false;
    if (liff.isLoggedIn()) {
      try { granted = await liff.permission.getGrantedAll(); } catch (_) { granted = []; }
      return authenticate();
    }
    return false;
  }
  async function authenticate(explicit = false) {
    const idToken = liff.getIDToken();
    if (!idToken) throw new Error('請授權 LINE 登入的 openid 權限。');
    await request('/api/liff-login', explicit ? {idToken,explicit:true} : {idToken});
    config.autoLoginPaused = false;
    await refreshEntry();
    return true;
  }
  async function refreshEntry() {
    officialEntryExpiresAt = 0;
    if (config.autoLoginPaused || !ready || !liff.isInClient() || !liff.isLoggedIn()) return false;
    try { granted = await liff.permission.getGrantedAll(); } catch (_) { granted = []; }
    // Read the entry only after LIFF has restored its redirect URL. The server
    // binds this official-account entry to the verified LINE identity.
    const ticket = new URL(location.href).searchParams.get('entry');
    try {
      const entry = await request('/api/line-entry', ticket ? {ticket} : undefined);
      officialEntryExpiresAt = entry.officialEntry ? entry.expiresAt : 0;
    } catch (_) { officialEntryExpiresAt = 0; }
    return canAutoReturn();
  }
  async function login() {
    if (!ready || !liff.isInClient()) return false;
    if (!liff.isLoggedIn()) {
      const ticket = new URL(location.href).searchParams.get('entry');
      liff.login({redirectUri: location.origin + '/' + (ticket ? '?entry='+encodeURIComponent(ticket) : '')});
      return true;
    }
    granted = await liff.permission.getGrantedAll();
    await authenticate(true);
    return true;
  }
  function canAutoReturn() {
    return !config.autoLoginPaused && ready && liff.isInClient() && liff.getContext()?.type === 'utou'
      && granted.includes('chat_message.write') && officialEntryExpiresAt > Date.now()/1000;
  }
  function requirementReason() {
    if (config.autoLoginPaused) return '你已登出，請先按「使用 LINE 登入」再開始申請。';
    if (!ready || !liff.isInClient()) return '請從客服 LINE 回覆的「開始維修申請」開啟表單。';
    if (liff.getContext()?.type !== 'utou') return '請從客服官方 LINE 的一對一聊天室開啟表單。';
    if (!granted.includes('chat_message.write')) return 'LINE 訊息傳送權限尚未完成，請重新開啟客服表單入口並完成授權。';
    if (officialEntryExpiresAt && officialEntryExpiresAt <= Date.now()/1000) return '這個表單入口已過期，請向客服 LINE 重新取得新入口。';
    return '請向客服 LINE 重新取得新入口，再開始填寫申請。';
  }
  async function waitForSummary(id) {
    for (let attempt=0; attempt<8; attempt++) {
      const receipt = await request('/api/line-receipt?id='+encodeURIComponent(id));
      if (receipt.summaryReceivedAt) return {state:'received',receivedAt:receipt.summaryReceivedAt};
      if (attempt<7) await pause(1000);
    }
    return {state:'pending'};
  }
  async function sendSummary(c, text) {
    if (config.demo) return {state:'demo'};
    if (!canAutoReturn()) return {state:'entry-required'};
    if (!config.webhookReady) return {state:'unconfirmed'};
    try {
      // An existing summary receipt prevents duplicates.
      const receipt = await request('/api/line-receipt?id='+encodeURIComponent(c.id));
      if (receipt.summaryReceivedAt) return {state:'received',receivedAt:receipt.summaryReceivedAt};
      if (sentCases.has(c.id)) return await waitForSummary(c.id);

      // Refresh the entry claim before sending. It verifies official entry and
      // identity, while the signed webhook below confirms actual OA receipt.
      await refreshEntry();
      if (!canAutoReturn()) return {state:'entry-required'};
      await liff.sendMessages([{type:'text',text}]);
      sentCases.add(c.id);
      return await waitForSummary(c.id);
    } catch (_) {
      return {state:sentCases.has(c.id)?'pending':'failed'};
    }
  }
  function returnReference(c, text) {
    if (inFlight.has(c.id)) return inFlight.get(c.id);
    const task = sendSummary(c,text).finally(() => inFlight.delete(c.id));
    inFlight.set(c.id,task);
    return task;
  }
  function clearSession() {
    config.autoLoginPaused = true;
    officialEntryExpiresAt = 0;
    granted = [];
    sentCases.clear();
  }
  function isInClient() { return !!window.liff?.isInClient(); }
  return {initialize,login,refreshEntry,canAutoReturn,requirementReason,returnReference,clearSession,isInClient};
})();
