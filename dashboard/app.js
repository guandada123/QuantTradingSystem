/* ============================================================
   QuantTradingSystem Dashboard — 共享工具库 v2.0
   API客户端 / WebSocket / 工具函数 / Toast
   ============================================================ */

// ---------- 运行时配置（自动适配部署环境） ----------
const APP_CONFIG = (() => {
  const proto = window.location.protocol;
  const hostname = window.location.hostname;
  // 开发模式：静态服务器端口 != 8000 时，后端API指向8000
  const apiPort = (window.location.port && window.location.port !== '8000') ? '8000' : (window.location.port || '');
  const apiHost = apiPort ? `${hostname}:${apiPort}` : window.location.host;
  const wsProto = proto === 'https:' ? 'wss:' : 'ws:';
  return {
    apiBase: proto + '//' + apiHost,
    wsBase: wsProto + '//' + apiHost,
  };
})();

const CONFIG = {
  API: {
    // Unified API base for strategy-service
    strategy: APP_CONFIG.apiBase + '/api',
    execution: APP_CONFIG.apiBase + '/api/v1/execution',
    scheduler:  APP_CONFIG.apiBase + '/api/v1/scheduler',
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
  return Number(val) > 0 ? 'bull' : Number(val) < 0 ? 'bear' : '';
}

function directionText(val) {
  if (val == null || isNaN(val)) return '';
  return Number(val) > 0 ? '上涨' : Number(val) < 0 ? '下跌' : '持平';
}

function directionArrow(val) {
  if (val == null || isNaN(val)) return '';
  return Number(val) > 0 ? '▲' : Number(val) < 0 ? '▼' : '—';
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

// ---------- ARIA Live Region (Screen Reader Announcements) ----------
const AriaLive = {
  _el: null,

  _ensure() {
    if (!this._el) {
      this._el = document.createElement('div');
      this._el.setAttribute('aria-live', 'polite');
      this._el.setAttribute('aria-atomic', 'true');
      this._el.className = 'sr-only';
      document.body.appendChild(this._el);
    }
  },

  announce(msg) {
    this._ensure();
    // Clear then set to trigger re-announcement
    this._el.textContent = '';
    requestAnimationFrame(() => {
      this._el.textContent = msg;
    });
  },
};

// ---------- Confirm Dialog ----------
function showConfirm(title, message, onConfirm, onCancel) {
  const existing = document.querySelector('.modal-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.setAttribute('role', 'alertdialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'confirm-title');
  overlay.setAttribute('aria-describedby', 'confirm-msg');

  overlay.innerHTML = `
    <div class="modal-box" role="document">
      <h3 id="confirm-title"></h3>
      <p id="confirm-msg" style="font-size:var(--text-sm);color:var(--color-text-secondary);margin-bottom:var(--space-4)"></p>
      <div class="modal-actions">
        <button class="btn" id="confirm-cancel">取消</button>
        <button class="btn btn-error" id="confirm-ok" autofocus>确认</button>
      </div>
    </div>`;

  document.body.appendChild(overlay);
  // Use textContent to prevent XSS injection
  overlay.querySelector('#confirm-title').textContent = title;
  overlay.querySelector('#confirm-msg').textContent = message;
  const okBtn = overlay.querySelector('#confirm-ok');
  const cancelBtn = overlay.querySelector('#confirm-cancel');

  function close() { overlay.remove(); document.removeEventListener('keydown', escHandler); if (onCancel) onCancel(); }
  function escHandler(e) { if (e.key === 'Escape') close(); }
  okBtn.addEventListener('click', () => { overlay.remove(); document.removeEventListener('keydown', escHandler); if (onConfirm) onConfirm(); });
  cancelBtn.addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  document.addEventListener('keydown', escHandler);
  okBtn.focus();
}

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
        try {
          this.isConnected = true;
          this._dispatch('connect', {});
        } catch (e) {
          console.warn(`[WS:${this.name}] onopen handler error:`, e);
        }
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
        try {
          this.isConnected = false;
          this._dispatch('disconnect', {});
        } catch (e) {
          console.warn(`[WS:${this.name}] onclose handler error:`, e);
        }
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

// ---------- Theme Toggle (Light / Dark / System — 3-mode cycle) ----------
// Uses event delegation — no inline onclick needed, CSP-safe
(function() {
  const KEY = 'qt_theme';

  function getPreferred() {
    const stored = localStorage.getItem(KEY);
    if (stored) return stored;
    return 'system'; // 默认跟随系统
  }

  function resolveSystem() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = theme === 'system' ? 'light dark' : theme;
    localStorage.setItem(KEY, theme);
  }

  function toggleTheme() {
    const current = localStorage.getItem(KEY) || 'system';
    const cycle = { light: 'dark', dark: 'system', system: 'light' };
    apply(cycle[current] || 'system');
  }

  // Event delegation — handles all .theme-toggle buttons, no inline onclick needed
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.theme-toggle');
    if (btn) toggleTheme();
  });

  apply(getPreferred());

  // Public API (for programmatic use)
  if (!window.QT) window.QT = {};
  // eslint-disable-next-line no-unused-vars
  window.QT.toggleTheme = toggleTheme;

  // Listen for system theme changes — auto-update when in system mode
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
    if (localStorage.getItem(KEY) === 'system') {
      // Re-apply to trigger color-scheme update
      apply('system');
    }
  });
})();

// ---------- Mobile Navigation Toggle ----------
(function() {
  document.addEventListener('DOMContentLoaded', function() {
    const toggle = document.querySelector('.nav-toggle');
    const nav = document.querySelector('.topbar nav');
    const overlay = document.querySelector('.mobile-nav-overlay');
    if (!toggle || !nav) return;

    function open() { toggle.classList.add('open'); nav.classList.add('open'); if (overlay) overlay.classList.add('open'); }
    function close() { toggle.classList.remove('open'); nav.classList.remove('open'); if (overlay) overlay.classList.remove('open'); }

    toggle.addEventListener('click', function() {
      toggle.classList.contains('open') ? close() : open();
    });

    if (overlay) {
      overlay.addEventListener('click', close);
    }

    // Close on nav link click
    nav.querySelectorAll('a').forEach(function(a) {
      a.addEventListener('click', close);
    });

    // Close on Escape
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && toggle.classList.contains('open')) close();
    });
  });
})();

// ---------- Skeleton → Content Transition ----------
window.QT = window.QT || {};
window.QT.transitionFromSkeleton = function(containerSelector) {
  const container = typeof containerSelector === 'string' ? document.querySelector(containerSelector) : containerSelector;
  if (!container) return;
  const skeletons = container.querySelectorAll('.skeleton-card, .skeleton');
  if (skeletons.length === 0) return;
  skeletons.forEach(function(el) {
    if (el.classList.contains('skeleton-card')) {
      el.classList.add('fade-out');
    } else {
      el.style.opacity = '0';
      el.style.transition = 'opacity 200ms ease';
    }
  });
  setTimeout(function() {
    skeletons.forEach(function(el) { el.remove(); });
  }, 350);
};

// ---------- Value Pulse on Data Update ----------
window.QT.pulseValue = function(el, newValue, formatter) {
  if (!el) return;
  const formatted = formatter ? formatter(newValue) : newValue;
  if (el.textContent === formatted) return;
  el.textContent = formatted;
  el.classList.add('value-pulse');
  setTimeout(function() { el.classList.remove('value-pulse'); }, 350);
};

// ---------- Refresh Progress Bar ----------
window.QT.startRefresh = function() {
  let bar = document.querySelector('.refresh-indicator');
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'refresh-indicator';
    document.body.appendChild(bar);
  }
  bar.classList.add('loading');
  bar.classList.remove('done');
};

window.QT.endRefresh = function() {
  const bar = document.querySelector('.refresh-indicator');
  if (!bar) return;
  bar.classList.remove('loading');
  bar.classList.add('done');
  setTimeout(function() { bar.classList.remove('done'); }, 600);
};

// ============================================================
// Three.js Particle Background — Premium cosmic dust effect
// Lazy-loaded, theme-aware, performance-optimized, ~2ms per frame
// ============================================================
QT.ParticleSystem = (() => {
  const STATE = { running: false, instance: null };

  class ParticleInstance {
    constructor(container) {
      this.container = container;
      this.w = window.innerWidth;
      this.h = window.innerHeight;
      this.animId = null;
      this.disposed = false;
      this._boundResize = this._onResize.bind(this);
    }

    async init() {
      // Respect reduced motion
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;

      const THREE = await this._loadThree();
      if (!THREE) return false;
      this.THREE = THREE;

      const { width: w, height: h } = this;

      // Scene with transparent bg
      this.scene = new THREE.Scene();

      // Orthographic camera — no perspective distortion, better for bg
      this.camera = new THREE.OrthographicCamera(-w / 2, w / 2, h / 2, -h / 2, 0.1, 1000);
      this.camera.position.z = 1;

      // Renderer — low-power, transparent, behind content
      this.renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: 'low-power',
      });
      this.renderer.setSize(w, h);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
      this.renderer.domElement.style.cssText =
        'position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none;display:block;';
      this.container.appendChild(this.renderer.domElement);

      this._createParticles();
      window.addEventListener('resize', this._boundResize);
      this._animate();
      return true;
    }

    async _loadThree() {
      try {
        const mod = await import(
          'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js'
        );
        return mod;
      } catch (e) {
        console.debug('[Particles] Three.js 加载跳过:', e.message);
        return null;
      }
    }

    _createParticles() {
      const THREE = this.THREE;
      const count = 120;
      const color = new THREE.Color(this._getBrandColor());

      // Random positions in a cylinder volume
      const positions = new Float32Array(count * 3);
      const sizes = new Float32Array(count);
      for (let i = 0; i < count; i++) {
        const angle = Math.random() * Math.PI * 2;
        const radius = Math.random() * Math.min(this.w, this.h) * 0.5;
        positions[i * 3] = Math.cos(angle) * radius;
        positions[i * 3 + 1] = (Math.random() - 0.5) * this.h * 0.7;
        positions[i * 3 + 2] = (Math.random() - 0.5) * 80;
        sizes[i] = Math.random() * 3 + 1.5;
      }

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

      const material = new THREE.PointsMaterial({
        color,
        size: 3,
        transparent: true,
        opacity: 0.35,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true,
        depthWrite: false,
      });

      this.particles = new THREE.Points(geometry, material);
      this.scene.add(this.particles);

      // Save initial Y positions for gentle bob animation
      this._baseY = new Float32Array(positions.slice(1, positions.length, 3));
      for (let i = 0; i < count; i++) {
        this._baseY[i] = positions[i * 3 + 1];
      }
    }

    _getBrandColor() {
      const val = getComputedStyle(document.documentElement)
        .getPropertyValue('--color-brand-400').trim();
      return val || '#7F77DD';
    }

    _animate(time) {
      if (this.disposed) return;
      this.animId = requestAnimationFrame((t) => this._animate(t));

      if (this.particles) {
        // Gentle rotation + Y bob
        this.particles.rotation.z += 0.0003;
        const positions = this.particles.geometry.attributes.position.array;
        for (let i = 0; i < positions.length / 3; i++) {
          const idx = i * 3 + 1;
          positions[idx] = this._baseY[i] + Math.sin((time || 0) * 0.001 + i) * 1.5;
        }
        this.particles.geometry.attributes.position.needsUpdate = true;
      }

      this.renderer.render(this.scene, this.camera);
    }

    _onResize() {
      this.w = window.innerWidth;
      this.h = window.innerHeight;
      this.camera.left = -this.w / 2;
      this.camera.right = this.w / 2;
      this.camera.top = this.h / 2;
      this.camera.bottom = -this.h / 2;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(this.w, this.h);
    }

    updateColor() {
      if (this.particles && this.THREE) {
        this.particles.material.color.set(new this.THREE.Color(this._getBrandColor()));
      }
    }

    dispose() {
      this.disposed = true;
      if (this.animId) cancelAnimationFrame(this.animId);
      window.removeEventListener('resize', this._boundResize);
      if (this.renderer) {
        this.renderer.dispose();
        const el = this.renderer.domElement;
        if (el && el.parentNode) el.parentNode.removeChild(el);
      }
      this.scene = null;
      this.renderer = null;
      this.particles = null;
    }
  }

  return {
    async mount(containerId = 'particle-bg') {
      if (STATE.running) return;
      const el = document.getElementById(containerId);
      if (!el) return;
      STATE.running = true;
      STATE.instance = new ParticleInstance(el);
      const ok = await STATE.instance.init();
      if (!ok) { STATE.running = false; return; }

      // Watch theme changes → update particle color
      STATE._mo = new MutationObserver(() => STATE.instance.updateColor());
      STATE._mo.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
      });
    },

    dispose() {
      if (STATE.instance) STATE.instance.dispose();
      if (STATE._mo) STATE._mo.disconnect();
      STATE.running = false;
      STATE.instance = null;
    },
  };
})();

// ============================================================
// ECharts Global Registry — 全生命周期跟踪 / SPA 安全回收
// ============================================================
QT.charts = (() => {
  const _instances = new Set();

  /**
   * 创建并注册 ECharts 实例到全局跟踪表
   * @param {HTMLElement|string} dom - DOM 元素或 ID
   * @param {object} [opts] - ECharts init 选项
   * @returns {object} chart 实例
   */
  function init(dom, opts) {
    const el = typeof dom === 'string' ? document.getElementById(dom) : dom;
    if (!el) return null;
    const chart = echarts.init(el, opts);
    _instances.add(chart);

    // 拦截 dispose 以自动从跟踪表移除
    const origDispose = chart.dispose.bind(chart);
    chart.dispose = function () {
      _instances.delete(chart);
      return origDispose();
    };
    return chart;
  }

  /** 释放所有活跃图表实例 */
  function disposeAll() {
    _instances.forEach((c) => {
      try { c.dispose(); } catch (e) { /* 已销毁 */ }
    });
    _instances.clear();
  }

  /** 调整所有活跃图表尺寸 */
  function resizeAll() {
    _instances.forEach((c) => {
      try { c.resize(); } catch (e) { /* 已销毁 */ }
    });
  }

  /** 当前活跃图表数（调试用） */
  function size() { return _instances.size; }

  /**
   * 从跟踪表中移除实例（不销毁）
   * 在 ChartUtils.dispose 等外部 dispose 路径调用
   */
  function unregister(chart) {
    _instances.delete(chart);
  }

  return { init, disposeAll, resizeAll, size, unregister };
})();

// ============================================================
// Scroll Animator — Intersection Observer for animate-on-scroll
// ============================================================
QT.ScrollAnimator = (() => {
  let observer = null;

  function init(root = document) {
    if (observer) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('on-screen');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

    root.querySelectorAll('.animate-on-scroll').forEach((el) => observer.observe(el));
  }

  function observe(el) {
    if (observer) observer.observe(el);
  }

  return { init, observe };
})();

// ============================================================
// Ripple Effect — premium button click animation
// ============================================================
QT.RippleEffect = (() => {
  function init(root = document) {
    root.querySelectorAll('.btn:not([data-ripple])').forEach((btn) => {
      btn.setAttribute('data-ripple', '1');
      btn.addEventListener('click', function (e) {
        // Remove existing ripples
        const old = this.querySelector('.ripple-effect');
        if (old) old.remove();

        const rect = this.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = e.clientX - rect.left - size / 2;
        const y = e.clientY - rect.top - size / 2;

        const ripple = document.createElement('span');
        ripple.className = 'ripple-effect';
        ripple.style.cssText =
          `width:${size}px;height:${size}px;left:${x}px;top:${y}px;`;
        this.appendChild(ripple);

        // Auto-remove after animation
        setTimeout(() => ripple.remove(), 600);
      });
    });
  }

  return { init };
})();

// ============================================================
// Table Horizontal Scroll Indicator
// ============================================================
QT.TableScrollHint = (() => {
  function init(root = document) {
    root.querySelectorAll('.data-table-wrapper').forEach((wrapper) => {
      const check = () => {
        wrapper.classList.toggle('can-scroll',
          wrapper.scrollWidth > wrapper.clientWidth &&
          wrapper.scrollLeft < wrapper.scrollWidth - wrapper.clientWidth - 5
        );
      };
      wrapper.addEventListener('scroll', check);
      // Check on load (after content is rendered)
      requestAnimationFrame(check);
    });
  }
  return { init };
})();

// ============================================================
// Premium Dashboard Init — call on every page after DOM ready
// ============================================================
QT.initPremium = function () {
  // Micro-interactions (non-blocking, fire-and-forget)
  requestAnimationFrame(() => {
    QT.ScrollAnimator.init();
    QT.RippleEffect.init();
    QT.TableScrollHint.init();
  });
};

// Auto-init on DOMContentLoaded
document.addEventListener('DOMContentLoaded', QT.initPremium);
