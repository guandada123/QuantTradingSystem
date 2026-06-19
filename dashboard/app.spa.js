(function() {
'use strict';

const { createApp, ref, shallowRef, reactive, computed, onMounted, onUnmounted, nextTick, watch, toRaw } = Vue;

/* ================================================================
   Route manager — 更新导航 active 状态
   ================================================================ */
function updateActiveNav(route) {
  document.querySelectorAll('#main-nav a').forEach(function(a) {
    var r = a.getAttribute('data-route');
    var active = r === route || (route === '/' && r === '/') || (r !== '/' && route.startsWith(r));
    a.classList.toggle('active', active);
    if (active) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
}

/* ================================================================
   ChartUtils — 图表增强工具（全局共享）
   - 自动 DataZoom 缩放能力
   - Window Resize 自适应
   - 增强 Tooltip 格式
   - 动态主题色（从 CSS 变量读取）
   ================================================================ */
const ChartUtils = {
  /* 创建图表实例，自动绑定 resize 监听
   * @param {string} domId - DOM 元素 ID
   * @param {object} store - { current: null } 用于存储实例引用
   * @returns {object} chart 实例
   */
  create(domId, store) {
    const dom = document.getElementById(domId);
    if (!dom) return null;
    if (store && store.current) { store.current.dispose(); store.current = null; }
    const chart = window.QT && QT.charts ? QT.charts.init(dom) : echarts.init(dom);
    const resizeFn = function() { try { chart.resize(); } catch(e) {} };
    window.addEventListener('resize', resizeFn);
    chart._resizeFn = resizeFn;
    if (store) store.current = chart;
    return chart;
  },

  /* 销毁图表，移除 resize 监听
   * @param {object} store - { current: null } 或 chart 实例
   */
  dispose(store) {
    const chart = store && store.current ? store.current : store;
    if (!chart) return;
    // 从全局注册表移除（ChartManager.init 挂载了代理 dispose，会自清理）
    if (window.QT && QT.charts) QT.charts.unregister(chart);
    if (chart._resizeFn) window.removeEventListener('resize', chart._resizeFn);
    try { chart.dispose(); } catch(e) {}
    if (store) store.current = null;
  },

  /* 获取 CSS 设计令牌值 */
  css(name) {
    try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); } catch(e) { return ''; }
  },

  /* 通用 DataZoom 配置（用于时间序列） */
  dataZoom: [
    { type: 'inside', start: 0, end: 100 },
    { type: 'slider', start: 0, end: 100, height: 18, bottom: 8,
      borderColor: 'rgba(102,126,234,0.2)',
      fillerColor: 'rgba(102,126,234,0.1)',
      handleStyle: { color: '#667eea' },
      textStyle: { fontSize: 10 }
    }
  ],

  /* 通用 Tooltip 配置 */
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(0,0,0,0.78)',
    borderColor: 'rgba(255,255,255,0.08)',
    borderWidth: 1,
    textStyle: { color: '#e5e7eb', fontSize: 12 },
    extraCssText: 'border-radius:10px;padding:12px 16px;box-shadow:0 8px 24px rgba(0,0,0,0.25);backdrop-filter:blur(8px)'
  },

  /* 通用 Grid 配置 */
  grid: { left: 55, right: 20, top: 35, bottom: 50 },

  /* 主题色 */
  get brandColor() { return this.css('--color-brand-400') || '#667eea'; },
  get textColor() { return this.css('--color-text-primary') || '#e5e7eb'; },
  get textSecondary() { return this.css('--color-text-secondary') || '#8b949e'; },
  get bullColor() { return this.css('--color-bull') || '#d4302f'; },
  get bearColor() { return this.css('--color-bear') || '#1ca01c'; },
  get bgSurface() { return this.css('--color-bg-surface') || '#1e2030'; },
};

/* ================================================================
   1. PageHome — 首页（仪表盘）
   ================================================================ */
const PageHome = {
  template: `
    <div class="page-home">
      <div class="hero-section">
        <div class="welcome-bar">
          <h2>交易仪表盘</h2>
          <div class="date-display" id="date-display">--</div>
        </div>
        <div class="metrics-grid" style="grid-template-columns:repeat(3,1fr)">
          <div class="metric-card-big glass-card magnetic">
            <div class="metric-icon" style="background:rgba(83,74,183,0.10);color:var(--color-brand-600)">💼</div>
            <div class="metric-body">
              <div class="metric-label">持仓市值</div>
              <div class="metric-number" id="summary-market-value">--</div>
              <div class="metric-subtitle">-- 只持仓</div>
            </div>
          </div>
          <div class="metric-card-big" id="pnl-card">
            <div class="metric-icon" style="background:rgba(83,74,183,0.10);color:var(--color-brand-600)">📊</div>
            <div class="metric-body">
              <div class="metric-label">今日盈亏</div>
              <div class="metric-number" id="summary-pnl">--</div>
              <div class="metric-subtitle">待计算</div>
            </div>
          </div>
          <div class="metric-card-big glass-card magnetic">
            <div class="metric-icon" style="background:rgba(83,74,183,0.10);color:var(--color-brand-600)">📋</div>
            <div class="metric-body">
              <div class="metric-label">活跃订单</div>
              <div class="metric-number" id="summary-orders">--</div>
              <div class="metric-subtitle">待处理</div>
            </div>
          </div>
        </div>
      </div>
      <section class="page-section" aria-label="功能导航" style="margin-top:0">
        <div class="func-grid-v2">
          <a href="#/account" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(83,74,183,0.08);color:var(--color-brand-600)" aria-hidden="true">💰</div>
            <div class="fc-title">账户概览</div>
            <div class="fc-desc">持仓明细与收益曲线</div>
          </a>
          <a href="#/orders" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(34,197,94,0.08);color:#16a34a" aria-hidden="true">📈</div>
            <div class="fc-title">交易下单</div>
            <div class="fc-desc">快速下单与仓位管理</div>
          </a>
          <a href="#/trade-analysis" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(245,158,11,0.08);color:#d97706" aria-hidden="true">📊</div>
            <div class="fc-title">交易分析</div>
            <div class="fc-desc">胜率盈亏分布图表</div>
          </a>
          <a href="#/backtest" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(37,99,235,0.08);color:#2563eb" aria-hidden="true">🧪</div>
            <div class="fc-title">策略回测</div>
            <div class="fc-desc">多策略参数优化</div>
          </a>
          <a href="#/strategies" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(139,92,246,0.08);color:#7c3aed" aria-hidden="true">🎯</div>
            <div class="fc-title">策略市场</div>
            <div class="fc-desc">创建对比交易策略</div>
          </a>
          <a href="#/stock-selection" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(236,72,153,0.08);color:#db2777" aria-hidden="true">🤖</div>
            <div class="fc-title">AI 选股</div>
            <div class="fc-desc">智能选股与评分</div>
          </a>
          <a href="#/review-analysis" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(20,184,166,0.08);color:#0d9488" aria-hidden="true">📝</div>
            <div class="fc-title">每日复盘</div>
            <div class="fc-desc">AI 市场回顾建议</div>
          </a>
          <a href="#/alerts" class="func-card-v2 magnetic">
            <div class="fc-icon" style="background:rgba(239,68,68,0.08);color:#ef4444" aria-hidden="true">🔔</div>
            <div class="fc-title">告警管理</div>
            <div class="fc-desc">监控告警与配置</div>
          </a>
        </div>
      </section>
    </div>
  `,
  setup() {
    let summaryInterval = null;

    function formatMoney(v) {
      if (v === undefined || v === null) return '--';
      return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function formatPct(v, d) { d = d || 2; if (v === undefined || v === null) return '--'; return (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%'; }

    async function fetchSummary() {
      try {
        if (window.QT) QT.startRefresh();
        const posResp = await API.execution('/v1/positions/summary?account_id=REAL_001');
        if (posResp.code === 0) {
          const d = posResp.data;
          const mvEl = document.getElementById('summary-market-value');
          if (mvEl) {
            if (QT) QT.pulseValue(mvEl, formatMoney(d.total_market_value));
          }
          const pnlEl = document.getElementById('summary-pnl');
          if (pnlEl) {
            const v = d.total_profit_loss || 0;
            if (QT) QT.pulseValue(pnlEl, (v >= 0 ? '+' : '') + formatMoney(v));
            pnlEl.className = 'metric-number ' + (v > 0 ? 'text-bull' : v < 0 ? 'text-bear' : '');
          }
          const mvCard = document.querySelector('#summary-market-value');
          if (mvCard) {
            const sub = mvCard.closest('.metric-card-big').querySelector('.metric-subtitle');
            if (sub) sub.textContent = (d.position_count || 1) + ' 只持仓';
          }
          const pnlCard = document.getElementById('pnl-card');
          if (pnlCard) {
            const sub = pnlCard.querySelector('.metric-subtitle');
            if (sub) sub.textContent = '收益率 ' + formatPct(d.total_profit_loss_ratio || 0, 2);
            const iconEl = pnlCard.querySelector('.metric-icon');
            if (iconEl) {
              const v = d.total_profit_loss || 0;
              if (v > 0) { iconEl.style.background = 'rgba(212,48,47,0.10)'; iconEl.style.color = 'var(--color-bull)'; }
              else if (v < 0) { iconEl.style.background = 'rgba(28,160,28,0.10)'; iconEl.style.color = 'var(--color-bear)'; }
              else { iconEl.style.background = 'rgba(83,74,183,0.10)'; iconEl.style.color = 'var(--color-brand-600)'; }
            }
          }
        }
        const orderResp = await API.execution('/v1/orders/?account_id=REAL_001&status=PENDING&limit=100');
        if (orderResp.code === 0) {
          const ordersEl = document.getElementById('summary-orders');
          if (ordersEl) {
            if (QT) QT.pulseValue(ordersEl, String(orderResp.total || 0));
            const sub = ordersEl.closest('.metric-card-big').querySelector('.metric-subtitle');
            if (sub) sub.textContent = (orderResp.total || 0) > 0 ? '待处理' : '无待处理订单';
          }
        }
        if (QT) QT.endRefresh();
      } catch (e) { console.debug('摘要拉取失败:', e.message); if (QT) QT.endRefresh(); }
    }

    onMounted(function() {
      // 日期
      const dateEl = document.getElementById('date-display');
      if (dateEl) {
        dateEl.textContent = new Date().toLocaleDateString('zh-CN', {
          year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
        });
      }
      fetchSummary();
      summaryInterval = setInterval(fetchSummary, 15000);
    });

    onUnmounted(function() {
      if (summaryInterval) { clearInterval(summaryInterval); summaryInterval = null; }
    });

    return {};
  }
};

/* ================================================================
   2. PageAccount — 账户概览
   ================================================================ */
const PageAccount = {
  template: `
    <div class="page-account">
      <div class="account-grid" v-if="!loading">
        <div class="account-summary-card">
          <div class="label">总资产</div>
          <div class="value" :class="(summary.total_asset||0) > 0 ? 'text-bull' : 'text-bear'">{{ fmt(summary.total_asset) }}</div>
          <div class="sub">总资产</div>
        </div>
        <div class="account-summary-card">
          <div class="label">可用资金</div>
          <div class="value">{{ fmt(summary.available) }}</div>
          <div class="sub">可交易资金</div>
        </div>
        <div class="account-summary-card">
          <div class="label">持仓市值</div>
          <div class="value" :class="(summary.market_value||0) > 0 ? 'text-bull' : ''">{{ fmt(summary.market_value) }}</div>
          <div class="sub">当前持仓市值</div>
        </div>
        <div class="account-summary-card">
          <div class="label">持仓数量</div>
          <div class="value">{{ summary.position_count || 0 }}</div>
          <div class="sub">持仓股票数</div>
        </div>
      </div>
      <div class="card" style="margin-bottom:20px">
        <div class="card-header">📈 收益曲线</div>
        <div id="pnl-chart" style="height:400px"></div>
      </div>
      <div class="card">
        <div class="card-header">📋 持仓明细</div>
        <div class="data-table-wrapper">
          <table class="data-table">
            <thead><tr><th>股票</th><th>代码</th><th>持仓</th><th>成本价</th><th>现价</th><th>市值</th><th>盈亏</th><th>盈亏%</th></tr></thead>
            <tbody>
              <tr v-if="positions.length === 0"><td colspan="8" style="text-align:center;color:#999;padding:24px;">暂无持仓数据</td></tr>
              <tr v-for="p in positions" :key="p.ts_code">
                <td><strong>{{ p.name || p.ts_code }}</strong></td>
                <td style="color:var(--color-text-secondary);font-size:12px">{{ p.ts_code }}</td>
                <td>{{ fmtNum(p.volume) }}</td>
                <td>{{ fmt(p.cost_price) }}</td>
                <td>{{ fmt(p.current_price) }}</td>
                <td>{{ fmt(p.market_value) }}</td>
                <td :class="(p.profit_loss||0) >= 0 ? 'text-bull' : 'text-bear'">{{ fmt(p.profit_loss) }}</td>
                <td :class="(p.profit_loss_pct||0) >= 0 ? 'text-bull' : 'text-bear'">{{ fmtPct(p.profit_loss_pct) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-if="loading" class="loading">加载中...</div>
    </div>
  `,
  setup() {
    const summary = ref({});
    const positions = ref([]);
    const loading = ref(true);
    const chartStore = { current: null };

    function fmt(v) {
      if (v === undefined || v === null) return '--';
      return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function fmtNum(v) {
      if (v === undefined || v === null) return '--';
      return Number(v).toLocaleString('zh-CN');
    }
    function fmtPct(v) {
      if (v === undefined || v === null) return '--';
      return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
    }

    async function fetchAccount() {
      try {
        const d = await API.strategy('/v1/account/summary');
        if (d.success) summary.value = d.data || {};
      } catch (e) { /* ignore */ }

      try {
        const d = await API.strategy('/v1/account/positions');
        if (d.success) positions.value = d.data || [];
      } catch (e) { /* ignore */ }

      try {
        const d = await API.strategy('/v1/account/daily-values');
        if (d.success && d.data) renderPnlChart(d.data);
      } catch (e) { /* ignore */ }
    }

    function renderPnlChart(data) {
      const chart = ChartUtils.create('pnl-chart', chartStore);
      if (!chart) return;
      const dates = data.dates || [];
      const values = data.values || [];
      chart.setOption({
        tooltip: Object.assign({}, ChartUtils.tooltip, { valueFormatter: function(v) { return '¥' + Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2 }); } }),
        dataZoom: ChartUtils.dataZoom,
        grid: ChartUtils.grid,
        xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 11, color: ChartUtils.textSecondary } },
        yAxis: { type: 'value', axisLabel: { color: ChartUtils.textSecondary, formatter: function(v) { return '¥' + Number(v).toLocaleString('zh-CN'); } } },
        series: [{ type: 'line', data: values, smooth: true, lineStyle: { color: ChartUtils.brandColor, width: 2 }, areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1, [{offset:0,color:'rgba(102,126,234,0.3)'},{offset:1,color:'rgba(102,126,234,0.02)'}]) } }]
      });
    }

    onMounted(function() { fetchAccount(); loading.value = false; });
    onUnmounted(function() { ChartUtils.dispose(chartStore); });

    return { summary, positions, loading, fmt, fmtNum, fmtPct };
  }
};

/* ================================================================
   3. PageOrders — 交易下单
   ================================================================ */
const PageOrders = {
  template: `
    <div class="page-orders">
      <div class="order-layout">
        <div class="order-panel">
          <h3>快速下单</h3>
          <div class="direction-toggle">
            <button :class="'buy' + (direction==='BUY'?' active-buy':'')" @click="direction='BUY'">买入</button>
            <button :class="'sell' + (direction==='SELL'?' active-sell':'')" @click="direction='SELL'">卖出</button>
          </div>
          <div class="form-row">
            <label>股票代码</label>
            <input v-model="stockCode" placeholder="如 000001.SZ" list="stock-list" @input="autoSuggest">
            <datalist id="stock-list">
              <option v-for="s in suggestions" :key="s" :value="s"></option>
            </datalist>
          </div>
          <div class="form-row">
            <label>订单类型</label>
            <div class="order-type-toggle">
              <button :class="{active:orderType==='LIMIT'}" @click="orderType='LIMIT'">限价单</button>
              <button :class="{active:orderType==='MARKET'}" @click="orderType='MARKET'">市价单</button>
              <button :class="{active:orderType==='STOP'}" @click="orderType='STOP'">止损单</button>
            </div>
          </div>
          <div class="form-row" v-if="orderType!=='MARKET'">
            <label>价格</label>
            <input v-model.number="price" type="number" step="0.001" placeholder="0.000">
          </div>
          <div class="form-row">
            <label>数量</label>
            <input v-model.number="quantity" type="number" step="100" min="100" placeholder="100">
          </div>
          <div v-if="errorMsg" style="color:var(--color-bull);font-size:12px;margin-bottom:8px">⚠ {{ errorMsg }}</div>
          <button class="submit-btn" :class="direction==='BUY'?'buy':'sell'" @click="submitOrder" :disabled="submitting">
            {{ submitting ? '提交中...' : (direction==='BUY'?'买入':'卖出') + ' ' + stockCode }}
          </button>
        </div>

        <div>
          <div class="card" style="margin-bottom:16px">
            <div class="card-header">📋 当前仓位</div>
            <div class="data-table-wrapper">
              <table class="data-table">
                <thead><tr><th>代码</th><th>持仓</th><th>成本</th><th>现价</th><th>盈亏</th></tr></thead>
                <tbody>
                  <tr v-if="positions.length===0"><td colspan="5" style="text-align:center;color:#999;padding:16px">无持仓</td></tr>
                  <tr v-for="p in positions" :key="p.ts_code">
                    <td><strong>{{ p.name || p.ts_code }}</strong></td><td>{{ p.volume }}</td>
                    <td>{{ fmt(p.cost_price) }}</td><td>{{ fmt(p.current_price) }}</td>
                    <td :class="(p.profit_loss||0)>=0?'text-bull':'text-bear'">{{ fmt(p.profit_loss) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="card">
            <div class="card-header">
              <span>📜 订单历史</span>
              <span class="toolbar-group">
                <span v-if="selectedOrders.length>0" style="font-size:12px;color:var(--color-text-secondary);margin-right:8px">已选 {{ selectedOrders.length }} 条</span>
                <button class="btn btn-sm btn-error" :disabled="selectedOrders.length===0||batchCancelling" @click="batchCancelOrders">{{ batchCancelling?'撤单中...':'🗑️ 批量撤单' }}</button>
              </span>
            </div>
            <div class="data-table-wrapper">
              <table class="data-table">
                <thead><tr><th style="width:36px"><input type="checkbox" :checked="selectedOrders.length===orders.length&&orders.length>0" @change="selectAllOrders($event.target.checked)"></th><th>时间</th><th>代码</th><th>方向</th><th>类型</th><th>价格</th><th>数量</th><th>状态</th></tr></thead>
                <tbody>
                  <tr v-if="orders.length===0"><td colspan="8" style="text-align:center;color:#999;padding:16px">暂无订单</td></tr>
                  <tr v-for="o in orders" :key="o.order_id" :class="{'row-selected':selectedOrders.includes(o.order_id)}">
                    <td><input type="checkbox" :checked="selectedOrders.includes(o.order_id)" @change="toggleSelectOrder(o.order_id)"></td>
                    <td style="font-size:12px;color:var(--color-text-secondary)">{{ o.created_at || o.time }}</td>
                    <td>{{ o.ts_code }}</td>
                    <td :class="(o.direction||o.side)=='BUY'?'text-bull':'text-bear'">{{ (o.direction||o.side)=='BUY'?'买入':'卖出' }}</td>
                    <td>{{ o.order_type || o.type }}</td>
                    <td>{{ fmt(o.price) }}</td><td>{{ o.volume || o.quantity }}</td>
                    <td><span class="badge" :class="statusBadge(o.status)">{{ o.status }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() {
    const stockCode = ref('000001.SZ');
    const direction = ref('BUY');
    const orderType = ref('LIMIT');
    const price = ref(0);
    const quantity = ref(100);
    const submitting = ref(false);
    const errorMsg = ref('');
    const positions = ref([]);
    const orders = ref([]);
    const suggestions = ref([]);
    const selectedOrders = ref([]);
    const batchCancelling = ref(false);
    let wsUnsub = null;

    function fmt(v) { if (v===undefined||v===null) return '--'; return Number(v).toLocaleString('zh-CN', {minFractionDigits:2,maxFractionDigits:2}); }
    function statusBadge(s) { var m={'FILLED':'badge-success','PENDING':'badge-warning','REJECTED':'badge-error','CANCELED':'badge-info'}; return m[s]||'badge-info'; }

    // --- 批量选择/撤单 ---
    function toggleSelectOrder(id) { var idx = selectedOrders.value.indexOf(id); if (idx>=0) selectedOrders.value.splice(idx,1); else selectedOrders.value.push(id); }
    function selectAllOrders(checked) { selectedOrders.value = checked ? orders.value.map(function(o){return o.order_id;}) : []; }
    async function batchCancelOrders() {
      if (selectedOrders.value.length===0) return;
      if (selectedOrders.value.length===1) { if(!confirm('确定撤销该订单？')) return; }
      else { if(!confirm('确定撤销选中的 '+selectedOrders.value.length+' 条订单？')) return; }
      batchCancelling.value = true;
      var ok=0,fail=0;
      for(var id of selectedOrders.value) {
        try {
          var r = await API.execution('/v1/orders/'+id+'/cancel',{method:'POST'});
          if (r.code===0||r.success) ok++; else fail++;
        } catch(e) { fail++; }
      }
      if (QT && QT.Toast) QT.Toast.success('已撤销 '+ok+' 条订单'+(fail?'，'+fail+' 条失败':''));
      batchCancelling.value = false;
      selectedOrders.value = [];
      await fetchOrders();
    }

    function autoSuggest() {
      if (stockCode.value.length >= 2) {
        suggestions.value = ['000001.SZ','000002.SZ','000333.SZ','000858.SZ','002594.SZ','002415.SZ','300750.SZ','600519.SH','600036.SH','601318.SH'];
      }
    }

    async function submitOrder() {
      errorMsg.value = '';
      if (!stockCode.value) { errorMsg.value = '请输入股票代码'; return; }
      if (orderType.value !== 'MARKET' && (!price.value || price.value <= 0)) { errorMsg.value = '请输入有效价格'; return; }
      if (!quantity.value || quantity.value < 100) { errorMsg.value = '数量至少100股'; return; }
      submitting.value = true;
      try {
        const d = await API.execution('/v1/orders/submit', {
          method: 'POST',
          body: JSON.stringify({ ts_code: stockCode.value, direction: direction.value, order_type: orderType.value, price: price.value, volume: quantity.value, account_id: 'REAL_001' })
        });
        if (d.code === 0 || d.success) {
          if (QT && QT.Toast) QT.Toast.success('订单已提交');
          else Toast.success('订单已提交');
          fetchOrders();
        } else {
          errorMsg.value = d.message || '提交失败';
        }
      } catch (e) { errorMsg.value = e.message; }
      finally { submitting.value = false; }
    }

    async function fetchPositions() {
      try { const d = await API.execution('/v1/positions?account_id=REAL_001'); if (d.code === 0) positions.value = d.data || []; } catch(e) {}
    }
    async function fetchOrders() {
      try { const d = await API.execution('/v1/orders?account_id=REAL_001&limit=50'); if (d.code === 0) orders.value = d.data || []; } catch(e) {}
    }

    onMounted(function() {
      fetchPositions(); fetchOrders();
      const ws = window.getWSManager ? getWSManager() : null;
      if (ws) {
        ws.on('order_update', function() { fetchOrders(); });
      }
    });
    onUnmounted(function() { if (wsUnsub && typeof wsUnsub === 'function') wsUnsub(); });

    return { stockCode, direction, orderType, price, quantity, submitting, errorMsg, positions, orders, suggestions, selectedOrders, batchCancelling, fmt, statusBadge, autoSuggest, submitOrder, toggleSelectOrder, selectAllOrders, batchCancelOrders };
  }
};

/* ================================================================
   4. PageTradeAnalysis — 交易分析
   ================================================================ */
const PageTradeAnalysis = {
  template: `
    <div class="page-trade-analysis">
      <div class="ta-grid">
        <div class="ta-stat-card" v-for="s in stats" :key="s.label">
          <div class="label">{{ s.label }}</div>
          <div class="value" :class="s.color||''">{{ s.val }}</div>
        </div>
      </div>
      <div class="ta-chart-grid">
        <div class="ta-chart-box"><div class="chart-title">盈亏分布</div><div id="pnl-dist-chart" class="chart-area"></div></div>
        <div class="ta-chart-box"><div class="chart-title">累计收益</div><div id="cumulative-chart" class="chart-area"></div></div>
        <div class="ta-chart-box" style="grid-column:1/-1"><div class="chart-title">月度收益</div><div id="monthly-chart" class="chart-area"></div></div>
      </div>
      <div class="card">
        <div class="card-header">
          <span>📋 交易记录</span>
          <span class="toolbar-group">
            <span v-if="selectedTrades.length>0" style="font-size:12px;color:var(--color-text-secondary);margin-right:8px">已选 {{ selectedTrades.length }} 条</span>
            <button class="btn btn-sm" :disabled="selectedTrades.length===0" @click="exportSelectedTrades">📥 导出选中</button>
          </span>
        </div>
        <div class="data-table-wrapper">
          <table class="data-table">
            <thead><tr><th style="width:36px"><input type="checkbox" :checked="selectedTrades.length===trades.length&&trades.length>0" @change="selectAllTrades($event.target.checked)"></th><th>时间</th><th>股票</th><th>方向</th><th>数量</th><th>价格</th><th>盈亏</th></tr></thead>
            <tbody>
              <tr v-if="trades.length===0"><td colspan="7" style="text-align:center;color:#999;padding:24px;">暂无交易记录</td></tr>
              <tr v-for="t in trades" :key="t.trade_id" :class="{'row-selected':selectedTrades.includes(getTradeId(t))}">
                <td><input type="checkbox" :checked="selectedTrades.includes(getTradeId(t))" @change="toggleSelectTrade(getTradeId(t))"></td>
                <td style="font-size:12px;color:var(--color-text-secondary)">{{ t.trade_time || t.time }}</td>
                <td><strong>{{ t.name || t.ts_code }}</strong></td>
                <td :class="t.direction==='BUY'?'text-bull':'text-bear'">{{ t.direction==='BUY'?'买入':'卖出' }}</td>
                <td>{{ t.volume || t.quantity }}</td>
                <td>{{ fmt(t.price) }}</td>
                <td :class="(t.profit_loss||0)>=0?'text-bull':'text-bear'">{{ fmt(t.profit_loss) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
  setup() {
    const stats = ref([]);
    const trades = ref([]);
    const selectedTrades = ref([]);
    const chartStores = { dist: { current: null }, cumulative: { current: null }, monthly: { current: null } };

    function fmt(v) { if (v===undefined||v===null) return '--'; return Number(v).toLocaleString('zh-CN', {minFractionDigits:2,maxFractionDigits:2}); }

    // --- 批量选择 ---
    function getTradeId(t) { return t.trade_id || t.id || (t.trade_time + '_' + t.ts_code); }
    function toggleSelectTrade(id) { var idx = selectedTrades.value.indexOf(id); if (idx>=0) selectedTrades.value.splice(idx,1); else selectedTrades.value.push(id); }
    function selectAllTrades(checked) { selectedTrades.value = checked ? trades.value.map(function(t){return getTradeId(t);}) : []; }
    function exportSelectedTrades() {
      if (selectedTrades.value.length===0) return;
      var rows = [['时间','股票','方向','数量','价格','盈亏']];
      trades.value.forEach(function(t) {
        if (!selectedTrades.value.includes(getTradeId(t))) return;
        rows.push([
          t.trade_time || t.time || '',
          t.name || t.ts_code || '',
          t.direction==='BUY'?'买入':'卖出',
          String(t.volume || t.quantity || ''),
          fmt(t.price),
          fmt(t.profit_loss)
        ]);
      });
      var csv = rows.map(function(r){return r.join(',');}).join('\n');
      var blob = new Blob(['\uFEFF'+csv], {type:'text/csv;charset=utf-8;'});
      var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = '交易记录_'+new Date().toISOString().slice(0,10)+'.csv'; a.click();
      URL.revokeObjectURL(a.href);
      if (QT && QT.Toast) QT.Toast.success('已导出 '+selectedTrades.value.length+' 条交易记录');
    }

    function createDistChart() {
      var chart = ChartUtils.create('pnl-dist-chart', chartStores.dist);
      if (!chart) return;
      chart.setOption({
        title:{text:'盈亏分布',left:'center',textStyle:{fontSize:14,color:ChartUtils.textColor}},
        tooltip:Object.assign({}, ChartUtils.tooltip, {trigger:'item',formatter:function(p){return p.name+': '+p.value+'次'}}),
        grid:{left:40,right:15,top:35,bottom:25},
        xAxis:{type:'category',data:['-5%','-3%','-1%','0%','1%','3%','5%'],axisLabel:{color:ChartUtils.textSecondary}},
        yAxis:{type:'value',axisLabel:{color:ChartUtils.textSecondary}},
        series:[{type:'bar',data:[2,5,12,20,15,8,3],itemStyle:{borderRadius:[4,4,0,0],color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'#667eea'},{offset:1,color:'#764ba2'}])}}]
      });
    }

    function createCumulativeChart() {
      var chart = ChartUtils.create('cumulative-chart', chartStores.cumulative);
      if (!chart) return;
      chart.setOption({
        title:{text:'累计收益',left:'center',textStyle:{fontSize:14,color:ChartUtils.textColor}},
        tooltip:Object.assign({}, ChartUtils.tooltip, {valueFormatter:function(v){return v.toFixed(2)+'%'}}),
        dataZoom: ChartUtils.dataZoom,
        grid:{left:50,right:15,top:35,bottom:50},
        xAxis:{type:'category',data:['1月','2月','3月','4月','5月','6月'],axisLabel:{color:ChartUtils.textSecondary}},
        yAxis:{type:'value',axisLabel:{color:ChartUtils.textSecondary,formatter:function(v){return v.toFixed(0)+'%'}}},
        series:[{type:'line',data:[0,2,5,8,12,15],smooth:true,lineStyle:{color:ChartUtils.brandColor,width:2},areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(102,126,234,0.3)'},{offset:1,color:'rgba(102,126,234,0.02)'}])}}]
      });
    }

    function createMonthlyChart() {
      var chart = ChartUtils.create('monthly-chart', chartStores.monthly);
      if (!chart) return;
      chart.setOption({
        title:{text:'月度收益',left:'center',textStyle:{fontSize:14,color:ChartUtils.textColor}},
        tooltip:Object.assign({}, ChartUtils.tooltip, {trigger:'axis',valueFormatter:function(v){return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'}}),
        dataZoom: ChartUtils.dataZoom,
        grid:{left:50,right:15,top:35,bottom:50},
        xAxis:{type:'category',data:['1月','2月','3月','4月','5月','6月'],axisLabel:{color:ChartUtils.textSecondary}},
        yAxis:{type:'value',axisLabel:{color:ChartUtils.textSecondary,formatter:function(v){return v.toFixed(0)+'%'}}},
        series:[{type:'bar',data:[1.2,-0.5,2.1,0.8,-0.3,1.5],itemStyle:{borderRadius:[4,4,0,0],color:function(p){return p.value>=0?ChartUtils.bullColor:ChartUtils.bearColor}}}]
      });
    }

    async function fetchStats() {
      try {
        const d = await API.strategy('/v1/trades/stats');
        if (d.success && d.data) {
          const s = d.data;
          stats.value = [
            { label: '总交易次数', val: s.total_trades || 0 },
            { label: '胜率', val: (s.win_rate != null ? (s.win_rate*100).toFixed(1) + '%' : '--') },
            { label: '总盈亏', val: fmt(s.total_pnl), color: (s.total_pnl||0)>=0?'text-bull':'text-bear' },
            { label: '最大单笔盈利', val: fmt(s.max_win), color: 'text-bull' },
            { label: '最大单笔亏损', val: fmt(s.max_loss), color: 'text-bear' },
            { label: '平均盈亏', val: fmt(s.avg_pnl) },
          ];
        }
      } catch(e) {}
    }

    async function fetchTrades() {
      try { const d = await API.strategy('/v1/trades?limit=100'); if (d.success) trades.value = d.data || []; } catch(e) {}
    }

    onMounted(function() {
      createDistChart();
      createCumulativeChart();
      createMonthlyChart();
      fetchStats();
      fetchTrades();
    });
    onUnmounted(function() {
      ChartUtils.dispose(chartStores.dist);
      ChartUtils.dispose(chartStores.cumulative);
      ChartUtils.dispose(chartStores.monthly);
    });

    return { stats, trades, selectedTrades, fmt, getTradeId, toggleSelectTrade, selectAllTrades, exportSelectedTrades };
  }
};

/* ================================================================
   5. PageBacktest — 策略回测（v2 多策略对比）
   ================================================================ */
const PageBacktest = {
  template: `
    <div class="page-backtest">
      <div class="backtest-config">
        <div class="config-row">
          <label>股票</label>
          <div class="stock-chips">
            <span v-for="s in stocks" :key="s.code" class="stock-chip" :class="{active:selectedStock===s.code}" @click="selectedStock=s.code">{{ s.name }}</span>
          </div>
        </div>
        <div class="config-row">
          <label>策略</label>
          <div class="strategy-chips strategy-multi">
            <span v-for="s in strategyOpts" :key="s.id" class="strategy-chip"
                  :class="{active: selectedStrategies.includes(s.id)}"
                  :style="selectedStrategies.includes(s.id) ? {background: strategyColor(s.id),borderColor:strategyColor(s.id),color:'#fff'} : {}"
                  @click="toggleStrategy(s.id)">
              {{ selectedStrategies.includes(s.id) ? '✓ ' : '' }}{{ s.name }}
            </span>
          </div>
          <span style="font-size:11px;color:var(--color-text-secondary);margin-left:4px">
            <template v-if="selectedStrategies.length===1">无需对比</template>
            <template v-else>{{ selectedStrategies.length }} 个策略对比</template>
          </span>
        </div>
        <div class="config-row" style="justify-content:space-between">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
            <label style="min-width:auto">开始</label><input type="date" v-model="startDate" style="padding:6px 10px;border:0.5px solid var(--color-border);border-radius:6px;font-size:13px;background:var(--color-bg-surface);color:var(--color-text)">
            <label style="min-width:auto">结束</label><input type="date" v-model="endDate" style="padding:6px 10px;border:0.5px solid var(--color-border);border-radius:6px;font-size:13px;background:var(--color-bg-surface);color:var(--color-text)">
          </div>
          <button class="btn btn-primary" @click="runBacktest" :disabled="running||selectedStrategies.length===0">{{ running ? '回测中...' : '▶ 运行回测'+(selectedStrategies.length>1?' ('+selectedStrategies.length+'策略)':'') }}</button>
        </div>
      </div>

      <div v-if="results">
        <!-- ===== 多策略对比表 ===== -->
        <div v-if="hasComparison" class="card bt-compare-card">
          <div class="card-header">📊 多策略对比（标注 <span class="compare-best-mark">绿色</span> = 最优）</div>
          <div class="data-table-wrapper">
            <table class="data-table bt-compare-table">
              <thead>
                <tr>
                  <th style="min-width:80px">指标</th>
                  <th v-for="r in comparison" :key="r.strategy" style="text-align:right">
                    <span :style="{color: strategyColor(r.strategy),fontWeight:600}">{{ strategyName(r.strategy) }}</span>
                  </th>
                  <th style="text-align:right;color:var(--color-text-secondary)">最佳</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in compareMetrics" :key="m.key">
                  <td class="compare-label">{{ m.label }}</td>
                  <td v-for="r in comparison" :key="r.strategy" style="text-align:right" :class="isBestVal(m, r) ? 'compare-best-val' : ''">
                    {{ fmtCompareMetric(m, r) }}
                  </td>
                  <td style="text-align:right" :style="{color:strategyColor(bestStrategy(m)),fontWeight:600,fontSize:'12px'}">
                    {{ strategyName(bestStrategy(m)) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- ===== KPI 卡片（显示 primaryStrategy 的指标） ===== -->
        <div class="bt-strategy-tabs" v-if="hasComparison">
          <span style="font-size:12px;color:var(--color-text-secondary);margin-right:6px">当前详情:</span>
          <span v-for="r in comparison" :key="r.strategy" class="bt-strategy-tab"
                :class="{active: primaryStrategy===r.strategy}"
                :style="primaryStrategy===r.strategy ? {background: strategyColor(r.strategy),borderColor:strategyColor(r.strategy),color:'#fff'} : {borderColor:strategyColor(r.strategy),color:strategyColor(r.strategy)}"
                @click="setPrimaryStrategy(r.strategy)">
            {{ strategyName(r.strategy) }}
          </span>
        </div>
        <div class="backtest-kpis">
          <div class="kpi-card" v-for="k in kpis" :key="k.label"><div class="kpi-label">{{ k.label }}</div><div class="kpi-value" :class="k.color||''">{{ k.val }}</div></div>
        </div>

        <!-- ===== 图表区域 ===== -->
        <div class="bt-chart-grid">
          <div class="bt-chart-box bt-full-chart">
            <div class="bt-chart-title">策略净值曲线</div>
            <div class="chart-area" id="bt-equity-chart"></div>
          </div>
          <div class="bt-chart-box">
            <div class="bt-chart-title">回撤曲线</div>
            <div class="chart-area" id="bt-drawdown-chart"></div>
          </div>
          <div class="bt-chart-box">
            <div class="bt-chart-title">月度收益热图 — {{ strategyName(primaryStrategy) }}</div>
            <div class="chart-area" id="bt-heatmap-chart"></div>
          </div>
          <div class="bt-chart-box bt-full-chart" v-if="wfResults.length">
            <div class="bt-chart-title">前向验证分析 — {{ strategyName(primaryStrategy) }}</div>
            <div class="chart-area" id="bt-walkforward-chart"></div>
          </div>
        </div>

        <!-- ===== 交易明细 ===== -->
        <div class="card" style="margin-top:20px">
          <div class="card-header">📋 交易明细</div>
          <div class="data-table-wrapper">
            <table class="data-table">
              <thead><tr><th>日期</th><th>策略</th><th>股票</th><th>方向</th><th>价格</th><th>数量</th><th>盈亏</th><th>持仓天数</th></tr></thead>
              <tbody>
                <tr v-if="!tradeDetails||tradeDetails.length===0"><td colspan="8" style="text-align:center;color:#999;padding:24px;">暂无交易明细</td></tr>
                <tr v-for="(t,i) in (tradeDetails||[])" :key="i">
                  <td>{{ t.date || t.time }}</td>
                  <td><span :style="{color:strategyColor(t.strategy),fontSize:'11px',fontWeight:500}">{{ strategyName(t.strategy)||'--' }}</span></td>
                  <td>{{ t.stock || t.ts_code }}</td>
                  <td :class="t.direction==='买入'||t.direction==='BUY'?'text-bull':'text-bear'">{{ t.direction==='买入'||t.direction==='BUY'?'买入':'卖出' }}</td>
                  <td>{{ fmt(t.price) }}</td>
                  <td>{{ t.quantity || t.volume }}</td>
                  <td :class="(t.pnl||t.profit||0)>=0?'text-bull':'text-bear'">{{ fmt(t.pnl||t.profit) }}</td>
                  <td>{{ t.hold_days||'--' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <button class="btn" style="margin-top:12px" @click="exportCSV">📥 导出 CSV</button>
        </div>
      </div>
      <div v-if="!results && !running" class="card" style="text-align:center;padding:60px;color:var(--color-text-secondary)">选择参数后点击"运行回测"</div>
      <div v-if="running" class="loading">运行回测中...</div>
    </div>
  `,
  setup() {
    const stocks = [{code:'000001.SZ',name:'平安银行'},{code:'600519.SH',name:'贵州茅台'},{code:'000858.SZ',name:'五粮液'},{code:'300750.SZ',name:'宁德时代'},{code:'002594.SZ',name:'比亚迪'}];
    const strategyOpts = [
      {id:'ma-cross',name:'双均线金叉'},
      {id:'breakout',name:'突破策略'},
      // 如果引擎支持更多策略，后端会自动处理；前端 UI 列出常用策略
      {id:'rsi',name:'RSI 策略'},
      {id:'macd',name:'MACD 策略'},
      {id:'kdj',name:'KDJ 策略'},
    ];
    // 策略颜色调色板
    const STRATEGY_COLORS = ['#667eea', '#2ed573', '#ff7b72', '#e6a23c', '#a855f7', '#06b6d4'];

    const selectedStock = ref('000001.SZ');
    const selectedStrategies = ref(['ma-cross', 'breakout']);
    const startDate = ref(new Date(Date.now()-90*86400000).toISOString().slice(0,10));
    const endDate = ref(new Date().toISOString().slice(0,10));
    const running = ref(false);
    const results = ref(null);
    const comparison = ref(null);
    const primaryStrategy = ref('ma-cross');
    const kpis = ref([]);
    const tradeDetails = ref([]);
    const wfResults = ref([]);
    const charts = { equity: null, drawdown: null, heatmap: null, walkforward: null };

    // 对比指标定义（better: higher=越大越好, lower=越小越好, nearzero=越接近0越好）
    const compareMetrics = [
      { key:'total_return', label:'总收益率', better:'higher', pct:true },
      { key:'annual_return', label:'年化收益', better:'higher', pct:true },
      { key:'sharpe', label:'夏普比率', better:'higher', pct:false },
      { key:'max_drawdown', label:'最大回撤', better:'lower', pct:true },
      { key:'win_rate', label:'胜率', better:'higher', pct:true },
      { key:'profit_loss_ratio', label:'盈亏比', better:'higher', pct:false },
      { key:'trade_count', label:'交易次数', better:'none', pct:false },
      { key:'calmar_ratio', label:'卡尔玛比率', better:'higher', pct:false },
      { key:'sortino_ratio', label:'索提诺比率', better:'higher', pct:false },
    ];

    // ---- 工具函数 ----
    function fmt(v) {
      if (v===undefined||v===null) return '--';
      return Number(v).toLocaleString('zh-CN',{minFractionDigits:2,maxFractionDigits:2});
    }
    function fmtPct(v) {
      if (v===undefined||v===null) return '--';
      return (v>=0?'+':'')+(v*100).toFixed(2)+'%';
    }
    function strategyName(id) {
      var s = strategyOpts.find(function(o){return o.id===id;});
      return s ? s.name : id;
    }
    function strategyColor(id) {
      var idx = strategyOpts.findIndex(function(o){return o.id===id;});
      return STRATEGY_COLORS[idx >= 0 ? idx % STRATEGY_COLORS.length : 0];
    }
    function getMetric(r, key) {
      if (!r) return 0;
      // 尝试 r.metrics.xxx -> r.xxx 回退
      if (r.metrics && r.metrics[key] !== undefined) return r.metrics[key];
      return r[key] !== undefined ? r[key] : 0;
    }

    // ---- 多策略选择 ----
    function toggleStrategy(id) {
      var idx = selectedStrategies.value.indexOf(id);
      if (idx >= 0) {
        if (selectedStrategies.value.length <= 1) return; // 至少保留1个
        selectedStrategies.value.splice(idx, 1);
      } else {
        if (selectedStrategies.value.length >= 4) return; // 最多4个
        selectedStrategies.value.push(id);
      }
      // 如果当前 primaryStrategy 被取消，切到第一个
      if (!selectedStrategies.value.includes(primaryStrategy.value)) {
        primaryStrategy.value = selectedStrategies.value[0];
      }
    }
    function setPrimaryStrategy(id) {
      primaryStrategy.value = id;
      var r = comparison.value ? comparison.value.find(function(x){return x.strategy===id;}) : results.value;
      if (r) { updateKPI(r); renderSingleCharts(r); }
    }

    // ---- 最佳值判定 ----
    function bestStrategy(m) {
      if (!comparison.value || comparison.value.length<2) return null;
      var bestR = null, bestVal = null;
      comparison.value.forEach(function(r){
        var v = getMetric(r, m.key);
        if (bestR === null) { bestR = r; bestVal = v; return; }
        if (m.better === 'higher' && v > bestVal) { bestR = r; bestVal = v; }
        else if (m.better === 'lower' && v < bestVal) { bestR = r; bestVal = v; }
        else if (m.better === 'nearzero' && Math.abs(v) < Math.abs(bestVal)) { bestR = r; bestVal = v; }
      });
      return bestR ? bestR.strategy : null;
    }
    function isBestVal(m, r) {
      var best = bestStrategy(m);
      return best && r.strategy === best && m.better !== 'none';
    }
    function fmtCompareMetric(m, r) {
      var v = getMetric(r, m.key);
      if (v === undefined || v === null) return '--';
      if (m.pct) return fmtPct(v);
      if (m.key === 'trade_count') return String(Math.round(v));
      if (['sharpe','calmar_ratio','sortino_ratio','profit_loss_ratio'].includes(m.key)) return Number(v).toFixed(2);
      return fmtPct(v);
    }

    // ---- 归一化结果（后端 metrics 在 r.metrics 内） ----
    function normalizeResult(r) {
      if (r && r.metrics) Object.assign(r, r.metrics);
      return r;
    }

    // ---- KPI 更新 ----
    function updateKPI(r) {
      var m = normalizeResult(r);
      kpis.value = [
        {label:'总收益率',val:fmtPct(m.total_return),color:(m.total_return||0)>=0?'text-bull':'text-bear'},
        {label:'年化收益',val:fmtPct(m.annual_return),color:(m.annual_return||0)>=0?'text-bull':'text-bear'},
        {label:'最大回撤',val:fmtPct(m.max_drawdown),color:'text-bear'},
        {label:'夏普比率',val:(m.sharpe||m.sharpe_ratio||0).toFixed(2)},
        {label:'胜率',val:fmtPct(m.win_rate)},
        {label:'交易次数',val:String(m.trade_count||m.total_trades||0)},
        {label:'阿尔法',val:(m.alpha||0).toFixed(3)},
        {label:'贝塔',val:(m.beta||0).toFixed(3)},
      ];
    }

    // ---- 主回测请求 ----
    async function runBacktest() {
      running.value = true;
      results.value = null;
      comparison.value = null;
      wfResults.value = [];
      try {
        var body = {
          ts_code: selectedStock.value,
          strategies: selectedStrategies.value,
          start_date: startDate.value,
          end_date: endDate.value
        };
        var d = await API.strategy('/v1/backtest/run', {
          method: 'POST',
          body: JSON.stringify(body)
        });
        if (d.success && d.data) {
          // 归一化所有结果
          var mainResult = normalizeResult(d.data);
          results.value = mainResult;

          // 处理多策略对比
          if (d.comparison && d.comparison.length > 1) {
            d.comparison.forEach(normalizeResult);
            comparison.value = d.comparison;
            primaryStrategy.value = d.comparison[0].strategy;
          } else {
            comparison.value = null;
            primaryStrategy.value = mainResult.strategy;
          }

          updateKPI(mainResult);

          // 聚合所有策略的交易明细
          var allTrades = [];
          if (comparison.value) {
            comparison.value.forEach(function(r){
              (r.trades||[]).forEach(function(t){
                t.strategy = r.strategy;
                allTrades.push(t);
              });
            });
          } else {
            allTrades = mainResult.trades || [];
          }
          // 按日期排序
          allTrades.sort(function(a,b){ return (a.date||'').localeCompare(b.date||''); });
          tradeDetails.value = allTrades;

          nextTick(function() { renderAllCharts(); });

          // 前向验证只跑 primaryStrategy
          runWalkForward();
        } else {
          Toast.warning('回测无返回数据' + (d.error ? ': '+d.error : ''));
        }
      } catch(e) { Toast.error('回测失败：'+e.message); }
      finally { running.value = false; }
    }

    async function runWalkForward() {
      try {
        var resp = await API.strategy('/v1/backtest/walk-forward', {
          method: 'POST',
          body: JSON.stringify({
            ts_code: selectedStock.value,
            strategy: primaryStrategy.value,
            start_date: startDate.value,
            end_date: endDate.value
          })
        });
        if (resp.success && resp.data && resp.data.windows) {
          wfResults.value = resp.data.windows.map(function(w,idx){
            return { window: w.window || 'W'+(idx+1), train_sharpe: Number(w.train_sharpe||0), test_sharpe: Number(w.test_sharpe||0) };
          });
          if (wfResults.value.length) nextTick(function(){ renderWalkForwardChart(wfResults.value); });
        }
      } catch(e) { /* walk-forward 非关键路径，静默失败 */ }
    }

    // ---- 渲染所有图表 ----
    function renderAllCharts() {
      renderEquityChart();
      renderDrawdownChart();
      renderHeatmapChart(getPrimaryResult());
    }
    function renderSingleCharts(r) {
      renderHeatmapChart(r);
    }

    function getPrimaryResult() {
      if (comparison.value) {
        var f = comparison.value.find(function(x){return x.strategy===primaryStrategy.value;});
        return f || results.value;
      }
      return results.value;
    }

    // ---- 策略净值曲线（多策略叠加） ----
    function renderEquityChart() {
      var el = document.getElementById('bt-equity-chart'); if (!el) return;
      if (charts.equity) charts.equity.dispose();
      charts.equity = QT.charts.init(el);

      var allData = comparison.value && comparison.value.length > 1 ? comparison.value : [results.value];
      var series = [];
      // 提取公共日期范围
      var allDates = null;

      allData.forEach(function(r, idx) {
        var ec = r.equity_curve || [];
        if (!allDates && ec.length) allDates = ec.map(function(d){return d[0];});
        var color = strategyColor(r.strategy);
        series.push({
          name: strategyName(r.strategy),
          type: 'line',
          data: ec.map(function(d){return d[1];}),
          smooth: true,
          symbol: 'none',
          lineStyle: { color: color, width: 2.5 },
          areaStyle: {
            color: { type:'linear', x:0, y:0, x2:0, y2:1,
              colorStops: [
                { offset:0, color: color + '2a' },
                { offset:1, color: color + '00' }
              ]
            }
          }
        });
      });

      // 基准曲线（取第一个策略的 benchmark 作为基准）
      var benchCurve = results.value && results.value.benchmark_curve;
      if (benchCurve && benchCurve.length) {
        series.push({
          name: '沪深300基准',
          type: 'line',
          data: benchCurve.map(function(d){return d[1];}),
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#999', type:'dashed', width: 1 },
          areaStyle: {
            color: { type:'linear', x:0, y:0, x2:0, y2:1,
              colorStops: [
                { offset:0, color: 'rgba(153,153,153,0.08)' },
                { offset:1, color: 'rgba(153,153,153,0)' }
              ]
            }
          }
        });
      }

      charts.equity.setOption({
        tooltip: {
          trigger:'axis',
          formatter:function(params){
            var s = '<b style="font-size:13px;">' + params[0].axisValue + '</b><br/>';
            params.forEach(function(p){
              s += p.marker + p.seriesName + ': <b>' + (p.value[1]?p.value[1].toFixed(4):'--') + '</b><br/>';
            });
            return s;
          },
          backgroundColor:'rgba(0,0,0,0.78)', borderColor:'rgba(255,255,255,0.08)', borderWidth:1,
          textStyle:{color:'#e5e7eb',fontSize:12},
          extraCssText:'border-radius:10px;padding:12px 16px;box-shadow:0 8px 24px rgba(0,0,0,0.25)'
        },
        legend: { data: series.map(function(s){return s.name;}), bottom:32, textStyle:{fontSize:11}, icon:'roundRect', itemWidth:12, itemHeight:4 },
        grid: { left:60, right:20, top:25, bottom:68 },
        xAxis: { type:'category', data: allDates||[], axisLabel:{fontSize:11,rotate:0} },
        yAxis: { type:'value', name:'净值', axisLabel:{formatter:function(v){return v.toFixed(2);}} },
        series: series,
        dataZoom: [
          { type:'inside', start:0, end:100 },
          { type:'slider', bottom:38, height:18, borderColor:'rgba(102,126,234,0.2)',
            fillerColor:'rgba(102,126,234,0.1)', handleStyle:{color:'#667eea'} }
        ]
      });
    }

    // ---- 回撤曲线（多策略叠加） ----
    function renderDrawdownChart() {
      var el = document.getElementById('bt-drawdown-chart'); if (!el) return;
      if (charts.drawdown) charts.drawdown.dispose();
      charts.drawdown = QT.charts.init(el);

      var allData = comparison.value && comparison.value.length > 1 ? comparison.value : [results.value];
      var series = [];
      var allDates = null;

      allData.forEach(function(r) {
        var dc = r.drawdown_curve || [];
        if (!allDates && dc.length) allDates = dc.map(function(d){return d[0];});
        var color = strategyColor(r.strategy);
        series.push({
          name: strategyName(r.strategy),
          type: 'line',
          data: dc.map(function(d){return d[1];}),
          smooth: true,
          symbol: 'none',
          lineStyle: { color: color, width: 2 },
          areaStyle: {
            color: { type:'linear', x:0, y:0, x2:0, y2:1,
              colorStops: [
                { offset:0, color: color + '40' },
                { offset:1, color: color + '02' }
              ]
            }
          }
        });
      });

      charts.drawdown.setOption({
        tooltip: {
          trigger:'axis',
          valueFormatter:function(v){return (v*100).toFixed(2)+'%';},
          backgroundColor:'rgba(0,0,0,0.78)', borderColor:'rgba(255,255,255,0.08)', borderWidth:1,
          textStyle:{color:'#e5e7eb',fontSize:12},
          extraCssText:'border-radius:10px;padding:12px 16px;box-shadow:0 8px 24px rgba(0,0,0,0.25)'
        },
        legend: { data: series.map(function(s){return s.name;}), bottom:24, textStyle:{fontSize:11}, icon:'roundRect', itemWidth:12, itemHeight:4 },
        grid: { left:55, right:15, top:15, bottom:55 },
        xAxis: { type:'category', data: allDates||[], axisLabel:{fontSize:11} },
        yAxis: { type:'value', axisLabel:{formatter:function(v){return (v*100).toFixed(0)+'%';}} },
        series: series,
        dataZoom: [{ type:'inside', start:0, end:100 }]
      });
    }

    // ---- 月度收益热图（single strategy） ----
    function renderHeatmapChart(r) {
      var el = document.getElementById('bt-heatmap-chart'); if (!el) return;
      if (charts.heatmap) charts.heatmap.dispose();
      charts.heatmap = QT.charts.init(el);
      if (!r) return;
      var months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];
      var monthly = r.monthly_returns || [];
      var heatData = [], years = [];
      if (monthly.length > 12) {
        for (var i=0; i<monthly.length; i++) {
          var yi = Math.floor(i/12), mi = i%12;
          if (!years[yi]) years[yi] = 'Y'+(yi+1);
          heatData.push([mi, yi, monthly[i]]);
        }
      } else {
        years = ['收益'];
        for (var i=0; i<monthly.length; i++) heatData.push([i, 0, monthly[i]]);
      }
      var maxVal = Math.max(Math.abs(monthly.reduce(function(a,b){return Math.abs(b)>Math.abs(a)?b:a;},0)), 0.05);
      charts.heatmap.setOption({
        tooltip:{formatter:function(p){return '<b>'+(years[p.value[1]]||'')+' '+months[p.value[0]]+'</b><br/>月收益: '+(p.value[2]*100).toFixed(2)+'%';}},
        grid:{left:50,right:15,top:10,bottom:48},
        xAxis:{type:'category',data:months,splitArea:{show:true,areaStyle:{color:['rgba(250,250,250,0.02)','rgba(250,250,250,0.02)']}},axisLine:{show:false},axisTick:{show:false}},
        yAxis:{type:'category',data:years,splitArea:{show:true},axisLine:{show:false},axisTick:{show:false}},
        visualMap:{min:-maxVal,max:maxVal,calculable:true,orient:'horizontal',left:'center',bottom:8,itemWidth:120,itemHeight:14,inRange:{color:['#2ed573','#f5f5f5','#ff4757']},textStyle:{fontSize:10}},
        series:[{type:'heatmap',data:heatData,label:{show:true,formatter:function(p){return (p.data[2]*100).toFixed(1)+'%';},fontSize:10},itemStyle:{borderColor:'rgba(255,255,255,0.6)',borderWidth:1},emphasis:{itemStyle:{shadowBlur:6,shadowColor:'rgba(0,0,0,0.3)'}}}]
      });
    }

    // ---- 前向验证图 ----
    function renderWalkForwardChart(wfData) {
      var el = document.getElementById('bt-walkforward-chart'); if(!el) return;
      if(charts.walkforward) charts.walkforward.dispose();
      charts.walkforward = QT.charts.init(el);
      var windows = wfData.map(function(w){return w.window;});
      charts.walkforward.setOption({
        tooltip:{trigger:'axis',backgroundColor:'rgba(0,0,0,0.78)',borderColor:'rgba(255,255,255,0.08)',borderWidth:1,textStyle:{color:'#e5e7eb',fontSize:12},extraCssText:'border-radius:10px;padding:10px 14px;box-shadow:0 8px 24px rgba(0,0,0,0.25)'},
        legend:{data:['训练集夏普','测试集夏普'],bottom:28,icon:'roundRect',itemWidth:12,itemHeight:4},
        grid:{left:50,right:20,top:25,bottom:55},
        xAxis:{type:'category',data:windows},
        yAxis:{type:'value',name:'夏普比率'},
        series:[
          {name:'训练集夏普',type:'bar',data:wfData.map(function(w){return Number(w.train_sharpe).toFixed(2);}),itemStyle:{color:'#667eea'}},
          {name:'测试集夏普',type:'bar',data:wfData.map(function(w){return Number(w.test_sharpe).toFixed(2);}),itemStyle:{color:'#2ed573'}}
        ]
      });
    }

    function disposeCharts() {
      Object.values(charts).forEach(function(c){if(c){c.dispose();}});
    }

    function handleResize() {
      Object.values(charts).forEach(function(c){if(c){c.resize();}});
    }

    function exportCSV() {
      if (!tradeDetails.value || tradeDetails.value.length===0) return;
      var csv = '日期,策略,股票,方向,价格,数量,盈亏,持仓天数\n';
      tradeDetails.value.forEach(function(t){
        csv += (t.date||t.time)+','+strategyName(t.strategy)+','+(t.stock||t.ts_code||'')+','+(t.direction||'')+','+(t.price||0)+','+(t.quantity||t.volume||0)+','+(t.pnl||t.profit||0)+','+(t.hold_days||'')+'\n';
      });
      var blob = new Blob([csv],{type:'text/csv;charset=utf-8'});
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a'); a.href=url; a.download='backtest-trades.csv'; document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    }

    onMounted(function() { window.addEventListener('resize', handleResize); });
    onUnmounted(function() { window.removeEventListener('resize', handleResize); disposeCharts(); });

    return {
      stocks, strategyOpts, selectedStock, selectedStrategies,
      startDate, endDate, running, results, comparison, primaryStrategy,
      kpis, tradeDetails, wfResults,
      compareMetrics,
      fmt, runBacktest, exportCSV,
      toggleStrategy, setPrimaryStrategy,
      strategyName, strategyColor, hasComparison: computed(function(){ return comparison.value && comparison.value.length > 1; }),
      isBestVal, bestStrategy, fmtCompareMetric
    };
  }
};

/* ================================================================
   6. PageStrategies — 策略管理
   ================================================================ */
const TYPE_LABELS = { builtin:'内置策略', trend:'趋势跟踪', mean_reversion:'均值回归', momentum:'动量策略', breakout:'突破策略' };

const PageStrategies = {
  template: `
    <div class="page-strategies">
      <div class="toolbar">
        <button class="btn btn-primary" @click="newStrategy">+ 新建策略</button>
        <button class="btn btn-info" :disabled="selected.length<2" @click="compareStrategies">对比选中 ({{ selected.length }})</button>
        <button class="btn btn-success" :disabled="selected.length===0" @click="backtestSelected">回测选中</button>
        <template v-if="selected.length>0">
          <span style="margin:0 4px;color:var(--color-text-secondary)">|</span>
          <button class="btn btn-sm" @click="batchActivate" :disabled="batchRunning">✅ 批量启用</button>
          <button class="btn btn-sm" @click="batchDeactivate" :disabled="batchRunning">⏸️ 批量停用</button>
          <button class="btn btn-sm btn-error" @click="batchDelete" :disabled="batchRunning">🗑️ 批量删除</button>
        </template>
        <select v-model="typeFilter" style="margin-left:auto" @change="loadStrategies">
          <option value="">全部类型</option>
          <option value="trend">趋势跟踪</option>
          <option value="mean_reversion">均值回归</option>
          <option value="momentum">动量策略</option>
          <option value="breakout">突破策略</option>
        </select>
      </div>
      <div class="strategy-grid" v-if="!loading && strategies.length>0">
        <div v-for="(s,idx) in strategies" :key="s.strategy_id||s.id" class="strategy-card"
          :class="{selected:selected.includes(s.strategy_id||s.id),'drag-over':dragOverIdx===idx}"
          @click="toggleSelect(s)"
          draggable="true"
          @dragstart="onDragStart(idx,$event)"
          @dragover.prevent="onDragOver(idx)"
          @drop.prevent="onDrop(idx)"
          @dragleave="dragOverIdx=null">
          <div class="card-actions" @click.stop>
            <button class="btn-edit" @click="editStrategy(s)" title="编辑/替换策略">✎</button>
            <button class="btn-del" @click="confirmDelete(s)" title="删除策略">✕</button>
          </div>
          <h3 @click.stop="startEditName(s)" v-if="editingId!==(s.strategy_id||s.id)">{{ s.name || s.strategy_name || '未命名策略' }}</h3>
          <input v-else v-model="editingValue" @blur="saveEditName(s)" @keyup.enter="saveEditName(s)" @keyup.escape="cancelEditName"
            style="width:100%;padding:4px 8px;border:1px solid var(--color-brand-400);border-radius:4px;font-size:14px;background:var(--color-bg-surface);color:var(--color-text)" @click.stop autofocus>
          <div class="desc" v-if="s.description">{{ s.description }}</div>
          <div class="metrics">
            <div class="metric">年化收益<strong :class="colorClass(s.annual_return||(s.performance&&s.performance.total_return))">{{ fmtPct(s.annual_return||(s.performance&&s.performance.total_return)) }}</strong></div>
            <div class="metric">夏普比率<strong>{{ ((s.sharpe_ratio||(s.performance&&s.performance.sharpe)||0)).toFixed(2) }}</strong></div>
            <div class="metric">最大回撤<strong :class="(s.max_drawdown||(s.performance&&s.performance.max_drawdown)||0)<0?'bear':''">{{ fmtPct(s.max_drawdown||(s.performance&&s.performance.max_drawdown)) }}</strong></div>
            <div class="metric">胜率<strong>{{ fmtPct(s.win_rate||(s.performance&&s.performance.win_rate)) }}</strong></div>
          </div>
          <div class="meta">
            <span class="badge" :class="'badge-'+ (s.strategy_type||s.type||'builtin')">{{ typeLabel(s.strategy_type||s.type||'builtin') }}</span>
            <span v-if="s.status" style="font-size:11px;color:var(--color-text-secondary)">{{ s.status==='active'?'● 已启用':'○ 已停用' }}</span>
            <span style="font-size:12px;color:var(--color-text-secondary);margin-left:auto">{{ (s.trade_count||(s.performance&&s.performance.total_trades)||0) }}笔交易</span>
          </div>
        </div>
      </div>
      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-card" v-for="i in 4" :key="i"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-line w80"></div><div class="skeleton skeleton-line w60"></div><div class="skeleton skeleton-line w40"></div></div>
      </div>
      <div v-if="!loading && strategies.length===0" style="text-align:center;padding:60px;color:#999"><div style="font-size:40px;margin-bottom:12px">📭</div><p>暂无策略，点击"新建策略"开始</p></div>
      <div v-if="showChart" class="card" style="margin-top:20px">
        <div class="card-header">📈 回测结果</div>
        <div id="strategy-chart" style="height:380px"></div>
        <div class="card-grid" style="margin-top:16px">
          <div class="summary-card" v-for="m in chartMetrics" :key="m.label"><div class="label">{{ m.label }}</div><div class="value" :class="m.color||''">{{ m.value }}</div></div>
        </div>
      </div>
      <div v-if="compareData.length" class="card compare-table" style="margin-top:20px">
        <div class="card-header">📊 策略对比</div>
        <table class="data-table"><thead><tr><th>策略</th><th>年化收益</th><th>夏普</th><th>最大回撤</th><th>胜率</th><th>交易次数</th></tr></thead>
          <tbody>
            <tr v-for="c in compareData" :key="c.name"><td><strong>{{ c.name }}</strong></td><td :class="colorClass(c.annual_return)">{{ fmtPct(c.annual_return) }}</td><td>{{ (c.sharpe_ratio||0).toFixed(2) }}</td><td :class="(c.max_drawdown||0)<0?'bear':''">{{ fmtPct(c.max_drawdown) }}</td><td>{{ fmtPct(c.win_rate) }}</td><td>{{ c.trade_count||0 }}</td></tr>
          </tbody>
        </table>
      </div>
      <div v-if="showForm" class="modal-overlay" @click.self="showForm=false">
        <div class="modal-box" style="max-width:460px;padding:28px 24px 20px;"><h3 style="margin:0 0 20px;font-size:17px;font-weight:500;">{{ editId?'替换 / 编辑策略':'新建策略' }}</h3>
          <div class="form-group"><label>策略名称</label><input v-model="form.name" placeholder="如：双均线金叉" style="width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid var(--color-border);border-radius:8px;font-size:14px;color:var(--color-text);background:var(--color-bg-surface)"></div>
          <div class="form-group"><label>策略类型</label><select v-model="form.type" style="width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid var(--color-border);border-radius:8px;font-size:14px;color:var(--color-text);background:var(--color-bg-surface)"><option value="trend">趋势跟踪</option><option value="mean_reversion">均值回归</option><option value="momentum">动量策略</option><option value="breakout">突破策略</option></select></div>
          <div class="form-group"><label>描述</label><input v-model="form.description" placeholder="策略逻辑说明..." style="width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid var(--color-border);border-radius:8px;font-size:14px;color:var(--color-text);background:var(--color-bg-surface)"></div>
          <div class="form-group"><label>参数 (JSON)</label><textarea v-model="form.params_text" placeholder='{"fast_ma":5,"slow_ma":20}' rows="3" style="width:100%;box-sizing:border-box;font-family:'SF Mono',Monaco,monospace;font-size:13px;padding:10px 12px;border:1px solid var(--color-border);border-radius:8px;color:var(--color-text);background:var(--color-bg-surface);resize:vertical;line-height:1.5"></textarea></div>
          <div class="modal-actions"><button class="btn btn-sm" @click="showForm=false">取消</button><button v-if="editId" class="btn btn-sm btn-error" @click="deleteStrategy">删除</button><button class="btn btn-primary btn-sm" @click="saveStrategy">{{ editId?'更新替换':'创建' }}</button></div>
        </div>
      </div>
      <div v-if="delConfirm.show" class="modal-overlay" @click.self="delConfirm.show=false">
        <div class="modal-box" style="max-width:380px;text-align:center"><h3>确认删除</h3><p style="font-size:14px;color:var(--color-text-secondary);margin-bottom:20px">确定要删除策略<br><strong>「{{ delConfirm.name }}」</strong>吗？<br>此操作不可撤销。</p><div class="modal-actions" style="justify-content:center"><button class="btn btn-sm" @click="delConfirm.show=false">取消</button><button class="btn btn-sm btn-error" @click="doDelete">确认删除</button></div></div>
      </div>
    </div>
  `,
  setup() {
    const strategies = ref([]);
    const selected = ref([]);
    const typeFilter = ref('');
    const loading = ref(false);
    const showChart = ref(false);
    const showForm = ref(false);
    const editId = ref(null);
    const compareData = ref([]);
    const chartMetrics = ref([]);
    const form = reactive({ name:'', type:'trend', description:'', params_text:'{}' });
    const delConfirm = reactive({ show:false, id:null, name:'' });
    let chartInstance = null;
    // 数据交互增强
    const editingId = ref(null);
    const editingValue = ref('');
    const dragOverIdx = ref(null);
    const dragFromIdx = ref(null);
    const batchRunning = ref(false);

    function fmtPct(v) { return window.formatPct ? window.formatPct(v,2) : '--'; }
    function colorClass(v) { return window.colorClass ? window.colorClass(v) : ''; }
    function typeLabel(t) { return TYPE_LABELS[t] || t; }

    async function loadStrategies() {
      loading.value = true;
      try {
        var path = '/v1/strategies/?'; if (typeFilter.value) path += 'type='+typeFilter.value+'&';
        var d = await API.strategy(path);
        if (d.success) strategies.value = d.data || [];
      } catch(e) { if (QT && QT.Toast) QT.Toast.warning('策略加载失败，使用缓存数据'); }
      finally { loading.value = false; }
    }

    function toggleSelect(s) { var id = s.strategy_id||s.id; var idx = selected.value.indexOf(id); if (idx>=0) selected.value.splice(idx,1); else selected.value.push(id); }
    async function compareStrategies() { try { var d = await API.strategy('/v1/strategies/compare',{method:'POST',body:JSON.stringify({strategy_ids:selected.value})}); if (d.success) compareData.value=d.data||[]; } catch(e) { if(QT.Toast) QT.Toast.error('对比失败：'+e.message); } }
    async function backtestSelected() { showChart.value=true; await nextTick(); try { var id=selected.value[0]; var d=await API.strategy('/v1/strategies/'+id+'/backtest?ts_code=000001.SZ',{method:'POST'}); if (d.success&&d.data) { var r=d.data; chartMetrics.value=[{label:'总收益率',value:fmtPct(r.total_return),color:colorClass(r.total_return)},{label:'夏普比率',value:(r.sharpe_ratio||0).toFixed(2),color:''},{label:'最大回撤',value:fmtPct(r.max_drawdown),color:(r.max_drawdown||0)<0?'bear':''},{label:'胜率',value:fmtPct(r.win_rate),color:''}]; renderStrategyChart(r); } } catch(e) { if(QT.Toast) QT.Toast.error('回测失败：'+e.message); } }
    function renderStrategyChart(data) { var el=document.getElementById('strategy-chart'); if(!el) return; if(chartInstance) chartInstance.dispose(); chartInstance=QT.charts.init(el); chartInstance.setOption({tooltip:{trigger:'axis',formatter:function(p){var s='<b>'+p[0].axisValue+'</b><br/>';p.forEach(function(p2){s+=p2.marker+p2.seriesName+': <b>'+p2.value[1].toFixed(4)+'</b><br/>';});return s;}},legend:{data:['策略净值','基准'],bottom:28,icon:'roundRect',itemWidth:12,itemHeight:4},grid:{left:60,right:20,top:30,bottom:55},xAxis:{type:'category',data:data.dates||[],axisLabel:{fontSize:11}},yAxis:{type:'value',name:'净值'},series:[{name:'策略净值',type:'line',data:data.equity_curve||[],smooth:true,symbol:'none',lineStyle:{color:'#667eea',width:2},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(102,126,234,0.15)'},{offset:1,color:'rgba(102,126,234,0)'}]}}},{name:'基准',type:'line',data:data.benchmark_curve||[],smooth:true,symbol:'none',lineStyle:{color:'#999',type:'dashed',width:1},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(153,153,153,0.08)'},{offset:1,color:'rgba(153,153,153,0)'}]}}}],dataZoom:[{type:'inside',start:0,end:100}]}); }
    function newStrategy() { editId.value=null; form.name=''; form.type='trend'; form.description=''; form.params_text='{}'; showForm.value=true; }
    function editStrategy(s) { editId.value=s.strategy_id||s.id; form.name=s.name||s.strategy_name||''; form.type=s.strategy_type||s.type||'trend'; form.description=s.description||''; form.params_text=s.params?JSON.stringify(s.params,null,2):'{}'; showForm.value=true; }
    async function saveStrategy() { try { var params={}; try { params=JSON.parse(form.params_text); } catch(e) { if(QT.Toast) QT.Toast.warning('参数JSON格式错误'); return; } var body={name:form.name,strategy_type:form.type,description:form.description,params:params,status:'active'}; if(editId.value) { await API.strategy('/v1/strategies/'+editId.value,{method:'PUT',body:JSON.stringify(body)}); if(QT.Toast) QT.Toast.success('策略已更新替换'); } else { await API.strategy('/v1/strategies/',{method:'POST',body:JSON.stringify(body)}); if(QT.Toast) QT.Toast.success('策略已创建'); } showForm.value=false; await loadStrategies(); } catch(e) { if(QT.Toast) QT.Toast.error('保存失败：'+e.message); } }
    function confirmDelete(s) { delConfirm.id=s.strategy_id||s.id; delConfirm.name=s.name||s.strategy_name||'未命名'; delConfirm.show=true; }
    async function doDelete() { try { await API.strategy('/v1/strategies/'+delConfirm.id,{method:'DELETE'}); if(QT.Toast) QT.Toast.success('策略已删除'); delConfirm.show=false; if(showForm.value&&editId.value===delConfirm.id) showForm.value=false; await loadStrategies(); } catch(e) { if(QT.Toast) QT.Toast.error('删除失败：'+e.message); } }

    // --- 拖拽排序 ---
    function onDragStart(idx) { dragFromIdx.value = idx; }
    function onDragOver(idx) { if (idx !== dragFromIdx.value) dragOverIdx.value = idx; }
    function onDrop(idx) {
      if (dragFromIdx.value === null || dragFromIdx.value === idx) { dragOverIdx.value = null; dragFromIdx.value = null; return; }
      var arr = strategies.value;
      var item = arr.splice(dragFromIdx.value, 1)[0];
      arr.splice(idx, 0, item);
      strategies.value = [].concat(arr); // trigger reactivity
      dragOverIdx.value = null; dragFromIdx.value = null;
    }

    // --- 行内编辑 ---
    function startEditName(s) { editingId.value = s.strategy_id||s.id; editingValue.value = s.name||s.strategy_name||''; }
    async function saveEditName(s) {
      var id = s.strategy_id||s.id;
      if (editingId.value !== id || !editingValue.value.trim()) { editingId.value = null; return; }
      try { await API.strategy('/v1/strategies/'+id,{method:'PUT',body:JSON.stringify({name:editingValue.value.trim()})}); if(QT.Toast) QT.Toast.success('名称已更新'); s.name = editingValue.value.trim(); } catch(e) { if(QT.Toast) QT.Toast.error('更新失败'); }
      editingId.value = null;
    }
    function cancelEditName() { editingId.value = null; editingValue.value = ''; }

    // --- 批量操作 ---
    async function batchActivate() { batchRunning.value = true; var ok=0,fail=0; for(var id of selected.value) { try { await API.strategy('/v1/strategies/'+id,{method:'PUT',body:JSON.stringify({status:'active'})}); ok++; } catch(e) { fail++; } } if(QT.Toast) QT.Toast.success('已启用 '+ok+' 个策略'+(fail?'，'+fail+' 个失败':'')); batchRunning.value = false; selected.value = []; await loadStrategies(); }
    async function batchDeactivate() { batchRunning.value = true; var ok=0,fail=0; for(var id of selected.value) { try { await API.strategy('/v1/strategies/'+id,{method:'PUT',body:JSON.stringify({status:'inactive'})}); ok++; } catch(e) { fail++; } } if(QT.Toast) QT.Toast.success('已停用 '+ok+' 个策略'+(fail?'，'+fail+' 个失败':'')); batchRunning.value = false; selected.value = []; await loadStrategies(); }
    async function batchDelete() { if(!confirm('确定要删除选中的 '+selected.value.length+' 个策略？此操作不可撤销。')) return; batchRunning.value = true; var ok=0,fail=0; for(var id of selected.value) { try { await API.strategy('/v1/strategies/'+id,{method:'DELETE'}); ok++; } catch(e) { fail++; } } if(QT.Toast) QT.Toast.success('已删除 '+ok+' 个策略'+(fail?'，'+fail+' 个失败':'')); batchRunning.value = false; selected.value = []; await loadStrategies(); }

    function handleResize() { if(chartInstance) try { chartInstance.resize(); } catch(e) {} }

    onMounted(function() { loadStrategies(); window.addEventListener('resize', handleResize); });
    onUnmounted(function() { window.removeEventListener('resize', handleResize); if(chartInstance) { chartInstance.dispose(); chartInstance=null; } });

    return { strategies, selected, typeFilter, loading, showChart, showForm, editId, compareData, chartMetrics, form, delConfirm, fmtPct, colorClass, typeLabel, toggleSelect, compareStrategies, backtestSelected, renderStrategyChart, newStrategy, editStrategy, saveStrategy, confirmDelete, doDelete, editingId, editingValue, dragOverIdx, batchRunning, onDragStart, onDragOver, onDrop, startEditName, saveEditName, cancelEditName, batchActivate, batchDeactivate, batchDelete };
  }
};

/* ================================================================
   7. PageStockSelection — 选股
   ================================================================ */
const PageStockSelection = {
  template: `
    <div class="page-stock-selection">
      <div class="section">
        <h2 class="section-title">🎯 AI 选股筛选</h2>
        <div class="scan-bar">
          <select v-model="filter.strategy"><option value="all">全部策略</option><option value="ma-cross">双均线金叉</option><option value="breakout">N日突破</option><option value="rsi">RSI超卖</option><option value="multi-factor">多因子综合</option></select>
          <select v-model="filter.minScore"><option value="0">最低评分：不限</option><option value="50">50+</option><option value="70">70+</option><option value="85">85+</option></select>
          <input type="text" v-model="filter.keyword" placeholder="搜索股票代码/名称" style="width:200px;padding:8px 12px;border:0.5px solid var(--color-border);border-radius:6px;font-size:14px;background:var(--color-bg-surface);color:var(--color-text)">
          <button @click="doScan">🔍 AI 扫描选股</button>
          <span style="font-size:12px;color:var(--color-text-secondary);">上次更新: {{ lastUpdate }}</span>
        </div>
      </div>
      <div class="section">
        <h2 class="section-title">📊 选股结果（{{ filteredStocks.length }} 只）</h2>
        <div class="stock-grid" v-if="filteredStocks.length>0">
          <div class="stock-card" v-for="stock in filteredStocks" :key="stock.ts_code" @click="analyzeStock(stock.ts_code)">
            <div class="name-row"><div><div class="name">{{ stock.name||'--' }}</div><div class="code">{{ stock.ts_code }}</div></div><span class="badge" :class="'badge-'+stock.signal.toLowerCase()">{{ signalLabel(stock.signal) }}</span></div>
            <div class="indicator-grid">
              <div class="ind-item">📈 评分 <span class="val">{{ stock.score }}</span>/100</div>
              <div class="ind-item">💰 收益 <span class="val" :class="(stock.return_pct||0)>=0?'bull':'bear'">{{ (stock.return_pct||0)>=0?'+':'' }}{{ (stock.return_pct||0).toFixed(2) }}%</span></div>
              <div class="ind-item">📊 策略 <span class="val">{{ stock.best_strategy||stock.strategy_name||'--' }}</span></div>
              <div class="ind-item" :class="(stock.return_pct||0)>=0?'bull':'bear'">夏普 <span class="val">{{ (stock.sharpe||0).toFixed(2) }}</span></div>
            </div>
            <div class="signal-row"><span class="score">{{ stock.reason }}</span><span style="font-size:12px;color:var(--color-text-secondary);">{{ stock.generated_at||'' }}</span></div>
          </div>
        </div>
        <div v-else-if="!scanning" class="loading" style="text-align:center;padding:60px;color:var(--color-text-secondary)">暂无选股结果，点击"AI 扫描选股"开始</div>
      </div>
      <div v-if="scanning" class="loading">🤖 AI模型正在扫描全市场... (此过程约需30秒)</div>
    </div>
  `,
  setup() {
    const stocks = ref([]);
    const filter = ref({ strategy:'all', minScore:'0', keyword:'' });
    const scanning = ref(false);
    const lastUpdate = ref('--');

    const filteredStocks = computed(function() {
      var result = stocks.value;
      if (filter.value.strategy !== 'all') result = result.filter(function(s){return s.strategy_name===filter.value.strategy;});
      var min = parseInt(filter.value.minScore);
      if (min > 0) result = result.filter(function(s){return s.score >= min;});
      if (filter.value.keyword) { var kw = filter.value.keyword.toUpperCase(); result = result.filter(function(s){return (s.ts_code||'').includes(kw)||(s.name||'').includes(kw);}); }
      return result.sort(function(a,b){return b.score-a.score;});
    });

    function signalLabel(s) { return ({BUY:'买入',SELL:'卖出',HOLD:'持有'}[s]||s); }

    async function doScan() {
      scanning.value = true;
      try {
        var data = await API.strategy('/v1/ai/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({strategy:filter.value.strategy,top_n:20})});
        if (data.success) { stocks.value = data.data || data.results || []; lastUpdate.value = new Date().toLocaleTimeString('zh-CN'); }
      } catch(e) { stocks.value = []; }
      finally { scanning.value = false; }
    }

    function analyzeStock(code) { Toast.info('AI分析跳转：正在分析 '+code+'...\n\n（完整AI多智能体分析功能开发中）'); }

    onMounted(async function() { await doScan(); });

    return { stocks, filter, filteredStocks, scanning, lastUpdate, signalLabel, doScan, analyzeStock };
  }
};

/* ================================================================
   8. PageReviewAnalysis — 复盘分析
   ================================================================ */
const PageReviewAnalysis = {
  template: `
    <div class="page-review-analysis">
      <div class="date-bar">
        <span class="title">📅 复盘分析</span>
        <div class="date-picker"><input type="date" v-model="reviewDate" :max="today" @change="loadReview"><button class="btn-reload" @click="loadReview">🔄 生成报告</button></div>
      </div>
      <div class="section" v-if="review&&review.summary">
        <div class="summary-grid">
          <div class="summary-card"><div class="label">上证指数</div><div class="value" :class="(review.summary.sh_pct||0)>=0?'bull':'bear'">{{ (review.summary.sh_close||0).toFixed(2) }}</div><div class="trend" :class="(review.summary.sh_pct||0)>=0?'bull':'bear'">{{ (review.summary.sh_pct||0)>=0?'+':'' }}{{((review.summary.sh_pct||0)*100).toFixed(2)}}%</div></div>
          <div class="summary-card"><div class="label">深证成指</div><div class="value" :class="(review.summary.sz_pct||0)>=0?'bull':'bear'">{{ (review.summary.sz_close||0).toFixed(2) }}</div><div class="trend" :class="(review.summary.sz_pct||0)>=0?'bull':'bear'">{{ (review.summary.sz_pct||0)>=0?'+':'' }}{{((review.summary.sz_pct||0)*100).toFixed(2)}}%</div></div>
          <div class="summary-card"><div class="label">上涨家数</div><div class="value red">{{ review.summary.up_count }}</div><div class="trend">家</div></div>
          <div class="summary-card"><div class="label">下跌家数</div><div class="value green">{{ review.summary.down_count }}</div><div class="trend">家</div></div>
          <div class="summary-card"><div class="label">涨停家数</div><div class="value red">{{ review.summary.limit_up }}</div><div class="trend">家</div></div>
          <div class="summary-card"><div class="label">跌停家数</div><div class="value green">{{ review.summary.limit_down }}</div><div class="trend">家</div></div>
        </div>
      </div>
      <div class="section" v-if="review&&review.strategy_perf"><div id="rv-strategy-chart" class="chart-box" style="height:320px"></div></div>
      <div class="analysis-columns" v-if="review&&(review.content||review.risk_warnings)">
        <div class="analysis-panel" v-if="review.content"><div class="panel-title"><span class="icon">🤖</span> AI 复盘分析</div><div class="review-content" v-html="formattedContent"></div></div>
        <div class="analysis-panel" v-if="review.risk_warnings"><div class="panel-title"><span class="icon">⚠️</span> 风险提示与优化建议</div><div class="review-content" v-html="formattedWarnings"></div></div>
      </div>
      <div v-if="!review&&!loading" style="text-align:center;padding:60px;color:var(--color-text-secondary)">📭 选择日期后自动加载复盘报告</div>
      <div v-if="loading" class="loading">🤖 AI 模型正在分析当日市场数据，请稍候...</div>
    </div>
  `,
  setup() {
    const review = ref(null);
    const reviewDate = ref(new Date().toISOString().slice(0,10));
    const today = ref(new Date().toISOString().slice(0,10));
    const loading = ref(false);
    let chartInstance = null;

    const formattedContent = computed(function() {
      if (!review.value || !review.value.content) return '';
      var html = review.value.content;
      html = html.replace(/^## (.+)$/gm,'<h2>$1</h2>');
      html = html.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
      html = html.replace(/^(\d+)\. (.+)$/gm,'<div class="review-item"><span class="num">$1.</span>$2</div>');
      html = html.replace(/\n\n/g,'<br><br>').replace(/\n/g,'<br>');
      return html;
    });

    const formattedWarnings = computed(function() {
      if (!review.value || !review.value.risk_warnings) return '';
      var html = review.value.risk_warnings;
      html = html.replace(/^## (.+)$/gm,'<h2>$1</h2>');
      html = html.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
      html = html.replace(/^(\d+)\. (.+)$/gm,'<div class="review-item"><span class="num">$1.</span>$2</div>');
      html = html.replace(/\n\n/g,'<br><br>').replace(/\n/g,'<br>');
      return html;
    });

    function renderStrategyChart(reviewData) {
      var dom = document.getElementById('rv-strategy-chart');
      if (!dom) return;
      if (chartInstance) chartInstance.dispose();
      chartInstance = QT.charts.init(dom);
      var perfData = reviewData && reviewData.strategy_performance ? reviewData.strategy_performance : null;
      if (perfData && perfData.months && perfData.series) {
        chartInstance.setOption({tooltip:{trigger:'axis'},legend:{data:perfData.series.map(function(s){return s.name;}),bottom:28,icon:'roundRect',itemWidth:12,itemHeight:4},grid:{left:60,right:20,top:20,bottom:55},xAxis:{type:'category',data:perfData.months},yAxis:{type:'value',axisLabel:{formatter:function(v){return(v*100).toFixed(0)+'%'}}},series:perfData.series.map(function(s){return{name:s.name,type:'line',data:s.data,smooth:true,symbol:'none',areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(102,126,234,0.1)'},{offset:1,color:'rgba(102,126,234,0)'}]}}};}),dataZoom:[{type:'inside',start:0,end:100}]});
      } else {
        chartInstance.setOption({title:{text:'策略数据待API返回',left:'center',top:'middle',textStyle:{color:'#999',fontSize:14}},xAxis:{show:false},yAxis:{show:false},series:[]});
      }
    }

    async function loadReview() {
      loading.value = true;
      try {
        var data = await API.strategy('/v1/ai/review?date='+reviewDate.value);
        if (data.success) { review.value = data.data; setTimeout(function(){renderStrategyChart(data.data);},200); }
      } catch(e) { review.value = null; }
      finally { loading.value = false; }
    }

    function handleResize() { if(chartInstance) try { chartInstance.resize(); } catch(e) {} }

    onMounted(function() { loadReview(); window.addEventListener('resize', handleResize); });
    onUnmounted(function() { window.removeEventListener('resize', handleResize); if(chartInstance) { chartInstance.dispose(); chartInstance=null; } });

    return { review, reviewDate, today, loading, formattedContent, formattedWarnings, loadReview };
  }
};

/* ================================================================
   9. PageAlerts — 告警管理
   ================================================================ */
const PageAlerts = {
  template: `
    <div class="page-alerts">
      <div class="main">
        <div class="card">
          <div class="card-title">告警配置</div>
          <div class="config-grid">
            <div class="config-card" v-for="cfg in alertTypes" :key="cfg.key"><div class="icon">{{ cfg.icon }}</div><div class="info"><h4>{{ cfg.name }}</h4><p>{{ cfg.desc }}</p></div><label class="toggle"><input type="checkbox" v-model="alertConfig[cfg.key]" @change="saveConfig"><span class="slider"></span></label></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title"><span>系统健康监控</span><button class="refresh-btn" @click="fetchHealth">刷新</button></div>
          <div class="health-grid">
            <div class="health-card" v-for="svc in services" :key="svc.name"><div class="service-name">{{ svc.label }}</div><div class="status-row"><span class="dot" :class="svc.dotClass"></span><span class="status-text">{{ svc.statusText }}</span></div><div class="last-check">上次检测: {{ svc.lastCheck }}</div></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title"><span>告警历史</span><div class="filter-row"><select v-model="levelFilter"><option value="">全部级别</option><option value="信息">信息</option><option value="警告">警告</option><option value="严重">严重</option></select></div></div>
          <div class="table-wrap">
            <table><thead><tr><th>时间</th><th>级别</th><th>类型</th><th>内容</th></tr></thead>
              <tbody>
                <tr v-if="filteredAlerts.length===0"><td colspan="4" style="text-align:center;color:#999;padding:24px;">暂无告警记录</td></tr>
                <tr v-for="(a,idx) in filteredAlerts" :key="idx"><td style="font-size:12px;color:var(--color-text-secondary)">{{ a.time }}</td><td><span class="badge" :class="levelBadge(a.level)">{{ a.level }}</span></td><td>{{ a.type }}</td><td>{{ a.content }}</td></tr>
              </tbody>
            </table>
          </div>
          <div class="note">💡 告警历史来自飞书群消息记录</div>
        </div>
        <div class="card">
          <div class="card-title">测试告警</div>
          <p style="font-size:13px;color:var(--color-text-secondary);margin-bottom:16px">发送一条测试告警到飞书群，验证 Webhook 是否正常工作。</p>
          <button class="btn btn-primary" @click="sendTestAlert" :disabled="testingSending">{{ testingSending?'发送中...':'发送测试告警' }}</button>
        </div>
      </div>
    </div>
  `,
  setup() {
    const testingSending = ref(false);
    const levelFilter = ref('');
    const alertTypes = [
      {key:'trade',icon:'💰',name:'交易告警',desc:'订单成交/拒绝/超时通知'},
      {key:'risk',icon:'🛡️',name:'风控告警',desc:'止损/止盈/仓位超限'},
      {key:'system',icon:'⚙️',name:'系统告警',desc:'服务宕机/连接异常'},
      {key:'report',icon:'📊',name:'定时报告',desc:'日报/周报/月报推送'},
    ];
    const alertConfig = reactive({ trade:true, risk:true, system:true, report:false });
    const services = ref([
      {name:'strategy-service',label:'策略研究服务',url:window.APP_CONFIG?APP_CONFIG.apiBase:'',dotClass:'dot-gray',statusText:'检测中...',lastCheck:'--'},
      {name:'execution-service',label:'交易执行服务',url:(window.APP_CONFIG?APP_CONFIG.apiBase:'')+'/api/v1/execution',dotClass:'dot-gray',statusText:'检测中...',lastCheck:'--'},
      {name:'ai-scheduler',label:'AI智能调度器',url:(window.APP_CONFIG?APP_CONFIG.apiBase:'')+'/api/v1/scheduler',dotClass:'dot-gray',statusText:'检测中...',lastCheck:'--'}
    ]);
    const alertHistory = ref([]);
    let healthTimer = null;

    const AI_SCHEDULER_BASE = (window.APP_CONFIG?APP_CONFIG.apiBase:'')+'/api/v1/scheduler';

    function loadConfig() { try { var saved=localStorage.getItem('quant_alert_config'); if(saved) Object.assign(alertConfig,JSON.parse(saved)); } catch(e) {} }
    function saveConfig() { localStorage.setItem('quant_alert_config',JSON.stringify(toRaw(alertConfig))); Toast.success('配置已保存'); }

    async function fetchHealth() {
      try {
        var resp = await fetch(AI_SCHEDULER_BASE+'/health-monitor/status');
        if(!resp.ok) throw Error('API error');
        var data = await resp.json();
        var now = new Date().toLocaleTimeString('zh-CN');
        var svcData = data.data || data.services || data;
        services.value.forEach(function(svc) {
          var info = svcData[svc.name] || svcData[svc.label];
          if (info !== undefined) {
            var healthy = info===true || info.status==='healthy'||info.status==='up'||info.healthy===true;
            svc.dotClass = healthy ? 'dot-green' : 'dot-red';
            svc.statusText = healthy ? '正常运行' : '服务异常';
          } else { svc.dotClass='dot-gray'; svc.statusText='未知'; }
          svc.lastCheck = now;
        });
      } catch(e) {
        // Fallback: probe each service directly
        var now = new Date().toLocaleTimeString('zh-CN');
        for (var svc of services.value) {
          try { var r = await fetch(svc.url+'/health',{signal:AbortSignal.timeout(3000)}); if(r.ok) { svc.dotClass='dot-green'; svc.statusText='正常运行'; } else { svc.dotClass='dot-red'; svc.statusText='异常'; } } catch(err) { svc.dotClass='dot-gray'; svc.statusText='检测中...'; }
          svc.lastCheck = now;
        }
      }
    }

    async function fetchAlerts() {
      try { var data = await API.strategy('/v1/alerts?limit=50'); if(data.success&&data.data) alertHistory.value=data.data; } catch(e) {}
    }

    const filteredAlerts = computed(function() {
      if (!levelFilter.value) return alertHistory.value;
      return alertHistory.value.filter(function(a){return a.level===levelFilter.value;});
    });

    function levelBadge(level) { var map={'信息':'badge-info','警告':'badge-warning','严重':'badge-critical'}; return map[level]||'badge-info'; }

    async function sendTestAlert() {
      testingSending.value = true;
      try { var resp = await fetch(AI_SCHEDULER_BASE+'/health-monitor/test-alert',{method:'POST'}); Toast.success('测试告警已发送到飞书群'); } catch(e) { Toast.error('测试告警发送失败：告警服务未连接'); }
      finally { testingSending.value = false; }
    }

    onMounted(function() { loadConfig(); fetchHealth(); healthTimer=setInterval(fetchHealth,30000); fetchAlerts(); });
    onUnmounted(function() { if(healthTimer) clearInterval(healthTimer); });

    return { alertConfig, alertTypes, saveConfig, services, fetchHealth, alertHistory, filteredAlerts, levelFilter, levelBadge, testingSending, sendTestAlert };
  }
};

/* ================================================================
   10. PageApiDocs — API 文档（iframe 嵌入）
   ================================================================ */
const PageApiDocs = {
  template: '<div class="page-api-docs" style="padding:0"><iframe src="api-docs.html" title="API 文档" loading="lazy"></iframe></div>',
  setup() { return {}; }
};

/* ================================================================
   11. PageReports — 回测报告总览（策略深度分析）
   ================================================================ */
const STRAT_CONFIG = {
  'vwm':          { label: 'VWM 趋势',      color: '#6366f1' },
  'bollinger':    { label: 'BBR 均值回归',   color: '#f59e0b' },
  'combo-vwm-bbr':{ label: 'COMBO 组合',     color: '#22c55e' },
  'adx':          { label: 'ADX 趋势强度',   color: '#ef4444' },
  'vbm':          { label: 'VBM 短线动量',   color: '#06b6d4' },
};

const PageReports = {
  template: `
    <div class="page-reports" style="padding: 0 0 40px;">
      <div class="section-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
        <h2 style="font-size:20px;font-weight:500;">📊 策略回测深度分析报告</h2>
        <span style="font-size:13px;color:var(--color-text-secondary);">22只股票 × 5策略 | 回测区间: 2025-06-01 ~ 2026-06-17</span>
      </div>

      <!-- 策略概览卡片 -->
      <div class="report-cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:24px;">
        <div v-for="s in strategies" :key="s.key" class="strat-card" :style="{borderTop:'3px solid '+s.color,background:'var(--color-bg-surface)',borderRadius:'12px',padding:'16px',border:'0.5px solid var(--color-border)'}">
          <div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:4px;">{{ s.label }}</div>
          <div :style="{fontSize:'22px',fontWeight:500,color:s.avgReturn>=0?'var(--color-bull)':'var(--color-bear)'}">{{ fmtPct(s.avgReturn) }}</div>
          <div style="display:flex;gap:12px;margin-top:8px;font-size:11px;color:var(--color-text-secondary);">
            <span>夏普 {{ s.avgSharpe.toFixed(2) }}</span>
            <span>胜率 {{ s.winRate }}%</span>
            <span>交易 {{ s.totalTrades }}笔</span>
          </div>
        </div>
      </div>

      <!-- 策略对比柱状图 -->
      <div class="card" style="margin-bottom:20px;">
        <div class="card-header">📈 策略收益对比</div>
        <div id="bt-compare-chart" style="height:360px;"></div>
      </div>

      <!-- 行业分析 -->
      <div class="card-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;">
        <div class="card">
          <div class="card-header">🏭 行业胜率矩阵</div>
          <div id="bt-sector-chart" style="height:280px;"></div>
        </div>
        <div class="card">
          <div class="card-header">📊 策略排名分布</div>
          <div id="bt-rank-chart" style="height:280px;"></div>
        </div>
      </div>

      <!-- 策略排名表 -->
      <div class="card" style="margin-bottom:20px;">
        <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;">
          <span>🏆 策略综合排名（按 COMBO 收益排序）</span>
          <select v-model="sortStrat" @change="sortStratChanged" style="padding:4px 10px;border:1px solid var(--color-border);border-radius:6px;font-size:12px;background:var(--color-bg-surface);color:var(--color-text);">
            <option value="combo-vwm-bbr">COMBO 排序</option>
            <option value="vwm">VWM 排序</option>
            <option value="bollinger">BBR 排序</option>
            <option value="adx">ADX 排序</option>
          </select>
        </div>
        <div style="overflow-x:auto;">
          <table class="data-table" style="width:100%;font-size:13px;">
            <thead>
              <tr>
                <th>股票</th>
                <th>行业</th>
                <th v-for="s in stratKeys" :key="s" :style="{color:STRAT_CONFIG[s]?.color}">{{ STRAT_CONFIG[s]?.label||s }}</th>
                <th>最佳策略</th>
                <th>最差策略</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in sortedStocks" :key="row.code" style="cursor:pointer;" @click="showStockDetail(row)">
                <td><strong>{{ row.name }}</strong><br><span style="font-size:11px;color:var(--color-text-secondary);">{{ row.code }}</span></td>
                <td><span class="badge-sector">{{ row.sector||'--' }}</span></td>
                <td v-for="s in stratKeys" :key="s" :style="{color: getReturnColor(row.returns[s])}">{{ fmtPct2(row.returns[s]) }}</td>
                <td><span :style="{color:STRAT_CONFIG[row.bestStrat]?.color}">{{ STRAT_CONFIG[row.bestStrat]?.label||row.bestStrat }}</span></td>
                <td><span :style="{color:STRAT_CONFIG[row.worstStrat]?.color,opacity:0.6}">{{ STRAT_CONFIG[row.worstStrat]?.label||row.worstStrat }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 个股详情弹窗 -->
      <div v-if="detailStock" class="modal-overlay" @click.self="detailStock=null" style="z-index:300;">
        <div class="modal-box" style="max-width:500px;padding:24px;">
          <h3 style="margin:0 0 4px;">{{ detailStock.name }} <span style="font-size:13px;color:var(--color-text-secondary);">{{ detailStock.code }}</span></h3>
          <div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:16px;">{{ detailStock.sector||'--' }}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div v-for="s in stratKeys" :key="s" style="padding:8px 12px;background:var(--color-bg-hover);border-radius:8px;">
              <div style="font-size:11px;color:var(--color-text-secondary);margin-bottom:2px;">{{ STRAT_CONFIG[s]?.label||s }}</div>
              <div :style="{fontSize:'16px',fontWeight:500,color:getReturnColor(detailStock.returns[s])}">{{ fmtPct2(detailStock.returns[s]) }}</div>
              <div v-if="detailStock.trades" style="font-size:11px;color:var(--color-text-secondary);margin-top:2px;">{{ detailStock.trades[s]||0 }}笔交易</div>
            </div>
          </div>
          <div v-if="detailStock.btUrl" style="margin-top:16px;text-align:center;">
            <a :href="detailStock.btUrl" target="_blank" class="btn btn-primary" style="text-decoration:none;padding:8px 20px;display:inline-block;">查看详细回测报告 →</a>
          </div>
          <button style="margin-top:12px;display:block;width:100%;padding:8px;border:1px solid var(--color-border);border-radius:8px;background:var(--color-bg-surface);cursor:pointer;font-size:13px;" @click="detailStock=null">关闭</button>
        </div>
      </div>

      <div v-if="!loaded" style="text-align:center;padding:60px;color:var(--color-text-secondary);">
        <div style="font-size:32px;margin-bottom:12px;">🔄</div>
        <p>加载回测数据中...</p>
      </div>
    </div>
  `,
  setup() {
    const { ref, computed, onMounted, onUnmounted, nextTick, watch } = Vue;
    const loaded = ref(false);
    const rawData = ref({});
    const strategies = ref([]);
    const stocks = ref([]);
    const sortStrat = ref('combo-vwm-bbr');
    const detailStock = ref(null);

    const stratKeys = Object.keys(STRAT_CONFIG);

    function fmtPct(v) {
      if (v==null) return '--';
      return (v>=0?'+':'')+(v*100).toFixed(2)+'%';
    }
    function fmtPct2(v) {
      if (v==null) return '--';
      return (v>=0?'+':'')+(v*100).toFixed(2)+'%';
    }
    function getReturnColor(v) {
      if (v==null) return 'var(--color-text-secondary)';
      return v>=0 ? 'var(--color-bull)' : 'var(--color-bear)';
    }

    const sortedStocks = computed(() => {
      const s = stocks.value.slice();
      const key = sortStrat.value;
      s.sort((a,b) => (b.returns[key]||-999) - (a.returns[key]||-999));
      return s;
    });

    function loadData() {
      fetch('bt_report_data.json')
        .then(r => r.json())
        .then(data => {
          rawData.value = data;
          processData(data);
          loaded.value = true;
          nextTick(() => { renderCharts(); });
        })
        .catch(e => { console.error('Failed to load report data:', e); loaded.value = true; });
    }

    function processData(data) {
      const sectors = {};
      const allCodes = Object.keys(data);
      const stockList = [];

      allCodes.forEach(code => {
        const d = data[code];
        const returns = {};
        const trades = {};
        let bestStrat = null, worstStrat = null;
        let bestRet = -Infinity, worstRet = Infinity;

        stratKeys.forEach(s => {
          if (d[s]) {
            const ret = d[s].total_return || 0;
            returns[s] = ret;
            trades[s] = d[s].total_trades || 0;
            if (ret > bestRet) { bestRet = ret; bestStrat = s; }
            if (ret < worstRet) { worstRet = ret; worstStrat = s; }
          } else {
            returns[s] = null;
            trades[s] = 0;
          }
        });

        const nameMap = {
          '002049.SZ':'紫光国微','600498.SH':'烽火通信','000725.SZ':'京东方A','600522.SH':'中天科技',
          '002601.SZ':'龙佰集团','600206.SH':'有研新材','000001.SZ':'平安银行','000333.SZ':'美的集团',
          '002415.SZ':'海康威视','600519.SH':'贵州茅台','601318.SH':'中国平安','000858.SZ':'五粮液',
          '600036.SH':'招商银行','600276.SH':'恒瑞医药','600887.SH':'伊利股份','600570.SH':'恒生电子',
          '600585.SH':'海螺水泥','600893.SH':'航发动力','601899.SH':'紫金矿业','002230.SZ':'科大讯飞',
          '300750.SZ':'宁德时代','688981.SH':'中芯国际'
        };
        const sectorMap = {
          '002049':'科技/半导体','600498':'科技/通信','000725':'科技/面板','600522':'科技/通信',
          '002601':'周期/化工','600206':'科技/材料','000001':'金融/银行','000333':'消费/家电',
          '002415':'科技/安防','600519':'消费/白酒','601318':'金融/保险','000858':'消费/白酒',
          '600036':'金融/银行','600276':'医药/创新药','600887':'消费/食品','600570':'科技/软件',
          '600585':'周期/建材','600893':'军工/航空','601899':'周期/黄金','002230':'科技/AI',
          '300750':'新能源/电池','688981':'科技/半导体'
        };
        const sector = sectorMap[code.slice(0,6)] || '其他';
        if (!sectors[sector]) sectors[sector] = { stocks:[], returns:{}, count:0 };
        sectors[sector].stocks.push(code);
        sectors[sector].count++;
        stratKeys.forEach(s => {
          if (returns[s] != null) {
            if (!sectors[sector].returns[s]) sectors[sector].returns[s] = [];
            sectors[sector].returns[s].push(returns[s]);
          }
        });

        stockList.push({
          code, name: nameMap[code]||code,
          sector, returns, trades,
          bestStrat, worstStrat,
          btUrl: 'bt_report_'+code.replace('.','_').replace('SH','SH').replace('SZ','SZ')+'.html'
        });
      });

      stocks.value = stockList;

      // Compute strategy-level averages
      const stratAvgs = {};
      const stratWinRates = {};
      const stratTotalTrades = {};
      stratKeys.forEach(s => {
        const vals = [];
        let wins = 0, total = 0;
        let trades = 0;
        stockList.forEach(st => {
          if (st.returns[s] != null) {
            vals.push(st.returns[s]);
            total++;
            if (st.returns[s] > 0) wins++;
            trades += st.trades[s]||0;
          }
        });
        if (vals.length > 0) {
          stratAvgs[s] = vals.reduce((a,b)=>a+b,0)/vals.length;
          stratWinRates[s] = total>0 ? Math.round(wins/total*100) : 0;
          stratTotalTrades[s] = trades;
        }
      });

      strategies.value = stratKeys.map(s => ({
        key: s,
        label: STRAT_CONFIG[s]?.label||s,
        color: STRAT_CONFIG[s]?.color||'#666',
        avgReturn: stratAvgs[s]||0,
        avgSharpe: stockList.reduce((sum,st) => sum + ((st.returns[s]!=null)?0:0), 0) ?
          stockList.filter(st=>st.returns[s]!=null).reduce((sum,st)=> sum + ((rawData.value[st.code]&&rawData.value[st.code][s]?.sharpe_ratio)||0), 0)
          / stockList.filter(st=>st.returns[s]!=null).length : 0,
        winRate: stratWinRates[s]||0,
        totalTrades: stratTotalTrades[s]||0,
      }));

      // Fix sharpe calculation
      strategies.value.forEach(s => {
        const vals = [];
        stockList.forEach(st => {
          const d = rawData.value[st.code];
          if (d && d[s.key] && d[s.key].sharpe_ratio != null) {
            vals.push(d[s.key].sharpe_ratio);
          }
        });
        s.avgSharpe = vals.length>0 ? vals.reduce((a,b)=>a+b,0)/vals.length : 0;
      });
    }

    function renderCharts() {
      // Chart 1: Strategy comparison bar chart
      const chart1 = echarts.init(document.getElementById('bt-compare-chart'));
      chart1.setOption({
        tooltip: { trigger:'axis', axisPointer:{type:'shadow'} },
        grid: { left:60, right:20, top:20, bottom:60 },
        xAxis: { type:'category', data: strategies.value.map(s=>s.label), axisLabel:{color:'var(--color-text-secondary)'} },
        yAxis: { type:'value', axisLabel:{formatter:'{value}%',color:'var(--color-text-secondary)'} },
        series: [{
          type:'bar', data: strategies.value.map(s => ({
            value: +(s.avgReturn*100).toFixed(2),
            itemStyle: { color: s.color, borderRadius:[6,6,0,0] }
          })),
          barWidth: '50%',
          label: { show:true, position:'top', formatter:'{c}%', color:'var(--color-text)', fontSize:12 }
        }]
      });

      // Chart 2: Sector win rate matrix
      const sectorGroups = {};
      stocks.value.forEach(st => {
        if (!sectorGroups[st.sector]) sectorGroups[st.sector] = [];
        sectorGroups[st.sector].push(st);
      });
      const sectorNames = Object.keys(sectorGroups).slice(0,10);
      const chart2 = echarts.init(document.getElementById('bt-sector-chart'));
      chart2.setOption({
        tooltip: { trigger:'axis' },
        legend: { data: stratKeys.map(s=>STRAT_CONFIG[s].label), textStyle:{color:'var(--color-text-secondary)',fontSize:11} },
        grid: { left:50, right:20, top:30, bottom:20 },
        xAxis: { type:'category', data: sectorNames, axisLabel:{rotate:20,fontSize:10,color:'var(--color-text-secondary)'} },
        yAxis: { type:'value', axisLabel:{formatter:'{value}%',color:'var(--color-text-secondary)'}, min:-5, max:20 },
        series: stratKeys.map(s => ({
          name: STRAT_CONFIG[s].label,
          type:'bar', stack: 'total',
          data: sectorNames.map(sn => {
            const avgs = sectorGroups[sn].map(st => st.returns[s]).filter(v=>v!=null);
            return avgs.length>0 ? +(avgs.reduce((a,b)=>a+b,0)/avgs.length*100).toFixed(2) : 0;
          }),
          itemStyle: { color: STRAT_CONFIG[s].color, borderRadius:0 },
          barWidth: 12,
        }))
      });

      // Chart 3: Top/Bottom stocks pie - actually show distribution
      const chart3 = echarts.init(document.getElementById('bt-rank-chart'));
      const bestCounts = {};
      stocks.value.forEach(st => {
        if (st.bestStrat) bestCounts[st.bestStrat] = (bestCounts[st.bestStrat]||0) + 1;
      });
      chart3.setOption({
        tooltip: { trigger:'item', formatter:'{b}: {c}只 ({d}%)' },
        series: [{
          type:'pie', radius:['30%','60%'], center:['50%','55%'],
          label: { color:'var(--color-text)', fontSize:11 },
          data: Object.entries(bestCounts).map(([k,v]) => ({
            name: STRAT_CONFIG[k]?.label||k,
            value: v,
            itemStyle: { color: STRAT_CONFIG[k]?.color||'#666', borderRadius:4 }
          }))
        }]
      });

      // Resize handler
      const resizeAll = () => { chart1.resize(); chart2.resize(); chart3.resize(); };
      window.addEventListener('resize', resizeAll);
    }

    function sortStratChanged() { /* computed handles it */ }
    function showStockDetail(stock) { detailStock.value = stock; }

    onMounted(() => { loadData(); });

    return {
      loaded, strategies, stocks, sortStrat, stratKeys, sortedStocks,
      STRAT_CONFIG, detailStock,
      fmtPct, fmtPct2, getReturnColor,
      sortStratChanged, showStockDetail
    };
  }
};

/* ================================================================
   Route Map
   ================================================================ */
const routes = {
  '/': PageHome,
  '/account': PageAccount,
  '/orders': PageOrders,
  '/trade-analysis': PageTradeAnalysis,
  '/backtest': PageBacktest,
  '/strategies': PageStrategies,
  '/reports': PageReports,
  '/stock-selection': PageStockSelection,
  '/review-analysis': PageReviewAnalysis,
  '/alerts': PageAlerts,
  '/api-docs': PageApiDocs,
};

/* ================================================================
   SPA Router App
   ================================================================ */
createApp({
  setup() {
    const currentPage = shallowRef(null);
    const routeKey = ref(0);

    function syncRoute() {
      var hash = window.location.hash.slice(1) || '/';
      var page = routes[hash] || null;
      if (!page) {
        // try prefix match
        for (var key in routes) {
          if (key !== '/' && hash.startsWith(key)) { page = routes[key]; break; }
        }
      }
      // 安全网：页面切换前销毁上一页遗漏的未回收图表
      if (window.QT && QT.charts) QT.charts.disposeAll();
      currentPage.value = page || PageHome;
      routeKey.value++;
      updateActiveNav(hash);
    }

    // 拦截导航链接的点击事件，确保 SPA 内导航正确
    document.addEventListener('click', function(e) {
      var target = e.target.closest('a[href^="#"]');
      if (target) {
        var href = target.getAttribute('href');
        if (href) {
          var route = href.slice(2) || '/';
          updateActiveNav(route);
        }
      }
    });

    onMounted(function() {
      syncRoute();
      window.addEventListener('hashchange', syncRoute);
    });

    return { currentPage, routeKey };
  }
}).mount('#app');

})();
