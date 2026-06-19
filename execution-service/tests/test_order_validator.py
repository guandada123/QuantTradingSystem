"""
订单输入验证模块 - 单元测试

覆盖 order_validator.py 的两个纯函数：
- validate_order_input(): 订单输入校验（TS Code、方向、类型、数量、价格、触发价）
- check_trading_hours(): 交易时间检查（工作日时段、非交易时段、周末）
"""

from datetime import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_validator import check_trading_hours, validate_order_input

# ============================================================
# validate_order_input 测试
# ============================================================


class TestValidateOrderInput:
    """订单输入校验测试"""

    # ---- 有效输入 ----

    def test_valid_buy_limit(self):
        """有效买入限价单"""
        assert validate_order_input("600519.SH", "BUY", "LIMIT", 1800.0, 100) is None

    def test_valid_sell_limit(self):
        """有效卖出限价单"""
        assert validate_order_input("000001.SZ", "SELL", "LIMIT", 15.5, 200) is None

    def test_valid_buy_market(self):
        """有效买入市价单"""
        assert validate_order_input("600519.SH", "BUY", "MARKET", None, 100) is None

    def test_valid_sell_market(self):
        """有效卖出市价单（无价格）"""
        assert validate_order_input("000001.SZ", "SELL", "MARKET", None, 300) is None

    def test_valid_buy_stop(self):
        """有效买入STOP条件单"""
        assert (
            validate_order_input("600519.SH", "BUY", "STOP", 1300.0, 100, trigger_price=1400.0)
            is None
        )

    def test_valid_sell_stop(self):
        """有效卖出STOP条件单"""
        assert (
            validate_order_input("000001.SZ", "SELL", "STOP", 15.0, 200, trigger_price=12.0) is None
        )

    def test_valid_large_quantity(self):
        """有效大数量订单"""
        assert validate_order_input("600519.SH", "BUY", "LIMIT", 1800.0, 10000) is None

    def test_valid_float_price(self):
        """有效浮点型价格"""
        assert validate_order_input("600519.SH", "SELL", "LIMIT", 18.88, 100) is None

    # ---- TS Code 格式错误 ----

    def test_invalid_ts_code_no_dot(self):
        """股票代码没有点号"""
        result = validate_order_input("600519", "BUY", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "格式错误" in result

    def test_invalid_ts_code_wrong_suffix(self):
        """股票代码后缀非SH/SZ"""
        result = validate_order_input("600519.SHZ", "BUY", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "格式错误" in result

    def test_invalid_ts_code_wrong_suffix_sse(self):
        """股票代码后缀SS应被拒绝"""
        result = validate_order_input("600519.SS", "BUY", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "格式错误" in result

    def test_invalid_ts_code_short_digits(self):
        """股票代码位数不足6位"""
        result = validate_order_input("60051.SH", "BUY", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "格式错误" in result

    def test_invalid_ts_code_long_digits(self):
        """股票代码超过6位"""
        result = validate_order_input("6000519.SH", "BUY", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "格式错误" in result

    def test_invalid_ts_code_empty(self):
        """股票代码为空字符串"""
        result = validate_order_input("", "BUY", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "格式错误" in result

    def test_invalid_ts_code_lowercase(self):
        """股票代码后缀小写应被拒绝"""
        result = validate_order_input("600519.sh", "BUY", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "格式错误" in result

    # ---- 方向错误 ----

    def test_invalid_direction_bad_value(self):
        """方向为无效值"""
        result = validate_order_input("600519.SH", "INVALID", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "方向错误" in result
        assert "INVALID" in result

    def test_invalid_direction_lowercase(self):
        """方向为小写应被拒绝"""
        result = validate_order_input("600519.SH", "buy", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "方向错误" in result

    def test_invalid_direction_empty(self):
        """方向为空字符串"""
        result = validate_order_input("600519.SH", "", "LIMIT", 1800.0, 100)
        assert result is not None
        assert "方向错误" in result

    # ---- 订单类型错误 ----

    def test_invalid_order_type(self):
        """订单类型为无效值"""
        result = validate_order_input("600519.SH", "BUY", "INVALID", 1800.0, 100)
        assert result is not None
        assert "订单类型错误" in result

    def test_invalid_order_type_empty(self):
        """订单类型为空"""
        result = validate_order_input("600519.SH", "BUY", "", 1800.0, 100)
        assert result is not None
        assert "订单类型错误" in result

    # ---- 数量错误 ----

    def test_quantity_zero(self):
        """数量为零"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", 1800.0, 0)
        assert result is not None
        assert "正整数" in result

    def test_quantity_negative(self):
        """数量为负数"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", 1800.0, -100)
        assert result is not None
        assert "正整数" in result

    def test_quantity_not_multiple_of_100(self):
        """数量非100的整数倍"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", 1800.0, 150)
        assert result is not None
        assert "100的整数倍" in result

    def test_quantity_not_multiple_of_100_10(self):
        """数量为10（非100倍数）"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", 1800.0, 10)
        assert result is not None
        assert "100的整数倍" in result

    def test_quantity_is_float(self):
        """数量为浮点数（非整数）"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", 1800.0, 100.0)
        assert result is not None
        assert "正整数" in result

    # ---- 价格错误 ----

    def test_limit_missing_price(self):
        """限价单未提供价格（None）"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", None, 100)
        assert result is not None
        assert "有效价格" in result

    def test_limit_zero_price(self):
        """限价单价格为0"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", 0, 100)
        assert result is not None
        assert "有效价格" in result

    def test_limit_negative_price(self):
        """限价单价格为负数"""
        result = validate_order_input("600519.SH", "BUY", "LIMIT", -10.0, 100)
        assert result is not None
        assert "有效价格" in result

    def test_stop_missing_price(self):
        """STOP单未提供价格"""
        result = validate_order_input("600519.SH", "BUY", "STOP", None, 100, trigger_price=1400.0)
        assert result is not None
        assert "有效价格" in result

    # ---- STOP 条件单触发价错误 ----

    def test_stop_missing_trigger_price(self):
        """STOP单未提供trigger_price"""
        result = validate_order_input("600519.SH", "BUY", "STOP", 1300.0, 100)
        assert result is not None
        assert "trigger_price" in result

    def test_stop_zero_trigger_price(self):
        """STOP单trigger_price为0"""
        result = validate_order_input("600519.SH", "BUY", "STOP", 1300.0, 100, trigger_price=0)
        assert result is not None
        assert "触发价格" in result

    def test_stop_negative_trigger_price(self):
        """STOP单trigger_price为负数"""
        result = validate_order_input("600519.SH", "BUY", "STOP", 1300.0, 100, trigger_price=-10.0)
        assert result is not None
        assert "触发价格" in result

    def test_buy_stop_trigger_le_price(self):
        """BUY STOP: trigger_price <= price 应拒绝"""
        result = validate_order_input("600519.SH", "BUY", "STOP", 1500.0, 100, trigger_price=1400.0)
        assert result is not None
        assert "触发价" in result

    def test_buy_stop_trigger_equal_price(self):
        """BUY STOP: trigger_price == price 应拒绝"""
        result = validate_order_input("600519.SH", "BUY", "STOP", 1400.0, 100, trigger_price=1400.0)
        assert result is not None
        assert "触发价" in result

    def test_sell_stop_trigger_ge_price(self):
        """SELL STOP: trigger_price >= price 应拒绝"""
        result = validate_order_input("000001.SZ", "SELL", "STOP", 10.0, 100, trigger_price=15.0)
        assert result is not None
        assert "触发价" in result

    def test_sell_stop_trigger_equal_price_sell(self):
        """SELL STOP: trigger_price == price 应拒绝"""
        result = validate_order_input("000001.SZ", "SELL", "STOP", 15.0, 100, trigger_price=15.0)
        assert result is not None
        assert "触发价" in result

    # ---- MARKET类型无需价格 ----

    def test_market_no_price_valid(self):
        """MARKET订单可以不提供价格"""
        assert validate_order_input("600519.SH", "BUY", "MARKET", None, 100) is None


# ============================================================
# check_trading_hours 测试
# ============================================================


class TestCheckTradingHours:
    """交易时间检查测试"""

    # ---- 工作日交易时段 - valid ----

    def test_weekday_morning_session(self):
        """工作日早盘交易时段（9:30-11:30）应返回None"""
        # 2026-06-15 是星期一
        dt = datetime(2026, 6, 15, 10, 0, 0)
        assert check_trading_hours(dt) is None

    def test_weekday_morning_start(self):
        """工作日上午9:30开盘时点"""
        dt = datetime(2026, 6, 15, 9, 30, 0)
        assert check_trading_hours(dt) is None

    def test_weekday_morning_end(self):
        """工作日上午11:30收盘时点"""
        dt = datetime(2026, 6, 15, 11, 30, 0)
        assert check_trading_hours(dt) is None

    def test_weekday_afternoon_session(self):
        """工作日下午盘交易时段（13:00-15:00）应返回None"""
        dt = datetime(2026, 6, 15, 14, 0, 0)
        assert check_trading_hours(dt) is None

    def test_weekday_afternoon_start(self):
        """工作日下午13:00开盘时点"""
        dt = datetime(2026, 6, 15, 13, 0, 0)
        assert check_trading_hours(dt) is None

    def test_weekday_afternoon_end(self):
        """工作日下午15:00收盘时点"""
        dt = datetime(2026, 6, 15, 15, 0, 0)
        assert check_trading_hours(dt) is None

    # ---- 工作日非交易时段 - invalid ----

    def test_weekday_before_open(self):
        """工作日上午盘前（9:00）"""
        dt = datetime(2026, 6, 15, 9, 0, 0)
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易时间" in result

    def test_weekday_lunch_break(self):
        """工作日午休时段（12:00）"""
        dt = datetime(2026, 6, 15, 12, 0, 0)
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易时间" in result

    def test_weekday_after_close(self):
        """工作日下午盘后（15:30）"""
        dt = datetime(2026, 6, 15, 15, 30, 0)
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易时间" in result

    def test_weekday_early_morning(self):
        """工作日凌晨（6:00）"""
        dt = datetime(2026, 6, 15, 6, 0, 0)
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易时间" in result

    def test_weekday_midnight(self):
        """工作日午夜（0:00）"""
        dt = datetime(2026, 6, 15, 0, 0, 0)
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易时间" in result

    # ---- 周末 ----

    def test_saturday(self):
        """周六全天不可交易"""
        dt = datetime(2026, 6, 13, 10, 0, 0)  # 周六
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易日" in result
        assert "周" in result

    def test_saturday_afternoon(self):
        """周六下午不可交易"""
        dt = datetime(2026, 6, 13, 14, 0, 0)  # 周六
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易日" in result

    def test_sunday(self):
        """周日全天不可交易"""
        dt = datetime(2026, 6, 14, 10, 0, 0)  # 周日
        result = check_trading_hours(dt)
        assert result is not None
        assert "非交易日" in result

    # ---- 默认参数 ----

    def test_default_now(self):
        """不传参数时使用当前时间（不报错即可）"""
        import time

        # 不指定时间，使用datetime.now()
        result = check_trading_hours()
        # 不会抛出异常，返回str或None
        assert isinstance(result, (str, type(None)))
