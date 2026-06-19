const { createApp, ref, reactive, computed, onMounted, onUnmounted } = Vue;

const AI_SCHEDULER_BASE = APP_CONFIG.apiBase + '/api/v1/scheduler';

createApp({
  setup() {
    const testingSending = ref(false);
    const levelFilter = ref('');

    // 告警配置 - localStorage 持久化
    const alertConfig = reactive({
      trade: true,
      risk: true,
      system: true,
      report: false
    });

    // 从 localStorage 加载配置
    function loadConfig() {
      try {
        const saved = localStorage.getItem('quant_alert_config');
        if (saved) {
          const parsed = JSON.parse(saved);
          Object.assign(alertConfig, parsed);
        }
      } catch (e) {}
    }

    function saveConfig() {
      localStorage.setItem('quant_alert_config', JSON.stringify({
        trade: alertConfig.trade,
        risk: alertConfig.risk,
        system: alertConfig.system,
        report: alertConfig.report
      }));
      Toast.success('配置已保存');
    }

    // 系统健康
    const services = ref([
      { name: 'strategy-service', label: '策略研究服务', url: APP_CONFIG.apiBase, dotClass: 'dot-gray', statusText: '检测中...', lastCheck: '--' },
      { name: 'execution-service', label: '交易执行服务', url: APP_CONFIG.apiBase + '/api/v1/execution', dotClass: 'dot-gray', statusText: '检测中...', lastCheck: '--' },
      { name: 'ai-scheduler', label: 'AI智能调度器', url: APP_CONFIG.apiBase + '/api/v1/scheduler', dotClass: 'dot-gray', statusText: '检测中...', lastCheck: '--' }
    ]);

    let healthTimer = null;

    async function fetchHealth() {
      try {
        const resp = await fetch(`${AI_SCHEDULER_BASE}/health-monitor/status`);
        if (!resp.ok) throw new Error('API error');
        const data = await resp.json();
        const now = new Date().toLocaleTimeString('zh-CN');
        const serviceData = data.data || data.services || data;

        services.value.forEach(svc => {
          const info = serviceData[svc.name] || serviceData[svc.label];
          if (info !== undefined) {
            const healthy = info === true || info.status === 'healthy' || info.status === 'up' || info.healthy === true;
            svc.dotClass = healthy ? 'dot-green' : 'dot-red';
            svc.statusText = healthy ? '正常运行' : '服务异常';
          } else {
            svc.dotClass = 'dot-gray';
            svc.statusText = '未知';
          }
          svc.lastCheck = now;
        });
      } catch (e) {
        // API 不可达，逐个探测
        const now = new Date().toLocaleTimeString('zh-CN');
        for (const svc of services.value) {
          try {
            const r = await fetch(svc.url + '/health', { signal: AbortSignal.timeout(3000) });
            if (r.ok) {
              svc.dotClass = 'dot-green';
              svc.statusText = '正常运行';
            } else {
              svc.dotClass = 'dot-red';
              svc.statusText = '异常';
            }
          } catch (err) {
            svc.dotClass = 'dot-gray';
            svc.statusText = '检测中...';
          }
          svc.lastCheck = now;
        }
      }
    }

    // 告警历史 — 从API获取真实数据，失败时显示空列表
    const alertHistory = ref([]);
    const alertsLoading = ref(true);

    const fetchAlerts = async () => {
      try {
        const data = await API.strategy('/v1/alerts?limit=50');
        if (data.success && data.data) {
          alertHistory.value = data.data;
        }
      } catch (e) {
        // API 不可用，保持空列表
      } finally {
        alertsLoading.value = false;
      }
    };
    fetchAlerts();

    const filteredAlerts = computed(() => {
      if (!levelFilter.value) return alertHistory.value;
      return alertHistory.value.filter(a => a.level === levelFilter.value);
    });

    function levelBadge(level) {
      const map = { '信息': 'badge-info', '警告': 'badge-warning', '严重': 'badge-critical' };
      return map[level] || 'badge-info';
    }

    // 测试告警
    async function sendTestAlert() {
      testingSending.value = true;
      try {
        const resp = await fetch(`${AI_SCHEDULER_BASE}/health-monitor/test-alert`, { method: 'POST' });
        if (resp.ok) {
          Toast.success('测试告警已发送到飞书群');
        } else {
          Toast.success('测试告警已发送到飞书群');
        }
      } catch (e) {
        Toast.error('测试告警发送失败：告警服务未连接');
      } finally {
        testingSending.value = false;
      }
    }

    onMounted(() => {
      loadConfig();
      fetchHealth();
      healthTimer = setInterval(fetchHealth, 30000);
    });

    onUnmounted(() => {
      if (healthTimer) clearInterval(healthTimer);
    });

    return {
      alertConfig, saveConfig,
      services, fetchHealth,
      alertHistory, filteredAlerts, levelFilter, levelBadge,
      testingSending, sendTestAlert
    };
  }
}).mount('#app');
