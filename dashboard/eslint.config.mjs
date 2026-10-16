// ============================================================
// QTS Dashboard — ESLint 扁平配置（2026-10-16 引入）
//
// 背景：本目录此前没有任何 package.json / lint 配置，前端改动仅靠人工检查与
//   构建脚本兜底（审计发现）。此配置提供**可运行的 lint 入口**。
//
// 设计取舍：规则集设为 **warn 级别、不阻塞**——
//   存量代码（约 6600 行手写 JS + 10 个 HTML）尚未按 lint 规范梳理，
//   直接设为 error 会让任何 lint 运行全红、失去意义。
//   后续应逐步收敛后再接入 CI 门禁（当前 CI 未调用本配置）。
// ============================================================

export default [
  {
    files: ['**/*.js'],
    ignores: ['vendor/**', 'dist/**', 'node_modules/**'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        // 浏览器
        window: 'readonly', document: 'readonly', navigator: 'readonly', location: 'readonly',
        localStorage: 'readonly', sessionStorage: 'readonly', fetch: 'readonly',
        setTimeout: 'readonly', clearTimeout: 'readonly', setInterval: 'readonly', clearInterval: 'readonly',
        requestAnimationFrame: 'readonly', cancelAnimationFrame: 'readonly', console: 'readonly',
        AbortSignal: 'readonly', MutationObserver: 'readonly', IntersectionObserver: 'readonly',
        CustomEvent: 'readonly', Event: 'readonly', HTMLElement: 'readonly', ResizeObserver: 'readonly',
        getComputedStyle: 'readonly', matchMedia: 'readonly', performance: 'readonly',
        // Service Worker / Web API（sw.js 使用）
        self: 'readonly', caches: 'readonly', Response: 'readonly', Request: 'readonly',
        URL: 'readonly', Blob: 'readonly', Headers: 'readonly', FormData: 'readonly',
        TextDecoder: 'readonly', TextEncoder: 'readonly', queueMicrotask: 'readonly',
        // 本项目的全局对象（由 app.js 暴露）
        Vue: 'readonly', echarts: 'readonly', QT: 'writable', APP_CONFIG: 'readonly',
        CONFIG: 'readonly', Toast: 'readonly', AriaLive: 'readonly', STRAT_CONFIG: 'readonly',
        API: 'readonly', getWSManager: 'readonly'
      }
    },
    rules: {
      // 全部 warn：先暴露问题、不阻断
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-undef': 'warn',
      'no-empty': 'warn',
      'no-cond-assign': 'warn',
      'no-constant-condition': 'warn',
      'no-dupe-keys': 'warn',
      'no-duplicate-case': 'warn',
      'no-fallthrough': 'warn',
      'no-redeclare': 'warn',
      'no-self-assign': 'warn',
      'no-unreachable': 'warn',
      'no-useless-escape': 'warn',
      'valid-typeof': 'warn',
      // 明确禁止（真问题、非风格）：调试残留
      'no-debugger': 'warn',
      'no-var': 'off'
    }
  }
];
