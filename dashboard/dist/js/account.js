const { createApp, ref, onMounted } = Vue;

        createApp({
            setup() {
                const account = ref({ total_assets: 0, available_cash: 0, market_value: 0, total_profit_loss: 0, total_profit_loss_ratio: 0 });
                const positions = ref([]);
                const loading = ref(true);
                const error = ref('');
                const miniChart1 = ref(null);

                const formatMoney = (val) => {
                    if (val === undefined || val === null) return '¥0.00';
                    return '¥' + val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                };

                const goBack = () => { window.location.href = '/'; };

                const fetchAccount = async () => {
                    try {
                        const data = await API.strategy('/v1/account/summary');
                        if (data.success) {
                            account.value = data.data;
                        }
                    } catch (e) {
                        // API 不可用，保持空状态
                    }
                };

                const fetchPositions = async () => {
                    try {
                        const data = await API.strategy('/v1/account/positions');
                        if (data.success) {
                            positions.value = data.data;
                        }
                    } catch (e) {
                        // API 不可用，保持空状态
                    }
                };

                const renderPnlChart = (pnlData) => {
                    const el = document.getElementById('pnl-chart');
                    if (!el) return;
                    const chart = echarts.init(el);

                    let dates = [], values = [];
                    if (pnlData && pnlData.length > 0) {
                        // 使用真实的每日净值数据
                        dates = pnlData.map(d => d.date ? d.date.slice(5) : '');
                        values = pnlData.map(d => d.value || d.total_assets || 0);
                    } else {
                        // API 无数据时显示空图表
                        dates = ['暂无数据'];
                        values = [0];
                    }

                    chart.setOption({
                        tooltip: { trigger: 'axis' },
                        xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10 } },
                        yAxis: { type: 'value', axisLabel: { formatter: (v) => '¥' + (v/10000).toFixed(1) + '万' } },
                        series: [{
                            type: 'line',
                            data: values,
                            smooth: true,
                            lineStyle: { color: '#667eea', width: 2 },
                            areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1, [{offset:0,color:'rgba(102,126,234,0.3)'},{offset:1,color:'rgba(102,126,234,0.02)'}]) },
                            itemStyle: { color: '#667eea' }
                        }],
                        grid: { left: 60, right: 20, top: 20, bottom: 30 }
                    });
                };

                onMounted(async () => {
                    await Promise.all([fetchAccount(), fetchPositions()]);
                    loading.value = false;
                    // 尝试获取每日净值数据用于图表
                    try {
                        const pnlResp = await API.strategy('/v1/account/daily-values');
                        if (pnlResp.success && pnlResp.data) {
                            setTimeout(() => renderPnlChart(pnlResp.data), 100);
                        } else {
                            setTimeout(() => renderPnlChart(null), 100);
                        }
                    } catch (e) {
                        setTimeout(() => renderPnlChart(null), 100);
                    }
                });

                return { account, positions, loading, error, miniChart1, formatMoney, formatPct, goBack };
            }
        }).mount('#app');
