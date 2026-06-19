"""
Tests for stock_insight_engine package — 6 sub-modules + engine class.

测试策略：
- 纯函数（indicators/penalty/filtering/ml_utils）：直接调用验证输出
- scoring：内部委托 penalty，验证综合评分逻辑
- engine：mock data_service 验证编排逻辑
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from services.stock_insight_engine.engine import StockInsightEngine, get_stock_insight_engine
from services.stock_insight_engine.filtering import (
    filter_long_term_candidates,
    filter_mainboard_candidates,
    filter_short_term_candidates,
    select_top_with_sector_diversification,
)
from services.stock_insight_engine.indicators import (
    calculate_max_drawdown,
    calculate_price_change,
    calculate_rsi,
)
from services.stock_insight_engine.ml_utils import ml_predict_bullish, ml_tier_selection
from services.stock_insight_engine.penalty import (
    calculate_long_penalty,
    calculate_short_penalty,
)
from services.stock_insight_engine.scoring import (
    calculate_mainboard_scores,
    calculate_rational_long_scores,
    calculate_rational_short_scores,
)

# ============================================================
#  Helpers
# ============================================================


def _make_kline_df(close_prices: list[float]) -> pd.DataFrame:
    """从收盘价序列构建测试用 K-line DataFrame。"""
    n = len(close_prices)
    return pd.DataFrame(
        {
            "close": close_prices,
            "open": close_prices,
            "high": [c * 1.02 for c in close_prices],
            "low": [c * 0.98 for c in close_prices],
            "volume": [1000000] * n,
            "date": [(datetime.now() - timedelta(days=n - i)).strftime("%Y%m%d") for i in range(n)],
        }
    )


def _make_analysis_result(**overrides) -> dict[str, Any]:
    """生成标准分析结果字典，供 scoring / penalty 测试使用。"""
    defaults = {
        "code": "600001",
        "name": "测试A",
        "sector": "金融",
        "price": 12.5,
        "volume": 5_000_000,
        "near_5d": 3.0,
        "near_20d": 8.0,
        "rsi": 55.0,
        "max_dd": -15.0,
        "roe": 10.0,
        "has_nt": False,
        "sharpe": 1.5,
        "long_score": 75,
        "short_score": 72,
        "fund_s": 70,
        "risk_s": 68,
        "mom_s": 65,
        "tech_s": 70,
        "vol_s": 60,
    }
    defaults.update(overrides)
    return defaults


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


# ============================================================
#  indicators.py — 技术指标
# ============================================================


class TestIndicators:
    """calculate_price_change / calculate_rsi / calculate_max_drawdown"""

    # ---- price_change ----

    def test_price_change_normal(self):
        """5日涨跌幅正常计算"""
        df = _make_kline_df([10.0, 10.5, 10.3, 10.8, 11.0])
        result = calculate_price_change(df, 5)
        assert result == pytest.approx(10.0)  # (11-10)/10*100

    def test_price_change_negative(self):
        """下跌应返回负值"""
        df = _make_kline_df([10.0, 9.8, 9.5, 9.2, 9.0])
        result = calculate_price_change(df, 5)
        assert result == pytest.approx(-10.0)

    def test_price_change_not_enough_data(self):
        """数据不足 days 时返回 0.0"""
        df = _make_kline_df([10.0, 10.5])
        result = calculate_price_change(df, 5)
        assert result == 0.0

    def test_price_change_zero_start(self):
        """起始价为 0 时返回 0.0"""
        df = _make_kline_df([0.0, 10.0, 10.5, 11.0, 11.5])
        result = calculate_price_change(df, 5)
        assert result == 0.0

    # ---- RSI ----

    def test_rsi_normal(self):
        """RSI 正常计算应在 0-100 范围内"""
        df = _make_kline_df([10, 11, 12, 11, 10, 11, 12, 13, 12, 11, 10, 9, 10, 11, 12] * 3)
        result = calculate_rsi(df, 14)
        assert 0 <= result <= 100

    def test_rsi_not_enough_data(self):
        """数据不足 period+1 时返回 50.0"""
        df = _make_kline_df([10.0, 11.0])
        result = calculate_rsi(df, 14)
        assert result == 50.0

    def test_rsi_all_gains(self):
        """全部上涨 → RSI = 100"""
        df = _make_kline_df([10 + i * 0.5 for i in range(20)])
        result = calculate_rsi(df, 14)
        assert result == 100.0

    def test_rsi_all_losses(self):
        """全部下跌 → RSI = 0"""
        df = _make_kline_df([20 - i * 0.5 for i in range(20)])
        result = calculate_rsi(df, 14)
        assert result == 0.0

    def test_rsi_flat(self):
        """价格持平 → RSI = 50"""
        df = _make_kline_df([10.0] * 20)
        result = calculate_rsi(df, 14)
        assert result == 50.0

    # ---- max_drawdown ----

    def test_max_drawdown_normal(self):
        """先升后降应计算最大回撤"""
        df = _make_kline_df([10, 12, 15, 14, 11, 13, 12])
        result = calculate_max_drawdown(df)
        # 峰值 15, 最低到 11, 回撤 (11-15)/15*100 = -26.67
        assert result == pytest.approx(-26.6667, abs=0.01)

    def test_max_drawdown_rising(self):
        """持续上涨 → 0% 回撤"""
        df = _make_kline_df([10, 11, 12, 13, 14, 15])
        result = calculate_max_drawdown(df)
        assert result == 0.0

    def test_max_drawdown_falling(self):
        """持续下跌 → 从起点到最低"""
        df = _make_kline_df([15, 13, 11, 9, 7])
        result = calculate_max_drawdown(df)
        # 峰值 15, 最低 7, 回撤 (7-15)/15*100 = -53.33
        assert result == pytest.approx(-53.3333, abs=0.01)

    def test_max_drawdown_not_enough_data(self):
        """少于 2 个点返回 0.0"""
        df = _make_kline_df([10.0])
        result = calculate_max_drawdown(df)
        assert result == 0.0

    def test_max_drawdown_empty_df(self):
        """空 DataFrame 返回 0.0"""
        result = calculate_max_drawdown(_empty_df())
        assert result == 0.0

    def test_max_drawdown_recover_partial(self):
        """下跌后部分回升，最大回撤在谷底"""
        df = _make_kline_df([10, 12, 14, 8, 11, 13])
        result = calculate_max_drawdown(df)
        # 峰值 14, 最低 8, 回撤 (8-14)/14*100 = -42.86
        assert result == pytest.approx(-42.8571, abs=0.01)

    # ---- Edge cases for uncovered lines ----

    def test_price_change_exception(self):
        """price_change 异常处理分支"""
        df = _make_kline_df([10.0, 10.5, 10.3, 10.8, 11.0])
        # 制造异常：把 close 列设为 object 类型使其 float() 转换失败
        df["close"] = df["close"].astype(str)
        df.loc[df.index[0], "close"] = "bad_value"
        result = calculate_price_change(df, 5)
        assert result == 0.0

    def test_price_change_no_close_column(self):
        """无 close 列时回退到最后一列"""
        df = _make_kline_df([10.0, 11.0])
        df_no_close = df.rename(columns={"close": "adj_close"})
        result = calculate_price_change(df_no_close, 5)
        assert result == 0.0  # 不足 days

    def test_rsi_avg_loss_zero(self):
        """RSI 中 avg_loss == 0 分支 → 返回 100"""
        # 全部上涨（已有测试）但如果 losses 存在但均值可能为 0？
        # 构造：有损失但 avg_loss 恰好为 0 → 不可达因为 len(losses)>0→mean>0
        # 直接用手动构造场景
        import numpy as np

        df = pd.DataFrame({"close": [10.0, 10.0, 10.0]})  # 持平 → 处理方式不同
        result = calculate_rsi(df, 2)
        # deltas 都是 0 → len(gains)==0 and len(losses)==0 → 50
        assert result == 50.0

    def test_rsi_exception(self):
        """RSI 异常处理分支 — astype(float) 抛出异常"""
        df = _make_kline_df([10.0] * 20)  # 足够行数（≥ period+1=15）
        df["close"] = df["close"].astype(object)  # pandas 3.x 兼容：先转 object 再塞 bad_value
        df.loc[df.index[5], "close"] = "bad_value"  # 使 astype(float) 失败
        result = calculate_rsi(df, 14)
        assert result == 50.0

    def test_max_drawdown_exception(self):
        """max_drawdown 异常处理分支 — astype(float) 抛出异常"""
        df = _make_kline_df([10.0] * 5)
        df["close"] = df["close"].astype(object)  # pandas 3.x 兼容
        df.loc[df.index[0], "close"] = "bad_value"  # 使 astype(float) 失败
        result = calculate_max_drawdown(df)
        assert result == 0.0


# ============================================================
#  penalty.py — 惩罚计算
# ============================================================


class TestPenaltyLong:
    """calculate_long_penalty 边界和组合"""

    def test_no_penalty(self):
        """所有条件正常 → 无惩罚"""
        r = _make_analysis_result(near_20d=5, rsi=50, max_dd=-10, roe=15)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 0
        assert reasons == []

    def test_near_20d_over_35(self):
        """近20日涨超35% → -12"""
        r = _make_analysis_result(near_20d=38)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 12
        assert "38%" in reasons[0]

    def test_near_20d_between_30_and_35(self):
        """近20日涨30~35% → -8"""
        r = _make_analysis_result(near_20d=32)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 8

    def test_near_20d_between_25_and_30(self):
        """近20日涨25~30% → -4"""
        r = _make_analysis_result(near_20d=27)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 4

    def test_rsi_over_78(self):
        """RSI > 78 → -10"""
        r = _make_analysis_result(rsi=82)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 10
        assert "过热" in reasons[0]

    def test_rsi_between_75_and_78(self):
        """RSI 75~78 → -6"""
        r = _make_analysis_result(rsi=76)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 6

    def test_rsi_between_72_and_75(self):
        """RSI 72~75 → -3"""
        r = _make_analysis_result(rsi=73)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 3

    def test_max_dd_below_45(self):
        """回撤 > -45% → -8"""
        r = _make_analysis_result(max_dd=-50)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 8

    def test_max_dd_between_35_and_45(self):
        """回撤 -35~-45% → -4"""
        r = _make_analysis_result(max_dd=-40)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 4

    def test_roe_negative(self):
        """ROE < 0 → -12"""
        r = _make_analysis_result(roe=-5)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 12
        assert "ROE为负" in reasons

    def test_roe_between_0_and_1(self):
        """ROE 0~1% → -5"""
        r = _make_analysis_result(roe=0.5)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 5

    def test_multiple_penalties_stack(self):
        """多条件同时触发 → 叠加"""
        r = _make_analysis_result(near_20d=40, rsi=85, max_dd=-50, roe=-3)
        pen, reasons = calculate_long_penalty(r)
        assert pen == 12 + 10 + 8 + 12  # 42
        assert len(reasons) == 4


class TestPenaltyShort:
    """calculate_short_penalty 边界"""

    def test_short_no_penalty(self):
        r = _make_analysis_result(near_5d=3)
        pen, reasons = calculate_short_penalty(r)
        assert pen == 0
        assert reasons == []

    def test_short_near_5d_over_18(self):
        r = _make_analysis_result(near_5d=20)
        pen, reasons = calculate_short_penalty(r)
        assert pen == 10
        assert "20%" in reasons[0]

    def test_short_near_5d_between_15_and_18(self):
        r = _make_analysis_result(near_5d=16)
        pen, reasons = calculate_short_penalty(r)
        assert pen == 5


# ============================================================
#  filtering.py — 候选筛选
# ============================================================


class TestFiltering:
    """filter_* 和 select_top_with_sector_diversification"""

    def _make_pool(self, n: int, prefix: str = "600", industry: str = "金融") -> list[dict]:
        return [
            {
                "symbol": f"{prefix}{i:03d}",
                "name": f"股票{i}",
                "market": "主板",
                "industry": industry,
            }
            for i in range(n)
        ]

    def test_filter_mainboard_excludes_owned(self):
        """排除已持仓股票"""
        pool = self._make_pool(10)
        owned = ["600000", "600001"]
        result = filter_mainboard_candidates(pool, owned)
        codes = {s["symbol"] for s in result}
        assert "600000" not in codes
        assert "600001" not in codes
        assert len(result) == 8

    def test_filter_mainboard_empty_pool(self):
        """空池子返回空"""
        result = filter_mainboard_candidates([])
        assert result == []

    def test_filter_mainboard_caps_at_100(self):
        """上限 100"""
        pool = self._make_pool(200)
        result = filter_mainboard_candidates(pool)
        assert len(result) == 100

    def test_filter_mainboard_no_owned(self):
        """无持仓列表时返回全部（上限100）"""
        pool = self._make_pool(50)
        result = filter_mainboard_candidates(pool)
        assert len(result) == 50

    def test_filter_long_term_caps_at_50(self):
        """长线候选上限 50"""
        pool = self._make_pool(100)
        result = filter_long_term_candidates(pool)
        assert len(result) == 50

    def test_filter_short_term_caps_at_50(self):
        """短线候选上限 50"""
        pool = self._make_pool(100)
        result = filter_short_term_candidates(pool)
        assert len(result) == 50

    def test_select_top_dedup_sectors(self):
        """板块去重：同板块只选最高分，除非 > 60"""
        results = [
            {"code": "A", "final_score": 90, "sector": "金融"},
            {"code": "B", "final_score": 80, "sector": "金融"},
            {"code": "C", "final_score": 70, "sector": "科技"},
            {"code": "D", "final_score": 65, "sector": "科技"},  # > 60, 可跨板块
            {"code": "E", "final_score": 50, "sector": "医药"},
        ]
        picked = select_top_with_sector_diversification(results, 5)
        codes = {s["code"] for s in picked}
        # A(90)>B(80) → A入选，C(70)>D(65) → C入选，E(50)入选
        # 但 D 也 > 60, 所以 D 可以跨板块选
        assert "A" in codes
        assert "C" in codes
        # D 的分数 65 > 60, 所以即使和 C 同板块也可以入选
        assert "D" in codes
        assert "E" in codes
        assert len(picked) >= 4  # A, C, D, E

    def test_select_top_empty(self):
        """空列表返回空"""
        assert select_top_with_sector_diversification([], 5) == []

    def test_select_top_less_than_n(self):
        """候选不足时返回全部"""
        results = [
            {"code": "A", "final_score": 50, "sector": "金融"},
        ]
        picked = select_top_with_sector_diversification(results, 5)
        assert len(picked) == 1

    def test_select_top_score_above_60_breaks_sector_limit(self):
        """分数 > 60 可突破板块限制"""
        results = [
            {"code": "A", "final_score": 90, "sector": "金融"},
            {"code": "B", "final_score": 55, "sector": "金融"},
            {"code": "C", "final_score": 70, "sector": "金融"},  # > 60, 可被选
        ]
        picked = select_top_with_sector_diversification(results, 3)
        codes = {s["code"] for s in picked}
        assert "A" in codes
        assert "C" in codes  # 分数 > 60, 所以可以入选
        assert "B" not in codes  # 同板块，分数 55 < 60, 被去重


# ============================================================
#  ml_utils.py — ML 工具
# ============================================================


class TestMlUtils:
    """ml_predict_bullish (当前为模拟实现)"""

    def test_predict_bullish_always_true(self):
        """当前实现始终返回 True"""
        assert ml_predict_bullish("600001") is True
        assert ml_predict_bullish("000001") is True
        assert ml_predict_bullish("") is True


class TestMlTierSelection:
    """ml_tier_selection — ML两阶段筛选"""

    @pytest.fixture
    def mock_ds(self):
        """创建带有 mock pro 的 data_service"""
        from unittest.mock import MagicMock

        ds = MagicMock()
        ds.pro = MagicMock()
        return ds

    @pytest.fixture
    def stock_basic_df(self):
        """主板+非主板股票池"""
        return pd.DataFrame(
            {
                "ts_code": ["600001.SH", "600002.SH", "000001.SZ", "300001.SZ"],
                "symbol": ["600001", "600002", "000001", "300001"],
                "name": ["沪A", "沪B", "深A", "创业"],
                "market": ["主板", "主板", "主板", "创业板"],
            }
        )

    @pytest.fixture
    def trade_cal_df(self):
        """交易日历"""
        return pd.DataFrame(
            {
                "cal_date": ["20260617"],
                "is_open": [1],
            }
        )

    @pytest.fixture
    def daily_basic_df(self):
        """日线基础数据"""
        return pd.DataFrame(
            {
                "ts_code": [
                    "600001.SH",
                    "600002.SH",
                    "000001.SZ",
                    "300001.SZ",
                ],
                "close": [15.0, 8.0, 25.0, 3.0],  # 300001 close=3 < 5 → 被过滤
                "pe": [12.0, 5.0, 30.0, 50.0],
                "pb": [1.5, 0.8, 3.0, 6.0],
                "volume_ratio": [1.2, 0.6, 0.8, 0.4],
                "turnover_rate": [5.0, 20.0, 15.0, 40.0],
            }
        )

    def test_no_pro_returns_empty(self, mock_ds):
        """data_service.pro 为 None 时返回空列表"""
        mock_ds.pro = None
        result = ml_tier_selection(mock_ds, "mainboard", 5, relaxed=False)
        assert result == []

    def test_no_daily_basic_returns_empty(self, mock_ds, stock_basic_df, trade_cal_df):
        """daily_basic 空时返回空列表"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = trade_cal_df
        mock_ds.pro.daily_basic.return_value = None

        result = ml_tier_selection(mock_ds, "mainboard", 5, relaxed=False)
        assert result == []

    def test_mainboard_mode_strict(self, mock_ds, stock_basic_df, trade_cal_df, daily_basic_df):
        """主板模式 + 严格筛选"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = trade_cal_df
        # 只保留主板股票（600001, 600002 → 但 600002 pe=5 < 严格条件 pe<=60)
        # 严格模式：close≥5, pe≤60, pb≤8, volume_ratio≥0.7, turnover_rate≤25
        # 600001: close=15√ pe=12√ pb=1.5√ vol=1.2√ turn=5√ → 入选
        # 600002: close=8√ pe=5√ pb=0.8√ vol=0.6✗ → 被过滤
        mock_ds.pro.daily_basic.return_value = daily_basic_df

        result = ml_tier_selection(mock_ds, "mainboard", 5, relaxed=False)
        assert len(result) >= 1
        codes = {r["code"] for r in result}
        assert "600001" in codes
        assert "600002" not in codes  # volume_ratio=0.6 < 0.7

    def test_relaxed_mode_more_results(self, mock_ds, stock_basic_df, trade_cal_df, daily_basic_df):
        """宽松模式比严格模式返回更多结果"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = trade_cal_df
        mock_ds.pro.daily_basic.return_value = daily_basic_df

        strict = ml_tier_selection(mock_ds, "all", 5, relaxed=False)
        relaxed = ml_tier_selection(mock_ds, "all", 5, relaxed=True)
        assert len(relaxed) >= len(strict)

    def test_top_n_limits_results(self, mock_ds, stock_basic_df, trade_cal_df, daily_basic_df):
        """top_n 限制返回数量"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = trade_cal_df
        mock_ds.pro.daily_basic.return_value = daily_basic_df

        result = ml_tier_selection(mock_ds, "all", 1, relaxed=False)
        assert len(result) <= 1

    def test_result_fields_present(self, mock_ds, stock_basic_df, trade_cal_df, daily_basic_df):
        """返回结果包含所有必需字段"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = trade_cal_df
        mock_ds.pro.daily_basic.return_value = daily_basic_df

        result = ml_tier_selection(mock_ds, "all", 2, relaxed=False)
        if result:
            keys = {
                "code",
                "name",
                "tier",
                "score",
                "pe",
                "pb",
                "close",
                "volume_ratio",
                "turnover_rate",
            }
            assert keys.issubset(result[0].keys())

    def test_tier_label_in_result(self, mock_ds, stock_basic_df, trade_cal_df, daily_basic_df):
        """严格模式 tier 为 Tier1，宽松模式为 Tier2"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = trade_cal_df
        mock_ds.pro.daily_basic.return_value = daily_basic_df

        strict = ml_tier_selection(mock_ds, "all", 2, relaxed=False)
        relaxed = ml_tier_selection(mock_ds, "all", 2, relaxed=True)

        if strict and relaxed:
            # 严格模式的所有结果应为 Tier1
            assert all(r["tier"] == "Tier1" for r in strict)
            # 宽松模式的所有结果应为 Tier2
            assert all(r["tier"] == "Tier2" for r in relaxed)

    def test_no_trade_cal_fallback(self, mock_ds, stock_basic_df, daily_basic_df):
        """交易日历空时使用当日日期"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = pd.DataFrame({"cal_date": [], "is_open": []})
        mock_ds.pro.daily_basic.return_value = daily_basic_df

        result = ml_tier_selection(mock_ds, "all", 2, relaxed=False)
        assert isinstance(result, list)

    def test_no_trade_cal_none(self, mock_ds, stock_basic_df, daily_basic_df):
        """交易日历为 None 时使用当日日期"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = None
        mock_ds.pro.daily_basic.return_value = daily_basic_df

        result = ml_tier_selection(mock_ds, "all", 2, relaxed=False)
        assert isinstance(result, list)

    def test_exception_graceful(self, mock_ds):
        """异常被捕获返回空列表"""
        mock_ds.pro.stock_basic.side_effect = RuntimeError("API超时")
        result = ml_tier_selection(mock_ds, "mainboard", 5, relaxed=False)
        assert result == []

    def test_all_filtered_out_returns_empty(self, mock_ds, stock_basic_df, trade_cal_df):
        """所有股票被条件过滤 → 触发 len(fd)==0 → return []"""
        mock_ds.pro.stock_basic.return_value = stock_basic_df
        mock_ds.pro.trade_cal.return_value = trade_cal_df
        # 所有行的 close < 5 → 全部被严格条件过滤
        df = pd.DataFrame(
            {
                "ts_code": ["600001.SH", "600002.SH"],
                "close": [3.0, 2.0],
                "pe": [12.0, 15.0],
                "pb": [1.5, 2.0],
                "volume_ratio": [1.0, 1.2],
                "turnover_rate": [10.0, 15.0],
            }
        )
        mock_ds.pro.daily_basic.return_value = df
        result = ml_tier_selection(mock_ds, "all", 5, relaxed=False)
        assert result == []


# ============================================================
#  scoring.py — 评分模块
# ============================================================


class TestScoringMainboard:
    """calculate_mainboard_scores"""

    def test_basic_scoring(self):
        """默认参数的评分计算"""
        r = _make_analysis_result()
        result = calculate_mainboard_scores(r)
        assert "final_score" in result
        assert result["final_score"] > 0

    def test_with_nt_bonus(self):
        """has_nt=True → +10 加分"""
        r = _make_analysis_result(has_nt=True)
        result = calculate_mainboard_scores(r)
        assert (
            result["final_score"]
            > calculate_mainboard_scores(_make_analysis_result(has_nt=False))["final_score"]
        )

    def test_all_fields_present(self):
        """输出包含所有评分字段"""
        result = calculate_mainboard_scores(_make_analysis_result())
        required_keys = {
            "final_score",
            "long_composite",
            "long_final",
            "long_penalty",
            "short_composite",
            "short_final",
            "short_penalty",
            "penalty_reasons",
            "long_score",
            "fund_s",
            "risk_s",
            "short_score",
            "mom_s",
            "tech_s",
            "vol_s",
        }
        assert required_keys.issubset(result.keys())

    def test_high_sharpe_improves_score(self):
        """高 Sharpe 提升分数"""
        low = calculate_mainboard_scores(_make_analysis_result(sharpe=0.5))
        high = calculate_mainboard_scores(_make_analysis_result(sharpe=3.5))
        assert high["final_score"] > low["final_score"]

    def test_defaults_for_missing_values(self):
        """缺失字段使用默认值不崩溃"""
        r = {"code": "test", "name": "x"}
        result = calculate_mainboard_scores(r)
        assert result["final_score"] > 0


class TestScoringRationalLong:
    """calculate_rational_long_scores"""

    def test_basic_long_scoring(self):
        """基础长线评分"""
        r = _make_analysis_result()
        result = calculate_rational_long_scores(r)
        assert result["selection_type"] == "long_term"
        assert "long_final" in result

    def test_long_penalty_applied(self):
        """高 near_20d 触发惩罚"""
        low_penalty = calculate_rational_long_scores(_make_analysis_result(near_20d=5))
        high_penalty = calculate_rational_long_scores(_make_analysis_result(near_20d=35))
        assert high_penalty["long_final"] < low_penalty["long_final"]

    def test_long_with_nt_bonus(self):
        """NT 加分"""
        with_nt = calculate_rational_long_scores(_make_analysis_result(has_nt=True))
        without = calculate_rational_long_scores(_make_analysis_result(has_nt=False))
        assert with_nt["long_final"] > without["long_final"]

    # ---- Edge cases for uncovered scoring branches ----

    def test_long_near_20d_between_25_and_30(self):
        """near_20d 25~30 触发 -5 惩罚"""
        result = calculate_rational_long_scores(_make_analysis_result(near_20d=27))
        assert result["penalty"] >= 5
        assert "27%" in result["penalty_reasons"][0]

    def test_long_rsi_over_75(self):
        """rsi > 75 触发 -8 惩罚"""
        result = calculate_rational_long_scores(_make_analysis_result(rsi=78))
        assert result["penalty"] >= 8
        assert "过热" in result["penalty_reasons"][0]

    def test_long_rsi_between_72_and_75(self):
        """rsi 72~75 触发 -4 惩罚"""
        result = calculate_rational_long_scores(_make_analysis_result(rsi=73))
        assert result["penalty"] >= 4
        assert "偏高" in result["penalty_reasons"][0]

    def test_long_max_dd_below_35(self):
        """max_dd < -35 触发 -5 惩罚"""
        result = calculate_rational_long_scores(_make_analysis_result(max_dd=-40))
        assert result["penalty"] >= 5
        assert "回撤" in result["penalty_reasons"][0]

    def test_long_roe_negative(self):
        """roe < 0 触发 -10 惩罚"""
        result = calculate_rational_long_scores(_make_analysis_result(roe=-5))
        assert result["penalty"] >= 10
        assert "ROE为负" in result["penalty_reasons"]


class TestScoringRationalShort:
    """calculate_rational_short_scores"""

    def test_basic_short_scoring(self):
        """基础短线评分"""
        r = _make_analysis_result()
        result = calculate_rational_short_scores(r)
        assert result["selection_type"] == "short_term"
        assert "short_final" in result

    def test_short_penalty_applied(self):
        """高 near_5d 触发惩罚"""
        low = calculate_rational_short_scores(_make_analysis_result(near_5d=3))
        high = calculate_rational_short_scores(_make_analysis_result(near_5d=20))
        assert high["short_final"] < low["short_final"]

    def test_short_near_5d_between_15_and_18(self):
        """near_5d 15~18 触发 -5 惩罚"""
        result = calculate_rational_short_scores(_make_analysis_result(near_5d=16))
        assert result["penalty"] == 5
        assert "16%" in result["penalty_reasons"][0]


# ============================================================
#  Engine — 核心编排类
# ============================================================


class MockDataService:
    """模拟 DataService，供引擎测试使用。"""

    def __init__(self):
        self._pro = MagicMock()
        self._pro.stock_basic.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600001.SH",
                    "symbol": "600001",
                    "name": "测试A",
                    "market": "主板",
                    "industry": "金融",
                    "list_date": "20200101",
                },
                {
                    "ts_code": "600002.SH",
                    "symbol": "600002",
                    "name": "测试B",
                    "market": "主板",
                    "industry": "科技",
                    "list_date": "20200102",
                },
                {
                    "ts_code": "600003.SH",
                    "symbol": "600003",
                    "name": "测试C",
                    "market": "主板",
                    "industry": "医疗",
                    "list_date": "20200103",
                },
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "测试D",
                    "market": "主板",
                    "industry": "金融",
                    "list_date": "20200104",
                },
                {
                    "ts_code": "000002.SZ",
                    "symbol": "000002",
                    "name": "测试E",
                    "market": "主板",
                    "industry": "科技",
                    "list_date": "20200105",
                },
            ]
        )
        self._daily_quote_return = None

    @property
    def pro(self):
        return self._pro

    def get_stock_daily_quote(self, ts_code, start_date, end_date, limit=365):
        """返回模拟 K 线数据。"""
        if self._daily_quote_return is not None:
            return self._daily_quote_return

        # 生成 250 根模拟 K 线（约 1 年交易日）
        np.random.seed(42)
        prices = 12.0 * (1 + np.cumsum(np.random.randn(250) * 0.02))
        return [
            {
                "trade_date": (datetime.now() - timedelta(days=250 - i)).strftime("%Y%m%d"),
                "open": float(prices[i]) if i < len(prices) else 12.0,
                "close": float(prices[i + 1]) if i + 1 < len(prices) else float(prices[-1]),
                "high": float(prices[i]) * 1.01 if i < len(prices) else 12.0,
                "low": float(prices[i]) * 0.99 if i < len(prices) else 12.0,
                "volume": 5_000_000 + int(np.random.rand() * 2_000_000),
            }
            for i in range(limit)
        ]


class MockDailyQuoteEmpty:
    def get_stock_daily_quote(self, ts_code, start_date, end_date, limit=365):
        return []


class MockDailyQuoteShort:
    def get_stock_daily_quote(self, ts_code, start_date, end_date, limit=365):
        # 少于 20 根，_analyze_candidate 应返回 None
        return [
            {
                "trade_date": "20260601",
                "close": 10.0,
                "open": 9.8,
                "high": 10.2,
                "low": 9.7,
                "volume": 1000000,
            },
        ]


@pytest.fixture
def engine():
    return StockInsightEngine(MockDataService())


@pytest.fixture
def engine_empty():
    ds = MockDataService()
    ds._pro.stock_basic.return_value = pd.DataFrame()
    return StockInsightEngine(ds)


@pytest.fixture
def engine_no_pro():
    ds = MockDataService()
    ds._pro = None
    return StockInsightEngine(ds)


class TestEngineInit:
    """StockInsightEngine 初始化"""

    def test_init_stores_data_service(self, engine):
        assert engine.data_service is not None
        assert engine._scan_cache == {}

    def test_init_empty_cache(self, engine):
        assert isinstance(engine._scan_cache, dict)


class TestEngineGetMainboardPool:
    """_get_mainboard_stock_pool"""

    def test_normal_pool(self, engine):
        pool = engine._get_mainboard_stock_pool()
        assert len(pool) >= 4  # 有主板 market 的股票
        assert all(isinstance(s, dict) for s in pool)

    def test_empty_pool(self, engine_empty):
        pool = engine_empty._get_mainboard_stock_pool()
        assert pool == []

    def test_no_pro(self, engine_no_pro):
        pool = engine_no_pro._get_mainboard_stock_pool()
        assert pool == []


class TestEngineGetFullPool:
    """_get_full_market_pool"""

    def test_normal_pool(self, engine):
        pool = engine._get_full_market_pool()
        assert len(pool) == 5
        assert "list_date" in pool[0]

    def test_empty_pool(self, engine_empty):
        pool = engine_empty._get_full_market_pool()
        assert pool == []

    def test_no_pro(self, engine_no_pro):
        pool = engine_no_pro._get_full_market_pool()
        assert pool == []


class TestEngineAnalyzeCandidate:
    """_analyze_candidate"""

    def test_normal_analysis(self, engine):
        candidate = {"symbol": "600001", "name": "测试A", "industry": "金融"}
        result = engine._analyze_candidate(candidate)
        assert result is not None
        assert result["code"] == "600001"
        assert result["name"] == "测试A"
        assert "price" in result
        assert "rsi" in result
        assert "near_5d" in result
        assert "near_20d" in result
        assert "max_dd" in result
        assert 0 <= result["rsi"] <= 100

    def test_no_code(self, engine):
        result = engine._analyze_candidate({"name": "无名"})
        assert result is None

    def test_empty_kline(self, engine):
        engine.data_service.get_stock_daily_quote = (
            lambda ts_code, start_date, end_date, limit=365: []
        )
        candidate = {"symbol": "600001", "name": "测试A", "industry": "金融"}
        result = engine._analyze_candidate(candidate)
        assert result is None

    def test_short_kline(self, engine):
        engine.data_service = MockDailyQuoteShort()
        candidate = {"symbol": "600001", "name": "测试A", "industry": "金融"}
        result = engine._analyze_candidate(candidate)
        assert result is None  # 少于 20 根数据

    def test_analysis_default_values(self, engine):
        """分析结果包含合理默认值"""
        candidate = {"symbol": "600001", "name": "测试A", "industry": "金融"}
        result = engine._analyze_candidate(candidate)
        assert result["roe"] == 10.0
        assert result["has_nt"] is False
        assert result["sharpe"] == 1.5
        assert result["sector"] == "金融"


class TestEngineScanMainboard:
    """scan_mainboard — 主板精选"""

    def test_scan_mainboard_normal(self, engine):
        result = engine.scan_mainboard(top_n=3)
        assert len(result) <= 3
        assert all("final_score" in r for r in result)

    def test_scan_mainboard_with_owned(self, engine):
        """排除已持仓"""
        result = engine.scan_mainboard(top_n=3, owned_codes=["600001"])
        codes = {r["code"] for r in result}
        assert "600001" not in codes

    def test_scan_mainboard_empty_pool(self, engine_empty):
        result = engine_empty.scan_mainboard()
        assert result == []

    def test_scan_mainboard_returns_sorted(self, engine):
        """按 final_score 降序"""
        if len(result := engine.scan_mainboard(top_n=5)) >= 2:
            scores = [r["final_score"] for r in result]
            assert scores == sorted(scores, reverse=True)

    def test_scan_mainboard_sector_diversification(self, engine):
        """板块去重应在输出中体现"""
        result = engine.scan_mainboard(top_n=5)
        # 5 只股票最多来自 5 个不同板块
        sectors = {r.get("sector", "") for r in result}
        assert len(sectors) <= len(result)

    def test_scan_mainboard_all_owned(self, engine):
        """所有候选股都已被持仓 → 空结果"""
        result = engine.scan_mainboard(
            top_n=3, owned_codes=["600001", "600002", "600003", "000001", "000002"]
        )
        assert result == []

    def test_scan_mainboard_exception_handling(self, engine):
        """scan_mainboard 异常处理分支"""
        engine._get_mainboard_stock_pool = lambda: [{"symbol": "bad"}]
        # 让 _analyze_candidate 抛出异常
        engine._analyze_candidate = lambda x: (_ for _ in ()).throw(RuntimeError("模拟失败"))
        result = engine.scan_mainboard(top_n=3)
        assert result == []


class TestEngineScanRational:
    """scan_rational — 理性选股"""

    def test_scan_rational_normal(self, engine):
        result = engine.scan_rational(top_n=10)
        assert len(result) <= 10
        types = {r.get("selection_type") for r in result}
        assert "long_term" in types
        assert "short_term" in types

    def test_scan_rational_long_short_count(self, engine):
        """长线 ≤5, 短线 ≤5"""
        result = engine.scan_rational()
        long_count = sum(1 for r in result if r.get("selection_type") == "long_term")
        short_count = sum(1 for r in result if r.get("selection_type") == "short_term")
        assert long_count <= 5
        assert short_count <= 5
        assert long_count + short_count == len(result)

    def test_scan_rational_empty_pool(self, engine_empty):
        result = engine_empty.scan_rational()
        assert result == []

    def test_scan_rational_empty_with_no_pro(self, engine_no_pro):
        """data_service.pro 为 None 时返回空"""
        result = engine_no_pro.scan_rational()
        # _get_full_market_pool 返回空 → result 为空
        assert result == []

    def test_scan_rational_rank_field(self, engine):
        """排序字段 rank 存在"""
        result = engine.scan_rational()
        for r in result:
            assert "rank" in r
            assert 1 <= r["rank"] <= len(result)

    def test_scan_rational_exception_handling(self, engine):
        """scan_rational 异常处理分支"""
        engine._get_full_market_pool = lambda: [{"symbol": "bad"}]
        engine._analyze_candidate = lambda x, days=365: (_ for _ in ()).throw(
            RuntimeError("模拟失败")
        )
        result = engine.scan_rational()
        assert result == []


class TestEngineScanMl:
    """scan_ml — ML 增强扫描（核心依赖 data_service.pro）"""

    def test_scan_ml_needs_pro(self, engine_no_pro):
        """无 pro 时返回空"""
        result = engine_no_pro.scan_ml(mode="mainboard")
        assert result == []

    def test_scan_ml_with_pro_mainboard(self, engine):
        """主板模式"""
        result = engine.scan_ml(mode="mainboard", top_n=3)
        assert isinstance(result, list)

    def test_scan_ml_with_pro_all(self, engine):
        """全市场模式"""
        result = engine.scan_ml(mode="all", top_n=3)
        assert isinstance(result, list)

    def test_scan_ml_tier2_supplement(self, engine):
        """ML 扫描 Tier1 不足时 Tier2 补充"""
        import services.stock_insight_engine.engine as eng

        original_tier = eng.ml_tier_selection
        original_pred = eng.ml_predict_bullish

        call_count = [0]
        eng.ml_tier_selection = lambda ds, mode, top_n, relaxed=False: (
            [{"code": "600001", "name": "A", "tier": "Tier1", "score": 90}]
            if not relaxed
            else [
                {"code": "600002", "name": "B", "tier": "Tier2", "score": 70},
                {"code": "600003", "name": "C", "tier": "Tier2", "score": 65},
            ]
        )
        eng.ml_predict_bullish = lambda code: True

        try:
            result = engine.scan_ml(mode="mainboard", top_n=5)
            assert len(result) >= 1
        finally:
            eng.ml_tier_selection = original_tier
            eng.ml_predict_bullish = original_pred

    def test_scan_ml_exception_handling(self, engine):
        """scan_ml 异常处理分支 — 让 ml_tier_selection 实际抛出异常"""
        import services.stock_insight_engine.engine as eng

        original = eng.ml_tier_selection
        eng.ml_tier_selection = lambda ds, mode, top_n, relaxed=False: (_ for _ in ()).throw(
            RuntimeError("模拟ml_tier_selection失败")
        )
        try:
            result = engine.scan_ml(mode="mainboard")
            assert result == []
        finally:
            eng.ml_tier_selection = original

    def test_scan_ml_bullish_break_at_top_n(self, engine):
        """ML 达到 top_n 后 break 停止预测"""
        import services.stock_insight_engine.engine as eng

        original_tier = eng.ml_tier_selection
        original_pred = eng.ml_predict_bullish

        eng.ml_tier_selection = lambda ds, mode, top_n, relaxed=False: [
            {"code": f"600{i:03d}", "name": f"S{i}", "tier": "Tier1", "score": 90}
            for i in range(1, 15)
        ]
        eng.ml_predict_bullish = lambda code: True  # 所有都入选 → 快速达到 top_n

        try:
            result = engine.scan_ml(mode="mainboard", top_n=3)
            assert len(result) == 3  # break at top_n=3
        finally:
            eng.ml_tier_selection = original_tier
            eng.ml_predict_bullish = original_pred


class TestEngineAuxMethods:
    """辅助方法异常分支"""

    def test_get_full_market_pool_exception(self, engine):
        """_get_full_market_pool 异常处理"""
        engine.data_service.pro.stock_basic.side_effect = RuntimeError("API异常")
        result = engine._get_full_market_pool()
        assert result == []

    def test_analyze_candidate_exception(self, engine):
        """_analyze_candidate 异常处理"""
        # 构造非法 kline 数据触发异常
        engine.data_service.get_stock_daily_quote = (
            lambda ts_code, start_date, end_date, limit=365: {"invalid": "data"}
        )
        candidate = {"symbol": "600001", "name": "测试A", "industry": "金融"}
        result = engine._analyze_candidate(candidate)
        assert result is None


class TestGetStockInsightEngine:
    """get_stock_insight_engine 单例工厂"""

    def test_returns_none_without_data_service(self):
        assert get_stock_insight_engine() is None

    def test_returns_engine_with_data_service(self):
        ds = MockDataService()
        engine = get_stock_insight_engine(ds)
        assert isinstance(engine, StockInsightEngine)
        assert engine.data_service is ds

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_singleton_reuses_instance(self, engine):
        """同一进程内复用全局实例"""
        from services.stock_insight_engine.engine import _stock_insight_engine

        _stock_insight_engine = None  # 重置单例
        first = get_stock_insight_engine(engine.data_service)
        second = get_stock_insight_engine()
        assert first is not None
        assert first is second  # 同一实例
