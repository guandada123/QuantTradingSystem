"""统一异常层次结构 — P5 异常统一化

用法:
    from shared.exceptions import (
        DataSourceException, RepositoryException,
        StrategyException, ConfigException,
    )

    raise DataSourceException("Tencent API 无响应", source="tencent", code=503)
"""

from typing import Any


class QTSBaseException(Exception):
    """QTS 所有自定义异常的基类。"""

    def __init__(
        self,
        message: str,
        *,
        code: str | int | None = None,
        detail: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ):
        self.message = message
        self.code = code
        self.detail = detail or {}
        self.cause = cause
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """序列化为结构化数据（日志/API 响应用）。"""
        d: dict[str, Any] = {
            "error_type": type(self).__name__,
            "message": self.message,
        }
        if self.code is not None:
            d["code"] = self.code
        if self.detail:
            d["detail"] = self.detail
        return d


# ── 数据源异常 ──────────────────────────────────────────


class DataSourceException(QTSBaseException):
    """数据源（行情 / 基本面 / 财务）相关异常。"""


class DataSourceTimeout(DataSourceException):
    """数据源请求超时。"""


class DataSourceUnavailable(DataSourceException):
    """数据源不可用（服务下线 / 限流 / 无返回）。"""


class DataSourceParseError(DataSourceException):
    """数据源返回格式解析失败。"""


# ── 数据访问层异常 ──────────────────────────────────────


class RepositoryException(QTSBaseException):
    """数据库 / Repository 操作异常。"""


class EntityNotFoundError(RepositoryException):
    """查询的记录不存在。"""


class EntityConflictError(RepositoryException):
    """记录冲突（重复 / 约束违反）。"""


class DatabaseConnectionError(RepositoryException):
    """数据库连接异常。"""


# ── 策略异常 ────────────────────────────────────────────


class StrategyException(QTSBaseException):
    """策略引擎相关异常。"""


class StrategyNotFoundError(StrategyException):
    """策略不存在。"""


class StrategyValidationError(StrategyException):
    """策略参数校验失败。"""


class StrategyConflictError(StrategyException):
    """策略冲突（ID 重复 / 资源配置冲突）。"""


class StrategyExecutionError(StrategyException):
    """策略执行过程异常。"""


# ── 调度异常 ────────────────────────────────────────────


class SchedulerException(QTSBaseException):
    """任务调度器异常。"""


class SchedulerConflictError(SchedulerException):
    """调度冲突（重复任务 / 资源竞争）。"""


# ── 配置异常 ────────────────────────────────────────────


class ConfigException(QTSBaseException):
    """配置 / 环境变量异常。"""


class ConfigMissingError(ConfigException):
    """必需配置缺失。"""


# ── 执行/交易异常 ────────────────────────────────────────


class ExecutionException(QTSBaseException):
    """交易执行（下单 / 撤单 / 查询）异常。"""


# ── AI 服务异常 ──────────────────────────────────────────


class AIServiceException(QTSBaseException):
    """AI 模型调用异常。"""


# ── WebSocket 异常 ──────────────────────────────────────


class WebSocketException(QTSBaseException):
    """WebSocket 连接或消息异常。"""


# ── 告警异常 ────────────────────────────────────────────


class AlertException(QTSBaseException):
    """告警推送异常。"""


# ── 向后兼容别名（旧代码过渡用） ──────────────────────────


class DataSourceError(DataSourceException):
    """旧名 → DataSourceException 的别名。"""
