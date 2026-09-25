"""
股票名称解析器 — 从 astock_code_name.json 加载 5528 条 A 股名称映射
供 strategy-service / execution-service / ai-scheduler 共用

用法:
    from shared.stock_name import resolve_name, resolve_name_batch

    name = resolve_name("603823.SH")   # → "百合花"
    names = resolve_name_batch(["603823.SH", "002971.SZ"])  # → {"603823.SH": "百合花", ...}
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_NAME_CACHE: dict[str, str] = {}
_LOADED = False

# 2026-09-03 加入：快照过期告警阈值（天）
# 背景：该文件自 2026-07-17 生成后无任何刷新机制，7 周后已失真 ——
#   漏网 5 只新戴帽 ST（天际股份→ST天际 等）+ 误杀 12 只已摘帽（ST京蓝→京蓝科技 等）。
#   最危险的是它**不报错**：名称查得到，只是过时，ST 过滤照跑但结果全错。
# 刷新命令：python shared/refresh_stock_names.py
STALE_DAYS = 30


def _warn_if_stale(path: Path) -> None:
    """快照超过 STALE_DAYS 天未更新则告警

    不抛异常——名称过期影响的是准确性而非可用性，让调用继续跑，
    但必须在日志里留痕，否则又会变成下一个"静默失效 7 周"。
    """
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days <= STALE_DAYS:
        return
    logger.warning(
        f"[stock_name] ⚠️ 名称快照已 {age_days:.0f} 天未更新（阈值 {STALE_DAYS} 天）：{path.name}。"
        f"ST/*ST 识别可能失真（新戴帽漏网 + 已摘帽误杀）。"
        f"请运行：python shared/refresh_stock_names.py"
    )


def _load():
    """懒加载名称映射（线程安全仅调用一次）"""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    # 优先读 shared 目录（多服务共用），回退到 data 目录
    for candidate in [
        Path(__file__).resolve().parent / "astock_code_name.json",
        Path(__file__).resolve().parent.parent / "data" / "astock_code_name.json",
    ]:
        if candidate.exists():
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                for code_key, name_val in raw.items():
                    _NAME_CACHE[code_key] = name_val
                    # 兼容 ts_code 后缀格式
                    if "." not in code_key:
                        suffix = ".SH" if code_key.startswith(("6", "9")) else ".SZ"
                        _NAME_CACHE[f"{code_key}{suffix}"] = name_val
                logger.info(f"[stock_name] 加载 {len(raw)} 条股票名称映射")
                _warn_if_stale(candidate)
                return
            except Exception as e:
                logger.warning(f"[stock_name] 加载失败: {e}")

    logger.warning("[stock_name] 未找到 astock_code_name.json，名称功能不可用")


def resolve_name(ts_code: str) -> str:
    """解析单只股票名称，失败返回空字符串"""
    _load()
    return _NAME_CACHE.get(ts_code, "")


def resolve_name_batch(ts_codes: list[str]) -> dict[str, str]:
    """批量解析，返回 {ts_code: name}"""
    _load()
    return {code: _NAME_CACHE.get(code, "") for code in ts_codes}


def fmt_stock(ts_code: str) -> str:
    """格式化为「名称(代码)」，如「百合花(603823.SH)」"""
    name = resolve_name(ts_code)
    return f"{name}({ts_code})" if name else ts_code
