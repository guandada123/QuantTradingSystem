"""
测试参数网格模块
Cover services/param_grids.py 中未覆盖的分支：
- _load_stock_params_file 文件不存在 (line 102)
- _load_stock_params_file JSON 解析/IO 错误 (lines 105-106)
- get_stock_params vwm 分支 (lines 140-148)
- get_stock_params bollinger 分支 (lines 149-157)
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from services.param_grids import (
    _STOCK_PARAMS_CACHE,
    _load_stock_params_file,
    get_default_param_grid,
    get_stock_params,
)


# 在每个测试前重置全局缓存，保证隔离
@pytest.fixture(autouse=True)
def reset_cache():
    """重置 _STOCK_PARAMS_CACHE 避免跨测试干扰"""
    import services.param_grids as pg

    pg._STOCK_PARAMS_CACHE = None
    yield


class TestLoadStockParamsFile:
    """测试 _load_stock_params_file() 异常路径"""

    def test_file_not_found_returns_empty(self):
        """文件不存在 → 返回 {} (line 102)"""
        with patch.object(Path, "exists", return_value=False):
            result = _load_stock_params_file("nonexistent.json")
        assert result == {}

    def test_invalid_json_returns_empty(self):
        """JSON 解析失败 → 返回 {} (lines 105-106)"""
        with patch.object(Path, "exists", return_value=True):
            # patch read_text 返回非法 JSON
            with patch.object(Path, "read_text", return_value="{invalid}"):
                result = _load_stock_params_file("bad.json")
        assert result == {}

    def test_oserror_returns_empty(self):
        """OSError 捕获 → 返回 {} (lines 105-106)"""
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "read_text", side_effect=OSError("IO error")):
                result = _load_stock_params_file("bad.json")
        assert result == {}


class TestGetStockParamsNoMatch:
    """测试 get_stock_params 无匹配时的 None"""

    def test_no_match_returns_none(self):
        """策略代码不匹配 → 返回 None"""
        # 预先填充缓存一个条目，然后查询不同的键
        import services.param_grids as pg

        pg._STOCK_PARAMS_CACHE = {
            "vwm:000001.SZ": {"ma_fast": 5, "ma_slow": 20, "vol_multiplier_buy": 1.0}
        }
        result = get_stock_params("999999.SZ", "vwm")
        assert result is None


class TestGetStockParamsVwm:
    """测试 get_stock_params vwm 策略 (lines 140-148)"""

    def test_vwm_returns_correct_params(self):
        """vwm 策略返回固定的参数字段"""
        import services.param_grids as pg

        pg._STOCK_PARAMS_CACHE = {
            "vwm:600519.SH": {
                "ma_fast": 5,
                "ma_slow": 20,
                "vol_multiplier_buy": 1.0,
            }
        }
        result = get_stock_params("600519.SH", "vwm")
        assert result == {
            "ma_fast": 5,
            "ma_slow": 20,
            "vol_multiplier_buy": 1.0,
            "volume_period": 20,
            "rsi_period": 14,
            "rsi_overbought": 80,
        }


class TestGetStockParamsBollinger:
    """测试 get_stock_params bollinger 策略 (lines 149-157)"""

    def test_bollinger_with_params(self):
        """bollinger 策略包含嵌套 params"""
        import services.param_grids as pg

        pg._STOCK_PARAMS_CACHE = {
            "bollinger:000001.SZ": {
                "params": {
                    "period": 22,
                    "std_mult": 2.0,
                    "rsi_period": 10,
                    "rsi_oversold": 35,
                    "rsi_overbought": 65,
                }
            }
        }
        result = get_stock_params("000001.SZ", "bollinger")
        assert result == {
            "period": 22,
            "std_mult": 2.0,
            "rsi_period": 10,
            "rsi_oversold": 35,
            "rsi_overbought": 65,
        }

    def test_bollinger_without_params(self):
        """bollinger 策略无嵌套 params → 使用默认值"""
        import services.param_grids as pg

        pg._STOCK_PARAMS_CACHE = {"bollinger:000001.SZ": {}}
        result = get_stock_params("000001.SZ", "bollinger")
        # 没有 params 键，所有值使用 .get() 默认值
        assert result["period"] == 20
        assert result["std_mult"] == 1.8
        assert result["rsi_period"] == 14
        assert result["rsi_oversold"] == 40
        assert result["rsi_overbought"] == 60


class TestGetStockParamsUnknown:
    """测试 get_stock_params 未知策略 (line 158)"""

    def test_unknown_strategy_returns_none(self):
        """未知策略名 → 返回 None (line 158)"""
        import services.param_grids as pg

        pg._STOCK_PARAMS_CACHE = {"unknown:000001.SZ": {"ma_fast": 5}}
        result = get_stock_params("000001.SZ", "unknown")
        assert result is None


class TestGetDefaultParamGrid:
    """测试 get_default_param_grid"""

    def test_known_strategy(self):
        """已知策略返回参数网格"""
        grid = get_default_param_grid("ma-cross")
        assert "ma_fast" in grid
        assert "ma_slow" in grid

    def test_unknown_strategy_returns_empty(self):
        """未知策略返回空字典"""
        grid = get_default_param_grid("nonexistent")
        assert grid == {}
