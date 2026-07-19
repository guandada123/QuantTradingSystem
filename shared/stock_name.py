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
from pathlib import Path

logger = logging.getLogger(__name__)

_NAME_CACHE: dict[str, str] = {}
_LOADED = False


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
