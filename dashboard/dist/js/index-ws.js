(function() {
  const ws = window.getWSManager ? getWSManager() : null;
  if (!ws) return;

  const idxOrder = { '000001.SH': 0, '399001.SZ': 1, '399006.SZ': 2, '000688.SH': 3, '000300.SH': 4, '000905.SH': 5 };
  const idxNames = ['上证指数', '深证成指', '创业板指', '科创50', '沪深300', '中证500'];

  function updateWSStatus(connected) {
    const dot = document.getElementById('ws-dot');
    const txt = document.getElementById('ws-status-text');
    const ttxt = document.getElementById('ticker-status-text');
    if (dot) {
      dot.className = 'conn-dot ' + (connected ? 'connected' : 'disconnected');
    }
    if (txt) txt.textContent = connected ? '实时' : '离线';
    if (ttxt) ttxt.textContent = connected ? 'WebSocket 实时行情' : 'WebSocket 断开，使用 HTTP 轮询';
  }

  ws.on('index_update', function(data) {
    var list = data.data && data.data.indices ? data.data.indices : (Array.isArray(data.data) ? data.data : []);
    list.forEach(function(idx) {
      var pos = idxOrder[idx.ts_code];
      if (pos === undefined) return;
      var priceEl = document.getElementById('idx-price-' + pos);
      var pctEl = document.getElementById('idx-pct-' + pos);
      if (idx.price && priceEl) priceEl.textContent = Number(idx.price).toLocaleString('zh-CN', { minimumFractionDigits: 2 });
      if (idx.pct_chg !== undefined && pctEl) {
        var up = idx.pct_chg >= 0;
        pctEl.textContent = (up ? '+' : '') + idx.pct_chg.toFixed(2) + '%';
        pctEl.className = 'idx-pct ' + (up ? 'bull' : 'bear');
      }
    });
    var tickerTime = document.getElementById('ticker-time');
    if (tickerTime) tickerTime.textContent = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  });

  ws.on('connect', function() { updateWSStatus(true); });
  ws.on('disconnect', function() { updateWSStatus(false); });
  if (ws.isConnected) updateWSStatus(true);
})();
