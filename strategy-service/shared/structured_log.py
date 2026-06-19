"""结构化日志 — P5 日志统一化

提供一致的日志配置，默认输出格式为:
    2026-06-18 22:30:00.123 [INFO ] [services.data_service] 消息内容  {"key": "val"}

用法:
    from shared.structured_log import get_logger

    logger = get_logger(__name__)
    logger.info("数据源切换", source="tencent", latency_ms=230)
    logger.error("API 调用失败", code=503, detail={"url": "..."})
"""

import logging
import sys
from typing import Any


class _StructuredLogger(logging.Logger):
    """Python 3.13 兼容的 Logger 子类。

    标准 Logger._log() 从 3.13 起拒绝额外的 **kwargs 参数。
    本子类自动将额外 kwargs 格式化为结构化字符串后拼接到 msg 中。
    """

    def _log(
        self,
        level: int,
        msg: object,
        args: tuple[object, ...] = (),
        exc_info: Any = None,
        extra: dict[str, Any] | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **kwargs: Any,
    ) -> None:
        if kwargs:
            extra_str = _format_extra(kwargs)
            msg = f"{msg}  {extra_str}"
        # extra 必须是 dict 或 None
        super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel + 1)


# ── 格式常量 ────────────────────────────────────────────

_TEXT_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)s] %(message)s"
_TEXT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── 级别名 ──────────────────────────────────────────────

_LEVEL_NAMES: dict[int, str] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "FATAL",
}


def _init_root_logger():
    """初始化根日志器（应用启动时调用一次即可）。"""
    root = logging.getLogger()
    if root.handlers:
        return  # 已初始化

    root.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_TEXT_FORMAT, datefmt=_TEXT_DATE_FORMAT)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # 第三方库降噪
    for noisy in ("httpx", "urllib3", "asyncio", "aiosqlite", "sqlalchemy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取统一配置的日志器。

    参数:
        name: 通常传入 __name__，自动按模块名提供日志上下文。

    返回:
        已配置的 logging.Logger 实例（Python 3.13+ 兼容）。
    """
    logging.setLoggerClass(_StructuredLogger)
    _init_root_logger()
    return logging.getLogger(name)


class LogHelper:
    """结构化日志辅助方法（静态工具类）。"""

    @staticmethod
    def summary(
        logger: logging.Logger,
        level: int,
        message: str,
        **kwargs: Any,
    ) -> None:
        """输出结构化日志，kwargs 自动 JSON 序列化附加。

        logger.info("任务完成", extra={"duration": 1.2}) 见下方说明
        这里简单地直接拼接到消息后
        """
        extra_str = _format_extra(kwargs)
        full_msg = f"{message}  {extra_str}" if extra_str else message
        logger.log(level, full_msg)

    @staticmethod
    def info(logger: logging.Logger, message: str, **kwargs: Any) -> None:
        LogHelper.summary(logger, logging.INFO, message, **kwargs)

    @staticmethod
    def warn(logger: logging.Logger, message: str, **kwargs: Any) -> None:
        LogHelper.summary(logger, logging.WARNING, message, **kwargs)

    @staticmethod
    def error(logger: logging.Logger, message: str, **kwargs: Any) -> None:
        LogHelper.summary(logger, logging.ERROR, message, **kwargs)

    @staticmethod
    def debug(logger: logging.Logger, message: str, **kwargs: Any) -> None:
        LogHelper.summary(logger, logging.DEBUG, message, **kwargs)


def _format_extra(kwargs: dict[str, Any]) -> str:
    """将 kwargs 格式化为 \"key=value key2=value2\" 形式。"""
    if not kwargs:
        return ""
    parts: list[str] = []
    for k, v in kwargs.items():
        if isinstance(v, float):
            parts.append(f"{k}={v:.3f}")
        elif isinstance(v, int | str):
            parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={v!r}")
    return "  " + "  ".join(parts)
