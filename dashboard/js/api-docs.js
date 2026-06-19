const SERVICES = [
        { name: 'strategy-service', port: 8000, label: '策略研究服务', version: '2.0.0' },
        { name: 'execution-service', port: 8001, label: '交易执行服务', version: '1.1.0' },
        { name: 'ai-scheduler', port: 8002, label: 'AI 智能调度器', version: '1.0.0' },
    ];

    // 使用 hostname 而非 apiBase 以避免端口重复
    const HOST = typeof APP_CONFIG !== 'undefined'
      ? window.location.protocol + '//' + window.location.hostname
      : window.location.origin;

    let currentIndex = 0;
    let ui = null;

    const STATIC_SPECS = [
        'docs/api/strategy-service.json',
        'docs/api/execution-service.json',
        'docs/api/ai-scheduler.json',
    ];

    async function buildSpecs() {
        const specs = [];
        const statusDot = document.getElementById('statusDot');
        let onlineCount = 0;

        for (let i = 0; i < SERVICES.length; i++) {
            const svc = SERVICES[i];
            let spec = null;

            // 策略1: 从运行的微服务动态拉取
            try {
                const url = `${HOST}:${svc.port}/openapi.json`;
                const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
                if (resp.ok) {
                    spec = await resp.json();
                    onlineCount++;
                }
            } catch (e) { /* fallback */ }

            // 策略2: 离线回退到静态 spec 文件
            if (!spec) {
                try {
                    const resp = await fetch(`../${STATIC_SPECS[i]}`);
                    if (resp.ok) {
                        spec = await resp.json();
                    }
                } catch (e) { /* 双回退 */ }
            }

            if (spec) {
                spec.info.title = `[${svc.label}] ${spec.info.title}`;
                spec.info.description = `${spec.info.description || ''}\n\n**端口**: ${svc.port} | **版本**: ${spec.info.version}`;
                specs.push(spec);
            } else {
                // 完全离线时创建占位
                specs.push({
                    openapi: '3.0.0',
                    info: {
                        title: `[${svc.label}] ${svc.name}`,
                        description: `⚠️ 服务不可用（端口 ${svc.port}）\n\n请确保服务已启动：\`docker-compose up -d ${svc.name}\``,
                        version: svc.version
                    },
                    paths: {}
                });
            }
        }

        // 更新状态指示器
        if (onlineCount === 3) {
            statusDot.className = 'status-dot online';
            statusDot.title = '所有服务在线';
        } else if (onlineCount > 0) {
            statusDot.className = 'status-dot loading';
            statusDot.title = `${onlineCount}/3 服务在线`;
        } else {
            statusDot.className = 'status-dot offline';
            statusDot.title = '所有服务离线';
        }

        return specs;
    }

    function renderSwagger(specs, index) {
        const container = document.getElementById('swagger-ui');
        // 安全清空容器（使用 textContent 而非 innerHTML）
        while (container.firstChild) {
            container.removeChild(container.firstChild);
        }

        let urls;
        if (index === 'all') {
            urls = specs.map((s, i) => ({
                url: s.info.title,
                name: SERVICES[i].label
            }));
        } else {
            urls = [{ url: specs[index].info.title, name: SERVICES[index].label }];
        }

        // 使用多个 spec 的 Swagger UI 配置
        const config = index === 'all'
            ? {
                urls: specs.map((s, i) => ({
                    url: `${HOST}:${SERVICES[i].port}/openapi.json`,
                    name: SERVICES[i].label
                })),
                'urls.primaryName': SERVICES[0].label,
            }
            : { url: `${HOST}:${SERVICES[index].port}/openapi.json` };

        ui = SwaggerUIBundle({
            dom_id: '#swagger-ui',
            ...config,
            deepLinking: true,
            docExpansion: 'list',
            defaultModelsExpandDepth: 2,
            defaultModelExpandDepth: 2,
            filter: true,
            tryItOutEnabled: true,
            displayRequestDuration: true,
            syntaxHighlight: { activate: true, theme: 'monokai' },
            layout: 'BaseLayout',
            presets: [SwaggerUIBundle.presets.apis],
            plugins: [SwaggerUIBundle.plugins.DownloadUrl],
        });
    }

    async function switchSpec(index) {
        currentIndex = index;
        // 更新 tab 样式
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active', 'all-active'));
        const tabId = index === 'all' ? 'tabAll' : `tab${index}`;
        const tab = document.getElementById(tabId);
        tab.classList.add(index === 'all' ? 'all-active' : 'active');

        const specs = await buildSpecs();
        renderSwagger(specs, index);
    }

    // Event delegation for tab clicks (no inline onclick needed)
    document.querySelector('.service-tabs').addEventListener('click', function(e) {
      const tab = e.target.closest('.tab');
      if (!tab) return;
      const index = tab.id === 'tabAll' ? 'all' : parseInt(tab.id.replace('tab', ''), 10);
      switchSpec(index);
    });

    // 初始化
    async function init() {
      const specs = await buildSpecs();
      renderSwagger(specs, 0);
      document.getElementById('tab0').classList.add('active');
    }

    init();
