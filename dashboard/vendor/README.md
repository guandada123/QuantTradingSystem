# vendor/ — 本地化前端依赖清单

> 2026-10-16 引入。**背景**：仪表盘原先从 `cdn.jsdelivr.net` 加载 Vue/ECharts。
> 在国内网络（尤其手机经 Tailscale 访问）下该 CDN 不可达 → 页面无法渲染。
> 现已全部本地化，本文件记录**确切版本与来源**，以保证可复现、可审计。

| 文件 | 库 | 版本 | 来源 URL | 备注 |
|------|----|------|---------|------|
| `vue.global.prod.js` | Vue 3（**含编译器**的完整构建） | 3.3.4 | `https://cdn.jsdelivr.net/npm/vue@3.3.4/dist/vue.global.prod.js` | 使用 `template:` 字符串，**依赖运行时模板编译** → 页面 CSP 必须放行 `'unsafe-eval'`（见各 HTML 的 CSP meta） |
| `echarts.min.js` | Apache ECharts | 文件内版本串 `5.4.4`（来源标签 5.4.3） | `https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js` | 与来源标签存在一档差异，已知并记录 |
| `three.module.min.js` | three.js（ESM，供粒子背景动态 import） | 0.160.0 | `https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.min.js` | 由 `app.js` 在 `requestIdleCallback` 中动态导入；是 `.min` 版（原代码引的是非压缩版） |

## 维护约定

1. **升级步骤**：替换文件 → 更新本表版本/来源 → 同步 `sw.js` 的 `CACHE_NAME` 版本号（否则用户拿到旧缓存）
2. **禁止**把 CDN 地址重新写回 `*.html` / `*.js` / `sw.js`（含预缓存清单）
3. `api-docs.html` 的 swagger-ui 仍走 CDN —— 该页仅开发期查接口用，且其体积（1.5MB）会触发
   pre-commit 的 `check-added-large-files --maxkb=1024` 拦截；如需本地化，请先把该阈值或方案定清楚
4. 新增第三方库时优先选 `.min` 版并确认体积 < 1024KB（否则提交会被钩子拦下）
