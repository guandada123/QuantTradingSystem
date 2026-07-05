# ADR-006: Dashboard 前端构建流水线与 CI 质量门

**状态**: 已采纳  
**日期**: 2026-06-20

## 背景

Dashboard 前端的 dist/ 目录曾被源码覆盖（开发调试时直接用 `cp` 覆盖了 minified 产物），导致：
1. 生产部署加载膨胀的未压缩 JS/CSS
2. 构建产物与源码状态不一致
3. 无 CI 门禁，回归无法被及时发现

## 决策

1. 创建 `dashboard/build.sh` 作为唯一官方构建入口
   - csso 压缩 CSS
   - terser 压缩 + mangle JS
   - 复制静态资源（HTML/SVG/manifest/sw.js）
   - 生成 build.json 记录版本与构建时间
2. 创建 `.github/workflows/dashboard-build.yml` 作为 CI 质量门
   - 当 dashboard/ 下任何文件变更时触发
   - 执行 build.sh 构建
   - 验证产物文件完整性
3. dist/ 保持 git tracked（Dockerfile 在其中）

## 后果

### 正面
- ✅ dist/ 始终可复现
- ✅ CI 自动检测构建回归
- ✅ 构建流程标准化

### 负面
- ❌ 新增一步 CI job（增加构建时间 ~10s）
- ❌ dist/ 的 git 记录膨胀（二进制压缩产物）
