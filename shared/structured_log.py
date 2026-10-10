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
from typing import Any, cast, override


class StructuredLogger(logging.Logger):
    """Python 3.13 兼容的 Logger 子类。

    标准 Logger._log() 从 3.13 起拒绝额外的 **kwargs 参数。
    本子类自动将额外 kwargs 格式化为结构化字符串后拼接到 msg 中。
    """

    def _log(  # type: ignore[override]
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

    # ── 重写公共方法以接受 **kwargs（mypy 需要）─────────────

    @override
    def info(self, msg: object, *args: object, **kwargs: Any) -> None:
        super().info(msg, *args, **kwargs)

    @override
    def error(self, msg: object, *args: object, **kwargs: Any) -> None:
        super().error(msg, *args, **kwargs)

    @override
    def warning(self, msg: object, *args: object, **kwargs: Any) -> None:
        super().warning(msg, *args, **kwargs)

    @override
    def debug(self, msg: object, *args: object, **kwargs: Any) -> None:
        super().debug(msg, *args, **kwargs)

    @override
    def critical(self, msg: object, *args: object, **kwargs: Any) -> None:
        super().critical(msg, *args, **kwargs)

    @override
    def log(self, level: int, msg: object, *args: object, **kwargs: Any) -> None:
        super().log(level, msg, *args, **kwargs)


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


def get_logger(name: str) -> StructuredLogger:
    """获取统一配置的日志器。

    参数:
        name: 通常传入 __name__，自动按模块名提供日志上下文。

    返回:
        已配置的 StructuredLogger 实例（支持 **kwargs 结构化日志）。

    注意（2026-10-10 修复）：
        `logging.setLoggerClass()` 只对**之后新建**的 logger 生效。若同名 logger 在本函数
        首次调用前已被创建为原生 `logging.Logger`（例如 `pytest --cov=<点分模块名>` 让
        coverage 提前导入模块、或外部代码按名字取过 logger），`getLogger()` 会返回缓存里的
        原生实例，原来的 `assert isinstance(...)` 会让**整个模块 import 崩溃**。
        该问题已在 strategy-service/tests/test_data_quality.py 留下过事故注释（2026-09-04），
        因此这里改为就地升级实例的类，不再硬失败。

        安全性：StructuredLogger 未定义 `__init__`，只重写 `_log` 与各级日志方法，
        不依赖任何新增实例属性，故在实例上替换 `__class__` 是安全的。
    """
    logging.setLoggerClass(StructuredLogger)
    _init_root_logger()
    logger = logging.getLogger(name)
    if not isinstance(logger, StructuredLogger):
        logger.__class__ = StructuredLogger
    # mypy 不会因 `__class__` 赋值而收窄类型，这里显式声明
    # （运行期由上面的分支保证，StructuredLogger 未定义 __init__，替换类是安全的）
    return cast("StructuredLogger", logger)


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
