const { createApp, ref, onMounted, computed } = Vue;

        createApp({
            setup() {
                const stocks = ref([]);
                const filter = ref({ strategy: 'all', minScore: '0', keyword: '' });
                const scanning = ref(false);
                const loading = ref(true);
                const error = ref('');
                const lastUpdate = ref('--');

                const signalLabel = (s) => ({ BUY: '买入', SELL: '卖出', HOLD: '持有' }[s] || s);
                const goBack = () => { window.location.href = '/'; };

                const filteredStocks = computed(() => {
                    let result = stocks.value;
                    if (filter.value.strategy !== 'all') {
                        result = result.filter(s => s.strategy_name === filter.value.strategy);
                    }
                    if (parseInt(filter.value.minScore) > 0) {
                        result = result.filter(s => s.score >= parseInt(filter.value.minScore));
                    }
                    if (filter.value.keyword) {
                        const kw = filter.value.keyword.toUpperCase();
                        result = result.filter(s => s.ts_code.includes(kw) || (s.name && s.name.includes(kw)));
                    }
                    return result.sort((a, b) => b.score - a.score);
                });

                const doScan = async () => {
                    scanning.value = true;
                    try {
                        const data = await API.strategy('/v1/ai/scan', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ strategy: filter.value.strategy, top_n: 20 })
                        });
                        if (data.success) {
                            stocks.value = data.data || data.results || [];
                            lastUpdate.value = new Date().toLocaleTimeString('zh-CN');
                        }
                    } catch (e) {
                        // API 不可用，保持空列表
                        stocks.value = [];
                        lastUpdate.value = '';
                    } finally {
                        scanning.value = false;
                    }
                };

                const analyzeStock = (code) => {
                    Toast.info('AI分析跳转：正在分析 ' + code + '...\n\n（完整AI多智能体分析功能开发中）');
                };

                onMounted(async () => {
                    // 自动触发一次扫描获取真实数据
                    await doScan();
                    loading.value = false;
                });

                return { stocks, filter, filteredStocks, scanning, loading, error, lastUpdate, signalLabel, goBack, doScan, analyzeStock };
            }
        }).mount('#app');
