const { createApp, reactive, computed, onMounted, onUnmounted, ref } = Vue;

createApp({
  setup() {
    const summary = reactive({ total_assets: 0, available_cash: 0, market_value: 0, day_pnl: 0 });
    const positions = ref([]);
    const orders = ref([]);
    const orderFilter = ref('');
    const errorMsg = ref('');
    const loading = ref(true);
    const submitting = ref(false);
    const wsStatus = ref('⏳ 连接中...');
    let pollTimer = null;

    const order = reactive({
      ts_code: '', direction: 'BUY', order_type: 'LIMIT', price: null, quantity: 100, trigger_price: null
    });

    const modal = reactive({
      visible: false, title: '', message: '', confirmText: '确认', onConfirm: () => {}
    });

    const pnlClass = computed(() => summary.day_pnl >= 0 ? 'bull' : 'bear');

    function formatMoney(v) { return window.formatMoney ? window.formatMoney(v) : '--'; }
    function formatPct(v) { return window.formatPct ? window.formatPct(v, 2) : '--'; }
    function colorClass(v) { return window.colorClass ? window.colorClass(v) : ''; }
    function timeAgo(v) { return window.timeAgo ? window.timeAgo(v) : v; }
    function statusBadge(s) {
      if (s === 'FILLED') return 'badge-success';
      if (s === 'PENDING') return 'badge-warning';
      if (s === 'REJECTED' || s === 'CANCELLED') return 'badge-error';
      return 'badge-info';
    }

    async function loadSummary() {
      try {
        const d = await API.execution('/v1/positions/summary?account_id=REAL_001');
        if (d.code === 0) {
          Object.assign(summary, d.data);
        }
      } catch (e) { console.debug('摘要加载失败:', e.message); }
    }

    async function loadPositions() {
      try {
        const d = await API.execution('/v1/positions/?account_id=REAL_001');
        if (d.code === 0) positions.value = d.data || [];
        errorMsg.value = '';
      } catch (e) { console.debug('持仓加载失败:', e.message); }
    }

    async function loadOrders() {
      try {
        let path = '/v1/orders/?account_id=REAL_001&limit=50';
        if (orderFilter.value) path += '&status=' + orderFilter.value;
        const d = await API.execution(path);
        if (d.code === 0) orders.value = d.data || [];
        errorMsg.value = '';
      } catch (e) { errorMsg.value = '连接失败：' + e.message; }
    }

    async function loadAll() {
      loading.value = true;
      await Promise.all([loadSummary(), loadPositions(), loadOrders()]);
      loading.value = false;
    }

    async function submitOrder() {
      if (!order.ts_code) { Toast.warning('请输入股票代码'); return; }
      submitting.value = true;
      try {
        const body = {
          ts_code: order.ts_code,
          direction: order.direction,
          order_type: order.order_type,
          price: order.price,
          quantity: order.quantity,
          trigger_price: order.order_type === 'STOP' ? order.trigger_price : null
        };
        const d = await API.execution('/v1/orders/submit', {
          method: 'POST', body: JSON.stringify(body)
        });
        if (d.code === 0) {
          Toast.success('订单已提交');
          await loadAll();
        } else {
          Toast.warning(d.message || '下单失败');
        }
      } catch (e) {
        Toast.error('下单失败：' + e.message);
      } finally {
        submitting.value = false;
      }
    }

    function confirmCancel(o) {
      modal.title = '撤销订单';
      modal.message = `确认撤销订单 ${o.order_id?.slice(-8)}？（${o.ts_code} ${o.direction} ${o.quantity}股）`;
      modal.confirmText = '确认撤单';
      modal.onConfirm = async () => {
        try {
          await API.execution('/v1/orders/' + o.order_id + '/cancel', { method: 'POST' });
          Toast.success('订单已撤销');
          modal.visible = false;
          await loadOrders();
        } catch (e) { Toast.error('撤单失败：' + e.message); }
      };
      modal.visible = true;
    }

    function confirmClose(p) {
      modal.title = '平仓确认';
      modal.message = `确认以现价 ${p.current_price || '?'} 平仓 ${p.ts_code}（${p.available_quantity || p.total_quantity} 股）？`;
      modal.confirmText = '确认平仓';
      modal.onConfirm = async () => {
        try {
          const d = await API.execution('/v1/positions/close', {
            method: 'POST',
            body: JSON.stringify({
              ts_code: p.ts_code,
              quantity: p.available_quantity || p.total_quantity,
              price: p.current_price || p.cost_price
            })
          });
          if (d.code === 0) {
            Toast.success('平仓成功');
            modal.visible = false;
            await loadAll();
          } else {
            Toast.error(d.message || '平仓失败');
          }
        } catch (e) { Toast.error('平仓失败：' + e.message); }
      };
      modal.visible = true;
    }

    // WebSocket 实时更新
    let wsUnsub = null;
    onMounted(() => {
      loadAll();
      pollTimer = setInterval(async () => { await loadSummary(); await loadPositions(); }, 10000);

      try {
        const ws = getWSManager('execution');
        wsUnsub = ws.on('order_update', (data) => {
          loadOrders();
          loadSummary();
        });
        ws.on('connect', () => { wsStatus.value = '🟢 实时连接'; });
        ws.on('disconnect', () => { wsStatus.value = '🔴 离线'; });
      } catch (e) { wsStatus.value = '⚠️ WebSocket不可用'; }
    });

    onUnmounted(() => {
      if (pollTimer) clearInterval(pollTimer);
      if (wsUnsub) wsUnsub();
    });

    return {
      summary, positions, orders, order, orderFilter, errorMsg, loading, submitting, wsStatus, modal, pnlClass,
      formatMoney, formatPct, colorClass, timeAgo, statusBadge,
      submitOrder, confirmCancel, confirmClose, loadOrders, loadAll
    };
  }
}).mount('#app');
