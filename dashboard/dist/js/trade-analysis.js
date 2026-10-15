const { createApp, ref, onMounted, computed } = Vue;

        createApp({
            setup() {
                const stats = ref({
                    total_trades: 0, win_rate: 0, profit_loss_ratio: 0,
                    avg_profit: 0, avg_loss: 0, max_drawdown: 0, sharpe_ratio: 0
                });
                const trades = ref([]);
                const filteredTrades = ref([]);
                const filterDir = ref('all');
                const loading = ref(true);
                const error = ref('');

                const goBack = () => { window.location.href = '/'; };

                const filterTrades = () => {
                    if (filterDir.value === 'all') {
                        filteredTrades.value = trades.value.slice(0, 50);
                    } else {
                        filteredTrades.value = trades.value.filter(t => t.direction === filterDir.value).slice(0, 50);
                    }
                };

                const fetchStats = async () => {
                    try {
                        const data = await API.strategy('/v1/trades/stats');
                        if (data.success && data.data) stats.value = data.data;
                    } catch (e) {
                        // API 不可用，保持默认空值，不置为 null（防止模板访问属性报错）
                    }
                };

                const fetchTrades = async () => {
                    try {
                        const data = await API.strategy('/v1/trades?limit=100');
                        if (data.success) {
                            trades.value = data.data;
                            filterTrades();
                        }
                    } catch (e) {
                        // API 不可用，显示空状态
                        trades.value = [];
                        filteredTrades.value = [];
                    }
                };

                const renderPnlDist = () => {
                    const chart = echarts.init(document.getElementById('pnl-dist-chart'));
                    const pnlList = trades.value.filter(t => t.profit_loss !== null).map(t => t.profit_loss);
                    if (pnlList.length === 0) {
                        chart.setOption({ title: { text: '暂无数据', left: 'center', top: 'middle', textStyle: { color: '#909399' } } });
                        return;
                    }
                    const bins = Array(20).fill(0);
                    const min = Math.min(...pnlList);
                    const max = Math.max(...pnlList);
                    const step = (max - min) / 20;
                    pnlList.forEach(v => {
                        const idx = Math.min(Math.floor((v - min) / step), 19);
                        bins[idx]++;
                    });
                    chart.setOption({
                        tooltip: { trigger: 'axis' },
                        xAxis: { type: 'category', data: bins.map((_, i) => (min + i * step).toFixed(0)) },
                        yAxis: { type: 'value' },
                        series: [{ type: 'bar', data: bins, itemStyle: { color: '#667eea' } }],
                        grid: { left: 50, right: 20, top: 20, bottom: 30 }
                    });
                };

                const renderMonthly = () => {
                    const chart = echarts.init(document.getElementById('monthly-chart'));
                    const months = {};
                    trades.value.forEach(t => {
                        if (t.profit_loss === null) return;
                        const m = t.trade_time.slice(0, 7);
                        months[m] = (months[m] || 0) + t.profit_loss;
                    });
                    const sortedMonths = Object.keys(months).sort();
                    chart.setOption({
                        tooltip: { trigger: 'axis' },
                        xAxis: { type: 'category', data: sortedMonths },
                        yAxis: { type: 'value', axisLabel: { formatter: v => '¥' + v.toFixed(0) } },
                        series: [{
                            type: 'bar',
                            data: sortedMonths.map(m => months[m]),
                            itemStyle: { color: months => months.value >= 0 ? '#d4302f' : '#1ca01c' }
                        }],
                        grid: { left: 60, right: 20, top: 20, bottom: 30 }
                    });
                };

                const renderCumulative = () => {
                    const chart = echarts.init(document.getElementById('cumulative-chart'));
                    const sellTrades = trades.value.filter(t => t.profit_loss !== null)
                        .sort((a, b) => (a.trade_time || '').localeCompare(b.trade_time || ''));
                    if (sellTrades.length === 0) {
                        chart.setOption({ title: { text: '暂无数据', left: 'center', top: 'middle', textStyle: { color: '#909399' } } });
                        return;
                    }
                    let cum = 0;
                    const dates = [], values = [];
                    sellTrades.forEach(t => {
                        cum += t.profit_loss;
                        dates.push(t.trade_time.slice(0, 10));
                        values.push(cum);
                    });
                    chart.setOption({
                        tooltip: { trigger: 'axis', formatter: params => {
                            const p = params[0];
                            return p.name + '<br/>累计收益: <strong>' + (p.value >= 0 ? '+' : '') + '¥' + p.value.toFixed(2) + '</strong>';
                        }},
                        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 11 } },
                        yAxis: { type: 'value', axisLabel: { formatter: v => '¥' + v.toFixed(0) } },
                        series: [{
                            type: 'line', data: values, smooth: true,
                            lineStyle: { width: 2, color: '#667eea' },
                            areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                                colorStops: [{ offset: 0, color: 'rgba(102,126,234,0.3)' }, { offset: 1, color: 'rgba(102,126,234,0.02)' }] }},
                            markLine: { data: [{ yAxis: 0 }], lineStyle: { color: '#ccc', type: 'dashed' } }
                        }],
                        grid: { left: 60, right: 20, top: 20, bottom: 50 }
                    });
                };

                onMounted(async () => {
                    await Promise.all([fetchStats(), fetchTrades()]);
                    loading.value = false;
                    setTimeout(() => {
                        renderPnlDist();
                        renderMonthly();
                        renderCumulative();
                    }, 100);
                });

                // safeFixed: 安全调用 toFixed()，防御 null/undefined
                const safeFixed = (val, digits = 2) => {
                    if (val == null || isNaN(val)) return '--';
                    return Number(val).toFixed(digits);
                };

                return { stats, trades, filteredTrades, filterDir, loading, error, goBack, filterTrades, safeFixed };
            }
        }).mount('#app');
