const { createApp, ref, reactive, onMounted, nextTick } = Vue;

// 策略类型 → 中文
const TYPE_LABELS = {
    builtin: '内置策略',
    trend: '趋势跟踪',
    mean_reversion: '均值回归',
    momentum: '动量策略',
    breakout: '突破策略',
};

createApp({
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
    const form = reactive({ name: '', type: 'trend', description: '', params_text: '{}' });
    const delConfirm = reactive({ show: false, id: null, name: '' });
    let chartInstance = null;

    function formatPct(v) { return window.formatPct ? window.formatPct(v, 2) : '--'; }
    function colorClass(v) { return window.colorClass ? window.colorClass(v) : ''; }

    function typeLabel(t) { return TYPE_LABELS[t] || t; }

    async function loadStrategies() {
      loading.value = true;
      try {
        let path = '/v1/strategies/?';
        if (typeFilter.value) path += 'type=' + typeFilter.value + '&';
        const d = await API.strategy(path);
        if (d.success) strategies.value = d.data || [];
      } catch (e) {
        Toast.warning('策略加载失败，使用缓存数据');
      } finally { loading.value = false; }
    }

    function toggleSelect(s) {
      const id = s.strategy_id || s.id;
      const idx = selected.value.indexOf(id);
      if (idx >= 0) selected.value.splice(idx, 1);
      else selected.value.push(id);
    }

    async function compareStrategies() {
      try {
        const ids = selected.value;
        const d = await API.strategy('/v1/strategies/compare', {
          method: 'POST', body: JSON.stringify({ strategy_ids: ids })
        });
        if (d.success) compareData.value = d.data || [];
      } catch (e) { Toast.error('对比失败：' + e.message); }
    }

    async function backtestSelected() {
      showChart.value = true;
      await nextTick();
      try {
        const id = selected.value[0];
        const d = await API.strategy('/v1/strategies/' + id + '/backtest?ts_code=000001.SZ', { method: 'POST' });
        if (d.success && d.data) {
          const r = d.data;
          chartMetrics.value = [
            { label: '总收益率', value: formatPct(r.total_return), color: colorClass(r.total_return) },
            { label: '夏普比率', value: (r.sharpe_ratio||0).toFixed(2), color: '' },
            { label: '最大回撤', value: formatPct(r.max_drawdown), color: r.max_drawdown < 0 ? 'bear' : '' },
            { label: '胜率', value: formatPct(r.win_rate), color: '' },
          ];
          renderChart(r);
        }
      } catch (e) { Toast.error('回测失败：' + e.message); }
    }

    function renderChart(data) {
      const el = document.getElementById('chart');
      if (!el) return;
      if (chartInstance) chartInstance.dispose();
      chartInstance = echarts.init(el);
      chartInstance.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['策略净值', '基准'] },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'category', data: data.dates || [] },
        yAxis: { type: 'value', name: '净值' },
        series: [
          { name: '策略净值', type: 'line', data: data.equity_curve || [], smooth: true, lineStyle: { color: '#667eea', width: 2 } },
          { name: '基准', type: 'line', data: data.benchmark_curve || [], smooth: true, lineStyle: { color: '#999', type: 'dashed', width: 1 } },
        ]
      });
    }

    function newStrategy() {
      editId.value = null;
      form.name = ''; form.type = 'trend'; form.description = ''; form.params_text = '{}';
      showForm.value = true;
    }

    function editStrategy(s) {
      editId.value = s.strategy_id || s.id;
      form.name = s.name || s.strategy_name || '';
      form.type = s.strategy_type || s.type || 'trend';
      form.description = s.description || '';
      form.params_text = s.params ? JSON.stringify(s.params, null, 2) : '{}';
      showForm.value = true;
    }

    async function saveStrategy() {
      try {
        let params = {};
        try { params = JSON.parse(form.params_text); } catch (e) { Toast.warning('参数JSON格式错误'); return; }
        const body = { name: form.name, strategy_type: form.type, description: form.description, params: params, status: 'active' };
        if (editId.value) {
          await API.strategy('/v1/strategies/' + editId.value, { method: 'PUT', body: JSON.stringify(body) });
          Toast.success('策略已更新替换');
        } else {
          await API.strategy('/v1/strategies/', { method: 'POST', body: JSON.stringify(body) });
          Toast.success('策略已创建');
        }
        showForm.value = false;
        await loadStrategies();
      } catch (e) { Toast.error('保存失败：' + e.message); }
    }

    function confirmDelete(s) {
      delConfirm.id = s.strategy_id || s.id;
      delConfirm.name = s.name || s.strategy_name || '未命名';
      delConfirm.show = true;
    }

    async function doDelete() {
      try {
        await API.strategy('/v1/strategies/' + delConfirm.id, { method: 'DELETE' });
        Toast.success('策略已删除');
        delConfirm.show = false;
        if (showForm.value && editId.value === delConfirm.id) showForm.value = false;
        await loadStrategies();
      } catch (e) { Toast.error('删除失败：' + e.message); }
    }

    onMounted(() => { loadStrategies(); });

    return {
      strategies, selected, typeFilter, loading, showChart, showForm, editId,
      compareData, chartMetrics, form, delConfirm,
      formatPct, colorClass, typeLabel,
      toggleSelect, compareStrategies, backtestSelected,
      newStrategy, editStrategy, saveStrategy, confirmDelete, doDelete, loadStrategies,
    };
  }
}).mount('#app');
