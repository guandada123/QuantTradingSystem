"""
Stock Insight 选股引擎 - 核心类
封装三个核心算法：主板精选、理性10选股、ML增强扫描
内部委托同目录子模块
"""

from datetime import datetime, timedelta
import logging
from typing import Any

import pandas as pd

from .filtering import (
    filter_long_term_candidates,
    filter_mainboard_candidates,
    filter_short_term_candidates,
    select_top_with_sector_diversification,
)
from .indicators import (
    calculate_max_drawdown,
    calculate_price_change,
    calculate_rsi,
)
from .ml_utils import (
    ml_predict_bullish,
    ml_tier_selection,
)
from .scoring import (
    calculate_mainboard_scores,
    calculate_rational_long_scores,
    calculate_rational_short_scores,
)

logger = logging.getLogger(__name__)


class StockInsightEngine:
    """
    Stock Insight 选股引擎

    基于 stock_insight 项目的三个核心算法：
    1. pick5_mainboard.py - 主板精选（惩罚机制+板块去重）
    2. rational_10.py - 理性10选股（长线5只+短线5只评分）
    3. ml_scan.py - ML集成预测（两阶段回退筛选）
    """

    def __init__(self, data_service):
        """
        初始化选股引擎

        Args:
            data_service: DataService 实例，用于获取数据
        """
        self.data_service = data_service
        self._scan_cache = {}

    def scan_mainboard(
        self, top_n: int = 10, owned_codes: list[str] = None
    ) -> list[dict[str, Any]]:
        """
        主板精选选股（基于 pick5_mainboard.py）

        Args:
            top_n: 返回股票数量
            owned_codes: 已持仓代码列表

        Returns:
            List[Dict]: 精选股票列表
        """
        logger.info(f"开始主板精选选股，目标数量: {top_n}")

        try:
            stock_pool = self._get_mainboard_stock_pool()
            if not stock_pool:
                logger.warning("主板股票池为空")
                return []

            candidates = filter_mainboard_candidates(stock_pool, owned_codes)
            if not candidates:
                logger.warning("基础筛选后无候选股票")
                return []

            all_results = []
            for candidate in candidates[:40]:
                analysis_result = self._analyze_candidate(candidate)
                if analysis_result:
                    scored_result = calculate_mainboard_scores(analysis_result)
                    all_results.append(scored_result)

            selected = select_top_with_sector_diversification(all_results, top_n)

            logger.info(f"主板精选完成，选中 {len(selected)} 只股票")
            return selected

        except Exception as e:
            logger.error(f"主板精选选股失败: {e}")
            return []

    def scan_rational(self, top_n: int = 10) -> list[dict[str, Any]]:
        """
        理性10选股（基于 rational_10.py）

        Args:
            top_n: 返回股票总数（默认10，长线5+短线5）

        Returns:
            List[Dict]: 选股结果
        """
        logger.info(f"开始理性选股，目标数量: {top_n}")

        try:
            stock_pool = self._get_full_market_pool()
            if not stock_pool:
                logger.warning("全市场股票池为空")
                return []

            # 长线
            long_term_candidates = filter_long_term_candidates(stock_pool)
            long_term_results = []
            for candidate in long_term_candidates[:25]:
                analysis_result = self._analyze_candidate(candidate, days=365)
                if analysis_result:
                    scored_result = calculate_rational_long_scores(analysis_result)
                    long_term_results.append(scored_result)

            long_term_results.sort(key=lambda x: x.get("long_final", 0), reverse=True)
            long_selected = long_term_results[: min(5, len(long_term_results))]

            # 短线
            short_term_candidates = filter_short_term_candidates(stock_pool)
            short_term_results = []
            for candidate in short_term_candidates[:25]:
                analysis_result = self._analyze_candidate(candidate, days=120)
                if analysis_result:
                    scored_result = calculate_rational_short_scores(analysis_result)
                    short_term_results.append(scored_result)

            short_term_results.sort(key=lambda x: x.get("short_final", 0), reverse=True)
            short_selected = short_term_results[: min(5, len(short_term_results))]

            # 合并
            result = []
            for i, stock in enumerate(long_selected):
                stock["selection_type"] = "long_term"
                stock["rank"] = i + 1
                result.append(stock)
            for i, stock in enumerate(short_selected):
                stock["selection_type"] = "short_term"
                stock["rank"] = i + 1
                result.append(stock)

            logger.info(f"理性选股完成，长线{len(long_selected)}只，短线{len(short_selected)}只")
            return result

        except Exception as e:
            logger.error(f"理性选股失败: {e}")
            return []

    def scan_ml(self, mode: str = "mainboard", top_n: int = 10) -> list[dict[str, Any]]:
        """
        ML增强扫描（基于 ml_scan.py）

        Args:
            mode: 扫描模式，"mainboard" 或 "all"
            top_n: 返回股票数量

        Returns:
            List[Dict]: ML筛选股票列表
        """
        logger.info(f"开始ML增强扫描，模式: {mode}, 目标数量: {top_n}")

        try:
            tier1_results = ml_tier_selection(self.data_service, mode, top_n, relaxed=False)

            if len(tier1_results) < top_n:
                logger.info(f"Tier1筛选仅{len(tier1_results)}只，启动Tier2补充")
                tier2_results = ml_tier_selection(
                    self.data_service, mode, top_n - len(tier1_results), relaxed=True
                )

                tier1_codes = {r["code"] for r in tier1_results}
                for result in tier2_results:
                    if result["code"] not in tier1_codes:
                        result["tier"] = "Tier2"
                        tier1_results.append(result)

            ml_filtered = []
            for result in tier1_results[: top_n * 3]:
                if ml_predict_bullish(result["code"]):
                    ml_filtered.append(result)
                if len(ml_filtered) >= top_n:
                    break

            logger.info(f"ML增强扫描完成，选中 {len(ml_filtered)} 只股票")
            return ml_filtered[:top_n]

        except Exception as e:
            logger.error(f"ML增强扫描失败: {e}")
            return []

    # ==================== 辅助方法 ====================

    def _get_mainboard_stock_pool(self) -> list[dict]:
        """获取主板股票池"""
        try:
            if self.data_service.pro:
                df = self.data_service.pro.stock_basic(
                    exchange="", list_status="L", fields="ts_code,symbol,name,market,industry"
                )
                mainboard_df = df[df["market"].isin(["主板", ""])]
                return mainboard_df.to_dict("records")
        except Exception as e:
            logger.warning(f"获取主板股票池失败: {e}")
        return []

    def _get_full_market_pool(self) -> list[dict]:
        """获取全市场股票池"""
        try:
            if self.data_service.pro:
                df = self.data_service.pro.stock_basic(
                    exchange="",
                    list_status="L",
                    fields="ts_code,symbol,name,market,industry,list_date",
                )
                return df.to_dict("records")
        except Exception as e:
            logger.warning(f"获取全市场股票池失败: {e}")
        return []

    def _analyze_candidate(self, candidate: dict, days: int = 365) -> dict | None:
        """深度分析候选股票"""
        try:
            code = candidate.get("symbol", "")
            if not code:
                return None

            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

            kline_data = self.data_service.get_stock_daily_quote(
                f"{code}.{'SH' if code.startswith('6') else 'SZ'}",
                start_date=start_date,
                end_date=end_date,
                limit=days,
            )

            if not kline_data:
                return None

            df = pd.DataFrame(kline_data)
            if len(df) < 20:
                return None

            result = {
                "code": code,
                "name": candidate.get("name", ""),
                "sector": candidate.get("industry", "未知"),
                "price": float(df.iloc[-1]["close"]) if "close" in df.columns else 0,
                "volume": float(df.iloc[-1]["volume"]) if "volume" in df.columns else 0,
                "near_5d": calculate_price_change(df, 5),
                "near_20d": calculate_price_change(df, 20),
                "rsi": calculate_rsi(df),
                "max_dd": calculate_max_drawdown(df),
                "roe": 10.0,
                "has_nt": False,
                "sharpe": 1.5,
            }

            return result

        except Exception as e:
            logger.warning(f"分析候选股票失败: {e}")
            return None


# 全局实例
_stock_insight_engine = None


def get_stock_insight_engine(data_service=None):
    """获取StockInsightEngine单例实例"""
    global _stock_insight_engine
    if _stock_insight_engine is None and data_service:
        _stock_insight_engine = StockInsightEngine(data_service)
    return _stock_insight_engine
