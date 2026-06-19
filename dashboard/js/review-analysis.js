const { createApp, ref, onMounted, computed } = Vue;

        createApp({
            setup() {
                const review = ref(null);
                const reviewDate = ref(new Date().toISOString().slice(0, 10));
                const today = ref(new Date().toISOString().slice(0, 10));
                const loading = ref(false);
                const error = ref('');

                const formattedContent = computed(() => {
                    if (!review.value || !review.value.content) return '';
                    let html = review.value.content;
                    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
                    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                    html = html.replace(/^(\d+)\. (.+)$/gm, '<div class="review-item"><span class="num">$1.</span>$2</div>');
                    html = html.replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>');
                    return html;
                });

                const formattedWarnings = computed(() => {
                    if (!review.value || !review.value.risk_warnings) return '';
                    let html = review.value.risk_warnings;
                    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
                    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                    html = html.replace(/^(\d+)\. (.+)$/gm, '<div class="review-item"><span class="num">$1.</span>$2</div>');
                    html = html.replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>');
                    return html;
                });

                const loadReview = async () => {
                    loading.value = true;
                    try {
                        const data = await API.strategy(`/v1/ai/review?date=${reviewDate.value}`);
                        if (data.success) {
                            review.value = data.data;
                            setTimeout(() => renderStrategyChart(data.data), 200);
                        }
                    } catch (e) {
                        // API 不可用，显示提示
                        review.value = null;
                        setTimeout(() => renderStrategyChart(null), 200);
                    } finally {
                        loading.value = false;
                    }
                };

                const renderStrategyChart = (reviewData) => {
                    const dom = document.getElementById('strategy-chart');
                    if (!dom) return;
                    const chart = echarts.init(dom);

                    // 尝试从复盘数据中提取策略表现图表数据
                    const perfData = reviewData && reviewData.strategy_performance ? reviewData.strategy_performance : null;

                    if (perfData && perfData.months && perfData.series) {
                        chart.setOption({
                            tooltip: { trigger: 'axis' },
                            legend: { data: perfData.series.map(s => s.name), bottom: 0 },
                            xAxis: { type: 'category', data: perfData.months },
                            yAxis: { type: 'value', axisLabel: { formatter: v => (v * 100).toFixed(0) + '%' } },
                            series: perfData.series.map(s => ({
                                name: s.name, type: 'line', data: s.data, smooth: true
                            })),
                            grid: { left: 60, right: 20, top: 20, bottom: 40 }
                        });
                    } else {
                        // 无数据时显示空图表
                        chart.setOption({
                            title: { text: '策略数据待API返回', left: 'center', top: 'middle', textStyle: { color: '#999', fontSize: 14 } },
                            xAxis: { show: false }, yAxis: { show: false },
                            series: []
                        });
                    }
                };

                onMounted(() => { loadReview(); });

                return { review, reviewDate, today, loading, error, formattedContent, formattedWarnings, loadReview };
            }
        }).mount('#app');
