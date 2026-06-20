"""
数据源抽象接口 (provider_interface.py) 测试。

覆盖:
  - QuoteProvider ABC（验证 abstraction 不可直接实例化）
  - FallbackChain 降级链执行器（execute: 成功/失败/异常/去重）
"""

from unittest.mock import MagicMock, patch

import pytest
from services.provider_interface import FallbackChain, QuoteProvider


class TestQuoteProvider:
    """QuoteProvider 抽象基类测试"""

    def test_cannot_instantiate(self):
        """不能直接实例化抽象类"""
        with pytest.raises(TypeError, match="abstract"):
            QuoteProvider()

    def test_concrete_subclass(self):
        """具体子类可以正常实例化"""

        class MockProvider(QuoteProvider):
            def get_realtime_quote(self, ts_code):
                return {"price": 10.0}

            def get_batch_realtime(self, ts_codes):
                return [{"price": 10.0}]

            def get_daily_kline(self, ts_code, start_date, end_date, limit=100):
                return [{"close": 10.0}]

            def get_index_realtime(self, index_codes):
                return [{"price": 3000.0}]

            def get_fundamental(self, ts_code):
                return {"pe_ttm": 15.0}

        provider = MockProvider()
        assert provider.get_realtime_quote("000001.SZ")["price"] == 10.0


class TestFallbackChain:
    """FallbackChain 降级链测试"""

    def test_first_provider_succeeds(self):
        """第一个 provider 成功 → 直接返回"""
        p1 = MagicMock()
        p1.get_price.return_value = {"price": 10.0}
        p2 = MagicMock()
        chain = FallbackChain([("p1", p1), ("p2", p2)])
        getter = lambda p: p.get_price
        validator = lambda r: r.get("price", 0) > 0
        result = chain.execute(getter, validator, "000001.SZ")
        assert result == {"price": 10.0}
        p1.get_price.assert_called_once_with("000001.SZ")
        p2.get_price.assert_not_called()

    def test_first_provider_fails_validator(self):
        """第一个 provider 返回结果不通过校验 → 尝试第二个"""
        p1 = MagicMock()
        p1.get_price.return_value = {"price": 0.0}
        p2 = MagicMock()
        p2.get_price.return_value = {"price": 15.0}
        chain = FallbackChain([("p1", p1), ("p2", p2)])
        getter = lambda p: p.get_price
        validator = lambda r: r.get("price", 0) > 0
        result = chain.execute(getter, validator, "000001.SZ")
        assert result == {"price": 15.0}

    def test_all_fail_returns_none(self):
        """所有 provider 均失败 → 返回 None"""
        p1 = MagicMock()
        p1.get_price.return_value = {"price": 0.0}
        p2 = MagicMock()
        p2.get_price.return_value = {"price": -1.0}
        chain = FallbackChain([("p1", p1), ("p2", p2)])
        getter = lambda p: p.get_price
        validator = lambda r: r.get("price", 0) > 0
        result = chain.execute(getter, validator, "000001.SZ")
        assert result is None

    def test_provider_raises_exception(self):
        """provider 抛出异常 → 跳过并尝试下一个"""
        p1 = MagicMock()
        p1.get_price.side_effect = ConnectionError("网络超时")
        p2 = MagicMock()
        p2.get_price.return_value = {"price": 12.0}
        chain = FallbackChain([("p1", p1), ("p2", p2)])
        getter = lambda p: p.get_price
        validator = lambda r: r.get("price", 0) > 0
        result = chain.execute(getter, validator, "000001.SZ")
        assert result == {"price": 12.0}

    def test_duplicate_source_skipped(self):
        """同名 source 去重 — 第二个被跳过"""
        p = MagicMock()
        p.get_price.return_value = {"price": 10.0}
        chain = FallbackChain([("same", p), ("same", p)])
        getter = lambda p: p.get_price
        validator = lambda r: True
        result = chain.execute(getter, validator, "000001.SZ")
        assert result == {"price": 10.0}
        p.get_price.assert_called_once()

    def test_exception_and_validator_fail(self):
        """混合场景 — 一个抛异常、一个校验失败 → None"""
        p1 = MagicMock()
        p1.get_price.side_effect = ValueError("bad data")
        p2 = MagicMock()
        p2.get_price.return_value = {"price": 0.0}
        chain = FallbackChain([("p1", p1), ("p2", p2)])
        getter = lambda p: p.get_price
        validator = lambda r: r.get("price", 0) > 0
        result = chain.execute(getter, validator, "000001.SZ")
        assert result is None

    def test_duplicate_skips_after_first_fails(self):
        """同名 source 的第一个失败 → 第二个被跳过（触发 continue），第三个成功"""
        p1 = MagicMock()
        p1.get_price.return_value = {"price": 0.0}  # fails validator
        p2 = MagicMock()  # same name, should be skipped
        p2.get_price.return_value = {"price": 99.0}  # would succeed if called
        p3 = MagicMock()
        p3.get_price.return_value = {"price": 15.0}
        chain = FallbackChain([("shared", p1), ("shared", p2), ("p3", p3)])
        getter = lambda p: p.get_price
        validator = lambda r: r.get("price", 0) > 0
        result = chain.execute(getter, validator, "000001.SZ")
        assert result == {"price": 15.0}
        p1.get_price.assert_called_once()
        p2.get_price.assert_not_called()  # skipped by dedup
        p3.get_price.assert_called_once()
