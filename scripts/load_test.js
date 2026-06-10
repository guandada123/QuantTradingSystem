// ============================================================
// QuantTradingSystem 性能压测脚本 (k6)
// 用法:
//   k6 run scripts/load_test.js
//   k6 run --vus 50 --duration 60s scripts/load_test.js
//   k6 run --vus 100 --duration 5m --stage 30s:50,2m:100,1m:0 scripts/load_test.js
// ============================================================

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend, Gauge } from 'k6/metrics';
import { htmlReport } from "https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js";

// 自定义指标
const errorRate = new Rate('error_rate');
const apiLatency = new Trend('api_latency', true);
const healthLatency = new Trend('health_latency', true);
const successCount = new Counter('success_count');
const failCount = new Counter('fail_count');

// 可配置参数
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const EXECUTION_URL = __ENV.EXECUTION_URL || 'http://localhost:8001';
const AI_URL = __ENV.AI_URL || 'http://localhost:8002';

export const options = {
    stages: [
        { duration: '30s', target: 10 },   // 预热: 10个并发用户
        { duration: '1m',  target: 30 },   // 爬升: 30个并发
        { duration: '2m',  target: 30 },   // 维持: 30个并发
        { duration: '30s', target: 0 },    // 冷却: 逐步退出
    ],
    thresholds: {
        'http_req_duration': ['p(95)<500', 'p(99)<1000'],  // 95%请求<500ms
        'error_rate': ['rate<0.05'],                          // 错误率<5%
        'http_req_failed': ['rate<0.01'],                     // 失败率<1%
    },
};

// ============================================================
// 测试场景
// ============================================================

export default function () {
    group('Health Checks', () => {
        healthCheck();
    });

    group('Stock Data API', () => {
        stockAPI();
    });

    group('Account & Risk API', () => {
        accountAPI();
    });

    group('Dashboard', () => {
        dashboardAccess();
    });

    sleep(2);
}

// ============================================================
// 1. 健康检查
// ============================================================

function healthCheck() {
    const services = [
        { url: `${BASE_URL}/health`, name: 'strategy' },
        { url: `${EXECUTION_URL}/health`, name: 'execution' },
        { url: `${AI_URL}/health`, name: 'ai-scheduler' },
    ];

    for (const svc of services) {
        const start = Date.now();
        const res = http.get(svc.url, { timeout: '5s' });
        const duration = Date.now() - start;
        healthLatency.add(duration);

        const ok = check(res, {
            [`${svc.name} health 200`]: (r) => r.status === 200,
            [`${svc.name} response time < 200ms`]: () => duration < 200,
        });

        if (ok) successCount.add(1); else failCount.add(1);
    }
}

// ============================================================
// 2. 股票数据API
// ============================================================

function stockAPI() {
    const stockList = ['600519.SH', '000858.SZ', '600036.SH', '601318.SH', '000333.SZ'];
    const stock = stockList[Math.floor(Math.random() * stockList.length)];

    // 实时行情
    {
        const start = Date.now();
        const res = http.get(`${BASE_URL}/api/v1/stocks/realtime/${stock}`, { timeout: '10s' });
        apiLatency.add(Date.now() - start);
        errorRate.add(res.status >= 400);
        check(res, { 'stock realtime ok': (r) => r.status === 200 });
    }

    // 股票池
    {
        const res = http.get(`${BASE_URL}/api/v1/stocks/pool`, { timeout: '10s' });
        check(res, { 'stock pool ok': (r) => r.status === 200 });
    }
}

// ============================================================
// 3. 账户与风控API
// ============================================================

function accountAPI() {
    // 账户概览
    {
        const res = http.get(`${BASE_URL}/api/v1/account/summary`, { timeout: '10s' });
        check(res, { 'account summary ok': (r) => r.status === 200 });
    }

    // 风控参数查询
    {
        const res = http.get(`${EXECUTION_URL}/api/v1/risk/settings`, { timeout: '10s' });
        check(res, { 'risk settings ok': (r) => r.status === 200 });
    }

    // 熔断器状态
    {
        const res = http.get(`${EXECUTION_URL}/api/v1/risk/circuit-breaker`, { timeout: '10s' });
        check(res, { 'circuit breaker ok': (r) => r.status === 200 });
    }
}

// ============================================================
// 4. Dashboard 访问
// ============================================================

function dashboardAccess() {
    const pages = ['/', '/orders.html', '/account.html', '/alerts.html', '/backtest.html'];
    const page = pages[Math.floor(Math.random() * pages.length)];

    const res = http.get(`http://localhost:3000${page}`, { timeout: '10s' });
    check(res, {
        'dashboard serves': (r) => r.status === 200,
        'dashboard has content': (r) => r.body.length > 500,
    });
}

// ============================================================
// 报告生成
// ============================================================

export function handleSummary(data) {
    const summary = {
        timestamp: new Date().toISOString(),
        total_requests: data.metrics.http_reqs?.values?.count || 0,
        total_failures: data.metrics.http_req_failed?.values?.passes || 0,
        error_rate: ((data.metrics.error_rate?.values?.rate || 0) * 100).toFixed(2) + '%',
        avg_response_time_ms: (data.metrics.http_req_duration?.values?.avg || 0).toFixed(1),
        p95_response_time_ms: (data.metrics.http_req_duration?.values['p(95)'] || 0).toFixed(1),
        p99_response_time_ms: (data.metrics.http_req_duration?.values['p(99)'] || 0).toFixed(1),
        health_checks: {
            avg_ms: (data.metrics.health_latency?.values?.avg || 0).toFixed(1),
            p95_ms: (data.metrics.health_latency?.values['p(95)'] || 0).toFixed(1),
        },
        api_latency: {
            avg_ms: (data.metrics.api_latency?.values?.avg || 0).toFixed(1),
            p95_ms: (data.metrics.api_latency?.values['p(95)'] || 0).toFixed(1),
        },
    };

    return {
        'stdout': JSON.stringify(summary, null, 2),
        'load_test_report.json': JSON.stringify(summary, null, 2),
        'load_test_report.html': htmlReport(data),
    };
}
