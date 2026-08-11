# Learnings (QuantTradingSystem)

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | best_practice | knowledge_gap

---

## [correction] gitleaks-action@v2 强制 GITLEAKS_LICENSE 致 quality-gate 红灯（★升级候选）

- **日期**: 2026-08-12
- **现象**: QTS `CI - Quality Gate` 在 08-11 21:40 推送后突然红灯，根因非代码问题，而是 `gitleaks/gitleaks-action@v2` 自 2026-08 起 breaking change 强制要求 `GITLEAKS_LICENSE` 密钥，缺失即 `🛑 missing gitleaks license` 报错。
- **影响面**: 所有引用 `engineering-audit-kit` quality-gate `@v1` 的仓库（QTS/Claw/StockInsight/MarvisBridge）同步红灯。
- **根因**: `@v2` 浮动 tag 被 repoint 到强制 license 的新版本；同仓库 `security-scan.yml` 用 `@v3` 且无 license 仍跑通，证伪"gitleaks 需付费"假设——实为 action 包装器的 license 限制，gitleaks 引擎本身（MIT）始终免费。
- **修复**: quality-gate.yml / eak-ci.yml 改为直接经 Docker 调用开源引擎 `zricethezav/gitleaks:latest detect --redact --source=/repo`，自动探测仓库根 `.gitleaks.toml`；并将 `v1` tag 同步至修复提交 ae57b18。
- **★升级候选**: 第三方 GitHub Action 浮动 tag（如 `@v2`）会因上游 breaking change 静默弄红 CI。经验：① 关键 CI 步骤优先用 commit SHA 或 Docker 直调引擎，避免 action 包装器 license/API 依赖；② 巡检 dedup 不能只按"CI 是否红"去重，需按具体 run/根因去重，否则会掩盖新红灯（本次即被误判为重复项跳过推送）。
