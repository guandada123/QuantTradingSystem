# ADR-005: 统一依赖管理与自动构建

**状态**: 已采纳  
**日期**: 2026-06-19

## 背景

QTS 在初期采用每服务独立 `requirements.txt` 的方式管理 Python 依赖，导致：
1. 重复声明（多个服务共用 fastapi/pydantic 等）
2. 版本漂移（不同服务使用不同版本的核心依赖）
3. 构建复杂（每服务需独立 `pip install -r`）
4. 锁文件缺失（无法保证可复现构建）

## 决策

1. 将所有依赖统一到根目录 `pyproject.toml` 的 `[project.optional-dependencies]` 中
2. 按服务划分 optional 组：`strategy` / `execution` / `ai-scheduler` / `shared` / `dev`
3. 子目录中的 `requirements.txt` 标记为"已废弃"
4. 安装方式统一为：`pip install -e ".[strategy,execution,ai-scheduler,shared,dev]"`
5. 使用 pip-tools 生成 `requirements.lock`（完整哈希锁定）
6. Dashboard 前端使用 `build.sh` 脚本（terser + csso）统一构建

## 后果

### 正面
- ✅ 单点维护：改依赖只需改一个文件
- ✅ 版本一致：所有服务使用相同版本的核心库
- ✅ 可复现：requirements.lock 完整哈希固定依赖树
- ✅ CI 简化：单条命令即可安装全部依赖
- ✅ 前端构建：dist 产物始终是 minified 版本

### 负面
- ❌ 安装膨胀：`pip install -e ".[strategy]"` 会安装所有依赖（含其他服务）
- ❌ 本地开发：仍需为每个服务单独构建 Docker 镜像
- ❌ 迁移成本：旧 CI 配置需更新 pip 安装命令
