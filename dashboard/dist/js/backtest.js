const { createApp, ref, reactive, computed, watch, onMounted, nextTick } = Vue;

const API_BASE = CONFIG.API.strategy + '/v1/backtest';

// ===== 真实数据模式：前端不再生成本地回测/前向验证数据 =====
createApp({
  setup() {
    // 状态
    const loading = ref(false);
    const hasResult = ref(false);
    const configCollapsed = ref(false);
    const advancedOpen = ref(false);
    const currentPage = ref(1);
    const pageSize = 20;

    // 历史回测
    const history = ref([]);
    const historyOpen = ref(false);
    const historyLoading = ref(false);
    const historyError = ref('');
    const selectedHistoryId = ref('');

    // 配置
    const now = new Date();
    const oneYearAgo = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
    const config = reactive({
      ts_code: '600519.SH',
      strategies: ['ma-cross'],
      start_date: oneYearAgo.toISOString().split('T')[0],
      end_date: now.toISOString().split('T')[0],
      initial_cash: 100000,
      slippage: 0.1,
      commission: 2.5,
      benchmark: '000300.SH'
    });

    const quickStocks = [
      { name: '贵州茅台', code: '600519.SH' },
      { name: '五粮液', code: '000858.SZ' },
      { name: '招商银行', code: '600036.SH' },
      { name: '中国平安', code: '601318.SH' },
      { name: '美的集团', code: '000333.SZ' }
    ];

    const allStrategies = [
      { value: 'ma-cross', label: '双均线交叉' },
      { value: 'breakout', label: '突破策略' },
      { value: 'rsi', label: 'RSI策略' },
      { value: 'macd', label: 'MACD策略' },
      { value: 'kdj', label: 'KDJ策略' }
    ];

    function toggleStrategy(val) {
      const idx = config.strategies.indexOf(val);
      if (idx >= 0) { config.strategies.splice(idx, 1); }
      else { config.strategies.push(val); }
    }
    function selectAllStrategies() {
      config.strategies = allStrategies.map(s => s.value);
    }

    // 绩效指标
    const metrics = reactive({
      total_return: 0, annual_return: 0, sharpe: 0, max_drawdown: 0,
      win_rate: 0, profit_loss_ratio: 0, trade_count: 0, alpha: 0, beta: 0
    });

    // 数据
    const equityCurve = ref([]);
    const benchmarkCurve = ref([]);
    const drawdownCurve = ref([]);
    const monthlyReturns = ref([]);
    const strategyComparison = ref([]);
    const trades = ref([]);
    const walkForwardResults = ref([]);
    const overfitIndex = ref(0);
    const avgOosSharpe = ref(0);
    const stabilityScore = ref(0);

    // 图表引用
    const equityChartRef = ref(null);
    const drawdownChartRef = ref(null);
    const heatmapChartRef = ref(null);
    const walkForwardChartRef = ref(null);
    let equityChart = null, drawdownChart = null, heatmapChart = null, walkForwardChart = null;

    // 分页
    const totalPages = computed(() => Math.ceil(trades.value.length / pageSize));
    const paginatedTrades = computed(() => {
      const start = (currentPage.value - 1) * pageSize;
      return trades.value.slice(start, start + pageSize);
    });

    // 格式化
    function formatPct(v) {
      if (v == null || isNaN(v)) return '--';
      return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
    }
    function formatMoney(v) {
      if (v == null || isNaN(v)) return '--';
      return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function formatTime(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      const pad = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    // 获取历史回测列表
    async function fetchHistory() {
      historyLoading.value = true;
      historyError.value = '';
      try {
        const resp = await fetch(`${API_BASE}/`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || '获取失败');
        history.value = (data.data && data.data.backtests) || [];
      } catch (e) {
        historyError.value = e.message;
        history.value = [];
      } finally {
        historyLoading.value = false;
      }
    }

    // 加载某条历史回测的完整结果
    async function loadHistoryItem(backtestId) {
      if (loading.value) return;
      loading.value = true;
      hasResult.value = false;
      selectedHistoryId.value = backtestId;
      strategyComparison.value = [];
      walkForwardResults.value = [];

      try {
        const resp = await fetch(`${API_BASE}/${backtestId}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (data.success === false) throw new Error(data.error || '加载失败');

        // data.data 与 POST /run 返回格式兼容
        const detail = data.data || data;
        // 把详情展开成 applyResult 能用的格式
        applyResult({ data: detail });
        hasResult.value = true;
        Toast.success('已加载历史回测结果');
        await nextTick();
        renderCharts();
      } catch (e) {
        Toast.error(`加载历史回测失败: ${e.message}`);
        selectedHistoryId.value = '';
      } finally {
        loading.value = false;
      }
    }

    // 不保留任何前端假数据生成逻辑；API 不可用时直接显示错误/空状态。

    // 运行回测
    async function runBacktest() {
      if (!config.ts_code) { Toast.error('请输入股票代码'); return; }
      if (config.strategies.length === 0) { Toast.error('请选择至少一个策略'); return; }

      loading.value = true;
      hasResult.value = false;
      strategyComparison.value = [];
      walkForwardResults.value = [];

      try {
        // 调用真实后端 API（V2引擎，腾讯财经 → 东方财富 → DataService 多源真实数据）
        const resp = await fetch(`${API_BASE}/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ts_code: config.ts_code,
            strategy: config.strategies[0],
            strategies: config.strategies,          // 多策略支持
            start_date: config.start_date,
            end_date: config.end_date,
            initial_cash: config.initial_cash,
            benchmark: config.benchmark,
            params: { slippage: config.slippage / 100, commission_rate: config.commission / 10000 }
          })
        });
        if (!resp.ok) throw new Error('API error');
        const data = await resp.json();
        if (data.success === false) throw new Error(data.error || '回测失败');
        const result = data.data || data;
        if (!result.equity_curve || result.equity_curve.length === 0) {
          Toast.error('后端未返回真实回测数据，请检查数据源或日期范围');
          return;
        }
        applyResult(data);
      } catch (e) {
        Toast.error(`真实回测API不可用：${e.message || '请先启动后端服务'}`);
        return;
      } finally {
        loading.value = false;
      }

      // 多策略对比、前向验证均只使用后端真实结果，不再本地造数
      if (config.strategies.length > 1) {
        await runMultiStrategy();
      }
      await runWalkForward();

      hasResult.value = true;
      await nextTick();
      renderCharts();

      // 刷新历史列表
      fetchHistory();
    }

    async function runComboBacktest() {
      if (config.strategies.length < 2) { Toast.error('组合回测至少需要两个策略'); return; }
      await runBacktest();
    }

    async function runMultiStrategy() {
      const comparisons = [];
      for (const st of config.strategies) {
        try {
          const resp = await fetch(`${API_BASE}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ts_code: config.ts_code, strategy: st,
              start_date: config.start_date, end_date: config.end_date,
              initial_cash: config.initial_cash,
              benchmark: config.benchmark,
              params: { slippage: config.slippage / 100, commission_rate: config.commission / 10000 }
            })
          });
          if (!resp.ok) throw new Error('API error');
          const data = await resp.json();
          const r = data.data || data;
          comparisons.push({
            name: getStrategyLabel(st),
            total_return: r.metrics?.total_return || 0,
            annual_return: r.metrics?.annual_return || 0,
            sharpe: r.metrics?.sharpe || r.metrics?.sharpe_ratio || 0,
            max_drawdown: r.metrics?.max_drawdown || 0,
            win_rate: r.metrics?.win_rate || 0,
            trade_count: r.metrics?.trade_count || 0
          });
        } catch (e) {
          Toast.error(`${getStrategyLabel(st)} 回测失败，已跳过`);
        }
      }
      comparisons.sort((a, b) => b.sharpe - a.sharpe);
      strategyComparison.value = comparisons;

    }

    async function runWalkForward() {
      try {
        const resp = await fetch(`${API_BASE}/walk-forward`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ts_code: config.ts_code,
            strategy: config.strategies[0],
            start_date: config.start_date,
            end_date: config.end_date,
            initial_cash: config.initial_cash,
            benchmark: config.benchmark,
            params: { slippage: config.slippage / 100, commission_rate: config.commission / 10000 }
          })
        });
        if (!resp.ok) throw new Error('API error');
        const data = await resp.json();
        if (data.success === false) throw new Error(data.error || '前向验证失败');
        const wf = (data.data && data.data.windows) || data.windows || [];
        walkForwardResults.value = wf.map((w, idx) => ({
          window: w.window || `W${idx + 1}`,
          train_sharpe: Number(w.train_sharpe || 0),
          test_sharpe: Number(w.test_sharpe || 0),
          train_return: Number(w.train_return || 0),
          test_return: Number(w.test_return || 0)
        }));

        const trainSharpes = walkForwardResults.value.map(w => w.train_sharpe);
        const testSharpes = walkForwardResults.value.map(w => w.test_sharpe);
        avgOosSharpe.value = testSharpes.length ? testSharpes.reduce((a, b) => a + b, 0) / testSharpes.length : 0;
        const avgTrain = trainSharpes.length ? trainSharpes.reduce((a, b) => a + b, 0) / trainSharpes.length : 0;
        overfitIndex.value = avgTrain > 0 ? 1 - (avgOosSharpe.value / avgTrain) : 0;
        stabilityScore.value = testSharpes.length ? testSharpes.filter(s => s > 0).length / testSharpes.length : 0;
      } catch (e) {
        walkForwardResults.value = [];
        avgOosSharpe.value = 0;
        overfitIndex.value = 0;
        stabilityScore.value = 0;
      }
    }

    function getStrategyLabel(val) {
      const found = allStrategies.find(s => s.value === val);
      return found ? found.label : val;
    }

    function stockLabel(code) {
      const names = { '600519.SH': '贵州茅台', '000858.SZ': '五粮液', '600036.SH': '招商银行', '601318.SH': '中国平安', '000333.SZ': '美的集团', '000001.SZ': '平安银行', '300750.SZ': '宁德时代', '002230.SZ': '科大讯飞', '000300.SH': '沪深300' };
      return (names[code] || code) + ' (' + code + ')';
    }

    function applyResult(data) {
      // 解包 API 响应结构 {success, data: {metrics, equity_curve, ...}} 或兼容旧格式
      const result = (data && data.data) || data || {};
      const m = result.metrics || result;
      Object.assign(metrics, {
        total_return: m.total_return || 0, annual_return: m.annual_return || 0,
        sharpe: m.sharpe || m.sharpe_ratio || 0, max_drawdown: m.max_drawdown || 0,
        win_rate: m.win_rate || 0, profit_loss_ratio: m.profit_loss_ratio || 0,
        trade_count: m.trade_count || 0, alpha: m.alpha || 0, beta: m.beta || 0
      });
      equityCurve.value = result.equity_curve || [];
      benchmarkCurve.value = result.benchmark_curve || [];
      drawdownCurve.value = result.drawdown_curve || [];
      monthlyReturns.value = result.monthly_returns || [];
      trades.value = result.trades || [];
      currentPage.value = 1;
    }

    // 渲染图表
    function renderCharts() {
      renderEquityChart();
      renderDrawdownChart();
      renderHeatmapChart();
      if (walkForwardResults.value.length > 0) {
        nextTick(() => renderWalkForwardChart());
      }
    }

    function renderEquityChart() {
      if (!equityChartRef.value) return;
      if (equityChart) equityChart.dispose();
      equityChart = echarts.init(equityChartRef.value);
      const option = {
        tooltip: { trigger: 'axis', formatter: function(params) {
          let s = params[0].axisValue + '<br/>';
          params.forEach(p => { s += p.marker + p.seriesName + ': ' + p.value[1].toFixed(4) + '<br/>'; });
          return s;
        }},
        legend: { data: ['策略净值', '基准净值'], top: 10 },
        grid: { left: 60, right: 60, top: 50, bottom: 30 },
        xAxis: { type: 'category', data: equityCurve.value.map(d => d[0]), axisLabel: { fontSize: 11 } },
        yAxis: [
          { type: 'value', name: '净值', axisLabel: { formatter: v => v.toFixed(2) } }
        ],
        series: [
          {
            name: '策略净值', type: 'line', data: equityCurve.value.map(d => d),
            lineStyle: { color: '#ff4757', width: 2 }, itemStyle: { color: '#ff4757' },
            areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
              { offset: 0, color: 'rgba(255,71,87,0.15)' }, { offset: 1, color: 'rgba(255,71,87,0)' }
            ]}}, smooth: true, symbol: 'none'
          },
          {
            name: '基准净值', type: 'line', data: benchmarkCurve.value.map(d => d),
            lineStyle: { color: '#409eff', width: 1.5 }, itemStyle: { color: '#409eff' },
            areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
              { offset: 0, color: 'rgba(64,158,255,0.08)' }, { offset: 1, color: 'rgba(64,158,255,0)' }
            ]}}, smooth: true, symbol: 'none'
          }
        ],
        dataZoom: [{ type: 'inside', start: 0, end: 100 }]
      };
      equityChart.setOption(option);
    }

    function renderDrawdownChart() {
      if (!drawdownChartRef.value) return;
      if (drawdownChart) drawdownChart.dispose();
      drawdownChart = echarts.init(drawdownChartRef.value);
      const option = {
        tooltip: { trigger: 'axis', formatter: p => p[0].axisValue + '<br/>回撤: ' + (p[0].value[1] * 100).toFixed(2) + '%' },
        grid: { left: 60, right: 30, top: 20, bottom: 30 },
        xAxis: { type: 'category', data: drawdownCurve.value.map(d => d[0]), axisLabel: { fontSize: 11 } },
        yAxis: { type: 'value', axisLabel: { formatter: v => (v * 100).toFixed(0) + '%' }, max: 0 },
        series: [{
          type: 'line', data: drawdownCurve.value.map(d => d),
          lineStyle: { color: '#ff4757', width: 1 }, itemStyle: { color: '#ff4757' },
          areaStyle: { color: 'rgba(255,71,87,0.3)' }, smooth: true, symbol: 'none'
        }],
        dataZoom: [{ type: 'inside', start: 0, end: 100 }]
      };
      drawdownChart.setOption(option);
    }

    function renderHeatmapChart() {
      if (!heatmapChartRef.value) return;
      if (heatmapChart) heatmapChart.dispose();
      heatmapChart = echarts.init(heatmapChartRef.value);
      const months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];
      const startYear = new Date(config.start_date).getFullYear();
      const endYear = new Date(config.end_date).getFullYear();
      const years = [];
      for (let y = startYear; y <= endYear; y++) years.push(String(y));

      const data = monthlyReturns.value.map(d => [d[0], d[1], d[2]]);
      const maxVal = Math.max(...data.map(d => Math.abs(d[2])), 0.05);

      const option = {
        tooltip: { formatter: p => {
          const y = years[p.value[1]] || '';
          const m = months[p.value[0]] || '';
          return y + ' ' + m + '<br/>收益: ' + (p.value[2] * 100).toFixed(2) + '%';
        }},
        grid: { left: 70, right: 30, top: 10, bottom: 50 },
        xAxis: { type: 'category', data: months, splitArea: { show: true, areaStyle: { color: ['rgba(250,250,250,0.02)','rgba(250,250,250,0.02)'] } }, axisLine: { show: false }, axisTick: { show: false } },
        yAxis: { type: 'category', data: years, splitArea: { show: true }, axisLine: { show: false }, axisTick: { show: false } },
        visualMap: {
          min: -maxVal, max: maxVal, calculable: true, orient: 'horizontal',
          left: 'center', bottom: 5, itemWidth: 200, itemHeight: 14,
          inRange: { color: ['#2ed573', '#f5f5f5', '#ff4757'] },
          formatter: v => (v * 100).toFixed(1) + '%'
        },
        series: [{
          type: 'heatmap', data: data, label: { show: true, formatter: p => (p.value[2] * 100).toFixed(1) + '%', fontSize: 10 },
          itemStyle: { borderColor: '#fff', borderWidth: 1 },
          emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.3)' } }
        }]
      };
      heatmapChart.setOption(option);
    }

    function renderWalkForwardChart() {
      if (!walkForwardChartRef.value) return;
      if (walkForwardChart) walkForwardChart.dispose();
      walkForwardChart = echarts.init(walkForwardChartRef.value);
      const windows = walkForwardResults.value.map(w => w.window);
      const option = {
        tooltip: { trigger: 'axis' },
        legend: { data: ['训练集夏普', '测试集夏普'], top: 5 },
        grid: { left: 50, right: 30, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: windows },
        yAxis: { type: 'value', name: '夏普比率' },
        series: [
          { name: '训练集夏普', type: 'bar', data: walkForwardResults.value.map(w => w.train_sharpe.toFixed(2)), itemStyle: { color: '#409eff' } },
          { name: '测试集夏普', type: 'bar', data: walkForwardResults.value.map(w => w.test_sharpe.toFixed(2)), itemStyle: { color: '#2ed573' } }
        ]
      };
      walkForwardChart.setOption(option);
    }

    // 导出 CSV
    function exportCSV() {
      if (trades.value.length === 0) { Toast.error('暂无数据可导出'); return; }
      const header = '日期,股票,方向,价格,数量,金额,盈亏,持仓天数\n';
      const rows = trades.value.map(t =>
        `${t.date},${t.stock},${t.direction},${t.price},${t.quantity},${t.amount},${t.pnl},${t.hold_days || ''}`
      ).join('\n');
      const csv = '\uFEFF' + header + rows;
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `backtest_trades_${config.ts_code}_${config.start_date}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      Toast.success('导出成功');
    }

    // 窗口 resize
    function handleResize() {
      equityChart && equityChart.resize();
      drawdownChart && drawdownChart.resize();
      heatmapChart && heatmapChart.resize();
      walkForwardChart && walkForwardChart.resize();
    }

    onMounted(() => {
      window.addEventListener('resize', handleResize);
      fetchHistory();
    });

    return {
      loading, hasResult, configCollapsed, advancedOpen, currentPage, pageSize,
      config, quickStocks, allStrategies, metrics,
      equityCurve, benchmarkCurve, drawdownCurve, monthlyReturns,
      strategyComparison, trades, walkForwardResults,
      overfitIndex, avgOosSharpe, stabilityScore,
      equityChartRef, drawdownChartRef, heatmapChartRef, walkForwardChartRef,
      totalPages, paginatedTrades,
      history, historyOpen, historyLoading, historyError, selectedHistoryId,
      toggleStrategy, selectAllStrategies, runBacktest, runComboBacktest,
      fetchHistory, loadHistoryItem, formatTime,
      formatPct, formatMoney, exportCSV, stockLabel
    };
  }
}).mount('#app');
