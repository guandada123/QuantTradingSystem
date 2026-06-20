"""
订单输入验证模块
可独立测试的纯验证逻辑 — 从 order_manager 拆分
"""

from datetime import datetime, time
import re

# TS Code 格式: 6位数字.SH 或 .SZ
TS_CODE_PATTERN = re.compile(r"^\d{6}\.(SZ|SH)$")


def validate_order_input(
    ts_code: str,
    direction: str,
    order_type: str,
    price: float | None,
    quantity: int,
    trigger_price: float | None = None,
) -> str | None:
    """
    订单输入校验，返回 None 表示通过，否则返回错误信息

    规则:
    - TS Code: 6位数字.SH 或 .SZ
    - 方向: BUY / SELL
    - 类型: LIMIT / MARKET / STOP
    - 数量: 正整数，100 的整数倍
    - 限价/STOP: 必须提供有效价格
    - STOP: 必须提供触发价，且与当前价逻辑一致
    """
    # TS Code 格式
    if not TS_CODE_PATTERN.match(ts_code):
        return f"股票代码格式错误: {ts_code}，正确格式如 600519.SH"

    # Direction
    if direction not in ("BUY", "SELL"):
        return f"交易方向错误: {direction}，仅支持 BUY/SELL"

    # Order type
    if order_type not in ("LIMIT", "MARKET", "STOP"):
        return f"订单类型错误: {order_type}，仅支持 LIMIT/MARKET/STOP"

    # Quantity: 正整数且 100 的倍数
    if not isinstance(quantity, int) or quantity <= 0:
        return f"数量必须为正整数: {quantity}"
    if quantity % 100 != 0:
        return f"数量必须为100的整数倍（A股最小交易单位）: {quantity}"

    # Price: 限价单和 STOP 单必须提供有效价格
    if order_type in ("LIMIT", "STOP"):
        if price is None or price <= 0:
            return f"限价单/STOP单必须提供有效价格: {price}"

    # STOP 条件单专项验证
    if order_type == "STOP":
        if trigger_price is None or trigger_price <= 0:
            return "STOP单必须提供trigger_price（触发价格）"
        assert price is not None and price > 0  # 已在 LIMIT/STOP 分支中验证  # noqa: S101
        if direction == "BUY" and trigger_price <= price:
            return f"买入STOP单触发价({trigger_price})必须 > 当前价({price})"
        if direction == "SELL" and trigger_price >= price:
            return f"卖出STOP单触发价({trigger_price})必须 < 当前价({price})"

    return None


def check_trading_hours(now: datetime | None = None) -> str | None:
    """
    检查是否在 A 股交易时间，返回 None 表示可交易，否则返回错误信息

    交易时间: 工作日 9:30–11:30, 13:00–15:00
    """
    if now is None:
        now = datetime.now()

    weekday = now.weekday()
    if weekday >= 5:
        return f"非交易日（周末），当前: 周{['一', '二', '三', '四', '五', '六', '日'][weekday]}"

    current_time = now.time()
    morning_start = time(9, 30)
    morning_end = time(11, 30)
    afternoon_start = time(13, 0)
    afternoon_end = time(15, 0)

    if not (
        (morning_start <= current_time <= morning_end)
        or (afternoon_start <= current_time <= afternoon_end)
    ):
        return f"非交易时间，当前: {current_time.strftime('%H:%M')}"

    return None
