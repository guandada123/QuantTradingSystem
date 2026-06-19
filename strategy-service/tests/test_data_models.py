"""
测试数据模型工具函数
Cover services/data_models.py 中未覆盖的分支。
"""

from services.data_models import format_trade_date, normalize_date_range


class TestFormatTradeDate:
    """测试 format_trade_date()"""

    def test_empty_string_returns_empty(self):
        """空字符串 → 返回空字符串 (line 75-76)"""
        assert format_trade_date("") == ""

    def test_removes_dashes(self):
        """包含横线的日期去掉横线 (line 77-78)"""
        assert format_trade_date("2026-06-19") == "20260619"

    def test_eight_digit_adds_dashes(self):
        """8位纯数字加横线 (line 79-80)"""
        assert format_trade_date("20260619") == "2026-06-19"

    def test_other_format_returns_as_is(self):
        """非标准格式原样返回 (line 81)"""
        assert format_trade_date("2026/06/19") == "2026/06/19"


class TestNormalizeDateRange:
    """测试 normalize_date_range()"""

    def test_start_date_with_dashes(self):
        """start_date 含横线 → 去掉横线 (line 87)"""
        result, _ = normalize_date_range(start_date="2026-01-01")
        assert result == "20260101"

    def test_end_date_with_dashes(self):
        """end_date 含横线 → 去掉横线 (line 89)"""
        _, result = normalize_date_range(end_date="2026-06-19")
        assert result == "20260619"

    def test_default_start_date(self):
        """start_date=None → 自动计算 days (line 90-91, fallback)"""
        result, _ = normalize_date_range(start_date=None, days=30)
        # 使用字符串伪造断言，避免时间戳耦合
        assert len(result) == 8

    def test_default_end_date(self):
        """end_date=None → 自动计算 (line 92-93)"""
        _, result = normalize_date_range(end_date=None)
        assert len(result) == 8

    def test_both_dates_provided(self):
        """start_date + end_date 都提供 → 原样返回"""
        s, e = normalize_date_range(start_date="20260101", end_date="20260619")
        assert s == "20260101"
        assert e == "20260619"
