/* ============================================================
   QuantTradingSystem Dashboard — 共享工具库 v2.0
   API客户端 / WebSocket / 工具函数 / Toast
   ============================================================ */

// ---------- 配置 ----------
const CONFIG = {
  API: {
    strategy: 'http://localhost:8000',
    execution: 'http://localhost:8001',
    scheduler:  'http://localhost:8002',
  },
  WS: {
    strategy: 'ws://localhost:8000/ws/strategy',
    execution: 'ws://localhost:8001/ws/execution',
    scheduler: 'ws://localhost:8002/ws/scheduler',
    legacy: 'ws://localhost:8000/ws',
  },
  POLL_INTERVAL: 10000,
};

// ---------- 工具函数 ----------
function formatMoney(val) {
  if (val == null || isNaN(val)) return '--';
  return '¥' + Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPct(val, digits = 2) {
  if (val == null || isNaN(val)) return '--';
  const v = Number(val) * 100;
  return (v >= 0 ? '+' : '') + v.toFixed(digits) + '%';
}

function formatNum(val) {
  if (val == null || isNaN(val)) return '--';
  return Number(val).toLocaleString('zh-CN');
}

function colorClass(val) {
  if (val == null) return '';
  return Number(val) > 0 ? 'up' : Number(val) < 0 ? 'down' : '';
}

function timeAgo(dateStr) {
  if (!dateStr) return '--';
  const d = new Date(dateStr);
  const now = new Date();
  const diff = Math.floor((now - d) / 1000);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
  return d.toLocaleDateString('zh-CN');
}

// ---------- Toast ----------
const Toast = {
  _el: null,
  _timer: null,

  _ensure() {
    if (!this._el) {
      this._el = document.createElement('div');
      this._el.className = 'toast';
      document.body.appendChild(this._el);
    }
  },

  show(msg, type = 'success', duration = 2500) {
    this._ensure();
    this._el.textContent = msg;
    this._el.className = `toast toast-${type} show`;
    clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      this._el.classList.remove('show');
    }, duration);
  },

  success(msg) { this.show(msg, 'success'); },
  error(msg) { this.show(msg, 'error', 3500); },
  warning(msg) { this.show(msg, 'warning', 3000); },
};

// ---------- API 客户端 ----------
const API = {
  async _fetch(base, path, options = {}) {
    const url = base + path;
    const opts = {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    };
    try {
      const resp = await fetch(url, opts);
      if (!resp.ok) {
        const err = await resp.text().catch(() => 'Unknown error');
        throw new Error(`HTTP ${resp.status}: ${err}`);
      }
      return await resp.json();
    } catch (e) {
      if (e.name === 'TypeError') throw new Error('网络连接失败');
      throw e;
    }
  },

  strategy(path, opts) { return this._fetch(CONFIG.API.strategy, path, opts); },
  execution(path, opts) { return this._fetch(CONFIG.API.execution, path, opts); },
  scheduler(path, opts) { return this._fetch(CONFIG.API.scheduler, path, opts); },
};

// ---------- WebSocket 管理器（多连接支持） ----------
const wsManagers = {};

function getWSManager(service = 'strategy') {
  if (!wsManagers[service]) {
    const url = CONFIG.WS[service] || CONFIG.WS.legacy;
    wsManagers[service] = new WebSocketManager(url, service);
  }
  return wsManagers[service];
}

function getWSManagerLegacy() {
  return getWSManager('legacy');
}

class WebSocketManager {
  constructor(url, name) {
    this.url = url;
    this.name = name || 'default';
    this.ws = null;
    this.listeners = new Map();
    this.reconnectTimer = null;
    this.reconnectDelay = 3000;
    this.isConnected = false;
    this.connect();
  }

  connect() {
    try {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = () => {
        this.isConnected = true;
        this._dispatch('connect', {});
      };
      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this._dispatch('message', data);
          if (data.type) this._dispatch(data.type, data);
        } catch (e) {
          console.warn('WS parse error:', e);
        }
      };
      this.ws.onclose = () => {
        this.isConnected = false;
        this._dispatch('disconnect', {});
        this._scheduleReconnect();
      };
      this.ws.onerror = () => {
        this.isConnected = false;
      };
    } catch (e) {
      this._scheduleReconnect();
    }
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
  }

  on(event, callback) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(callback);
    return () => this.off(event, callback);
  }

  off(event, callback) {
    const list = this.listeners.get(event);
    if (list) {
      const idx = list.indexOf(callback);
      if (idx >= 0) list.splice(idx, 1);
    }
  }

  _dispatch(event, data) {
    const list = this.listeners.get(event);
    if (list) list.forEach(cb => { try { cb(data); } catch (e) { console.warn('WS handler error:', e); } });
  }

  send(data) {
    if (this.ws && this.isConnected) {
      this.ws.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  }

  close() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.isConnected = false;
  }
}
