"""
执行服务 - 集中异常定义
"""


class OrderError(Exception):
    """订单异常"""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class RiskError(Exception):
    """风控异常"""

    def __init__(self, message: str, status_code: int = 403):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PositionError(Exception):
    """持仓异常"""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)
