/* ============================================================
   QuantTradingSystem Dashboard — 共享工具库 v2.0
   API客户端 / WebSocket / 工具函数 / Toast
   ============================================================ */

// ---------- 运行时配置（自动适配部署环境） ----------
const APP_CONFIG = (() => {
  const proto = window.location.protocol;
  const host = window.location.host;
  const wsProto = proto === 'https:' ? 'wss:' : 'ws:';
  return {
    apiBase: proto + '//' + host,
    wsBase: wsProto + '//' + host,
  };
})();

const CONFIG = {
  API: {
    strategy: APP_CONFIG.apiBase + '/api/strategy',
    execution: APP_CONFIG.apiBase + '/api/execution',
    scheduler:  APP_CONFIG.apiBase + '/api/scheduler',
  },
  WS: {
    strategy: APP_CONFIG.wsBase + '/ws/strategy',
    execution: APP_CONFIG.wsBase + '/ws/execution',
    scheduler: APP_CONFIG.wsBase + '/ws/scheduler',
    legacy: APP_CONFIG.wsBase + '/ws',
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

// ---------- WebSocket 状态持久化层（跨页面导航保活） ----------
const WSStateStore = {
  _prefix: 'qt_ws_',

  _key(service, eventType) {
    return `${this._prefix}${service}_${eventType}`;
  },

  /** 缓存最新 WS 消息数据 */
  set(service, eventType, data) {
    try {
      sessionStorage.setItem(this._key(service, eventType), JSON.stringify({
        data,
        ts: Date.now(),
      }));
    } catch (_) { /* quota exceeded, skip */ }
  },

  /** 获取缓存数据（不超过 30s 过期） */
  get(service, eventType, maxAgeMs = 30000) {
    try {
      const raw = sessionStorage.getItem(this._key(service, eventType));
      if (!raw) return null;
      const entry = JSON.parse(raw);
      if (Date.now() - entry.ts > maxAgeMs) {
        sessionStorage.removeItem(this._key(service, eventType));
        return null;
      }
      return entry.data;
    } catch (_) { return null; }
  },

  /** 获取该 service 所有缓存的 key */
  keys(service) {
    const results = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (key && key.startsWith(`${this._prefix}${service}_`)) {
        results.push(key.replace(`${this._prefix}${service}_`, ''));
      }
    }
    return results;
  },

  /** 清除某 service 的所有缓存 */
  clear(service) {
    this.keys(service).forEach(k => {
      sessionStorage.removeItem(this._key(service, k));
    });
  },
};

// ---------- WebSocket 管理器（多连接 + 状态持久化） ----------
const wsManagers = {};

function getWSManager(service = 'strategy') {
  if (!wsManagers[service]) {
    const url = CONFIG.WS[service] || CONFIG.WS.legacy;
    wsManagers[service] = new WebSocketManager(url, service);
    // 恢复上次页面保留的缓存数据，立即派发给已注册的 listener
    wsManagers[service]._restoreCache();
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
    // v2.1: 快速重连（500ms），页面导航后几乎无感
    this.reconnectDelay = 500;
    this.isConnected = false;
    this._messageCount = 0;
    this._cachedTypes = new Set();  // 记录已缓存的 type

    // Tab 可见性感知：切后台暂停重连，切前台立即恢复
    this._bindVisibility();
    this.connect();
  }

  /** 页面可见性变化时，暂停/恢复连接 */
  _bindVisibility() {
    const handler = () => {
      if (document.hidden) {
        // 切后台：暂停重连定时器
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      } else {
        // 切前台：如果断开则立即尝试重连
        if (!this.isConnected && !this.reconnectTimer) {
          this._scheduleReconnect();
        }
      }
    };
    document.addEventListener('visibilitychange', handler);
  }

  /** 恢复上次会话缓存的数据（页面导航后立即有数据展示） */
  _restoreCache() {
    const cachedTypes = WSStateStore.keys(this.name);
    cachedTypes.forEach(eventType => {
      const cached = WSStateStore.get(this.name, eventType);
      if (cached) {
        this._dispatch(eventType, cached);
      }
    });
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
          this._messageCount++;

          // 持久化：将消息按 type 缓存到 sessionStorage
          const eventType = data.type || 'message';
          WSStateStore.set(this.name, eventType, data);
          this._cachedTypes.add(eventType);

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
    // 页面不可见时不重连
    if (document.hidden) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
  }

  on(event, callback) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(callback);

    // 如果该 event 已有缓存，立即推送给新注册的 listener
    const cached = WSStateStore.get(this.name, event);
    if (cached) {
      try { callback(cached); } catch (_) {}
    }

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
