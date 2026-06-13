"""
Stock Insight 选股引擎
封装 stock_insight 的三个核心算法：主板精选、理性10选股、ML增强扫描
独立引擎，不改动现有回测管线
"""

from datetime import datetime, timedelta
import logging
from typing import Any

import numpy as np
import pandas as pd

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
        self._scan_cache = {}  # 扫描结果缓存

    def scan_mainboard(
        self, top_n: int = 10, owned_codes: list[str] = None
    ) -> list[dict[str, Any]]:
        """
        主板精选选股（基于 pick5_mainboard.py）

        核心逻辑：
        - 长线综合评分：长线×0.35 + 基本面×0.25 + 风险×0.2 + 夏普归一化×0.1 + 国家队×0.1
        - 短线综合评分：短线×0.35 + 动量×0.25 + 技术×0.2 + 量能×0.2
        - 最终得分：长线最终×0.6 + 短线最终×0.4
        - 惩罚机制：避免追高，对近期涨幅、RSI、回撤、ROE等指标扣分
        - 板块去重：优先选择不同板块的股票

        Args:
            top_n: 返回股票数量
            owned_codes: 已持仓代码列表，避免重复推荐

        Returns:
            List[Dict]: 精选股票列表，包含详细评分信息
        """
        logger.info(f"开始主板精选选股，目标数量: {top_n}")

        try:
            # 1. 获取主板股票池
            stock_pool = self._get_mainboard_stock_pool()
            if not stock_pool:
                logger.warning("主板股票池为空")
                return []

            # 2. 基础筛选
            candidates = self._filter_mainboard_candidates(stock_pool, owned_codes)
            if not candidates:
                logger.warning("基础筛选后无候选股票")
                return []

            # 3. 深度分析（模拟原算法逻辑）
            all_results = []
            for candidate in candidates[:40]:  # 原算法分析TOP40
                analysis_result = self._analyze_candidate(candidate)
                if analysis_result:
                    # 计算综合评分
                    scored_result = self._calculate_mainboard_scores(analysis_result)
                    all_results.append(scored_result)

            # 4. 排序和板块去重选择
            selected = self._select_top_with_sector_diversification(all_results, top_n)

            logger.info(f"主板精选完成，选中 {len(selected)} 只股票")
            return selected

        except Exception as e:
            logger.error(f"主板精选选股失败: {e}")
            return []

    def scan_rational(self, top_n: int = 10) -> list[dict[str, Any]]:
        """
        理性10选股（基于 rational_10.py）

        核心逻辑：
        - 长线5只：重基本面+低波动+不追高
        - 短线5只：动量+技术+量能
        - 惩罚机制：对追高、过热、ROE为负等扣分

        Args:
            top_n: 返回股票总数（默认10，长线5+短线5）

        Returns:
            List[Dict]: 选股结果，包含长线/短线分类
        """
        logger.info(f"开始理性选股，目标数量: {top_n}")

        try:
            # 1. 获取全市场数据
            stock_pool = self._get_full_market_pool()
            if not stock_pool:
                logger.warning("全市场股票池为空")
                return []

            # 2. 长线选股（基本面优先）
            long_term_candidates = self._filter_long_term_candidates(stock_pool)
            long_term_results = []

            for candidate in long_term_candidates[:25]:  # 原算法分析TOP25
                analysis_result = self._analyze_candidate(candidate, days=365)
                if analysis_result:
                    scored_result = self._calculate_rational_long_scores(analysis_result)
                    long_term_results.append(scored_result)

            # 按长线最终得分排序
            long_term_results.sort(key=lambda x: x.get("long_final", 0), reverse=True)
            long_selected = long_term_results[: min(5, len(long_term_results))]

            # 3. 短线选股（动量技术优先）
            short_term_candidates = self._filter_short_term_candidates(stock_pool)
            short_term_results = []

            for candidate in short_term_candidates[:25]:
                analysis_result = self._analyze_candidate(candidate, days=120)
                if analysis_result:
                    scored_result = self._calculate_rational_short_scores(analysis_result)
                    short_term_results.append(scored_result)

            # 按短线最终得分排序
            short_term_results.sort(key=lambda x: x.get("short_final", 0), reverse=True)
            short_selected = short_term_results[: min(5, len(short_term_results))]

            # 4. 合并结果
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

        核心逻辑：
        - 两阶段回退：Tier1严格筛选 → Tier2宽松筛选
        - ML集成预测：仅保留"看涨"股票
        - 基本面+技术面+量能综合评分

        Args:
            mode: 扫描模式，"mainboard"（主板）或 "all"（全市场）
            top_n: 返回股票数量

        Returns:
            List[Dict]: ML筛选股票列表，包含Tier分类
        """
        logger.info(f"开始ML增强扫描，模式: {mode}, 目标数量: {top_n}")

        try:
            # 1. Tier1严格筛选
            tier1_results = self._ml_tier_selection(mode, top_n, relaxed=False)

            # 2. 如果Tier1不足，补充Tier2宽松筛选
            if len(tier1_results) < top_n:
                logger.info(f"Tier1筛选仅{len(tier1_results)}只，启动Tier2补充")
                tier2_results = self._ml_tier_selection(
                    mode, top_n - len(tier1_results), relaxed=True
                )

                # 合并结果，避免重复
                tier1_codes = {r["code"] for r in tier1_results}
                for result in tier2_results:
                    if result["code"] not in tier1_codes:
                        result["tier"] = "Tier2"
                        tier1_results.append(result)

            # 3. ML预测过滤
            ml_filtered = []
            for result in tier1_results[: top_n * 3]:  # 原算法取3倍数量用于ML过滤
                if self._ml_predict_bullish(result["code"]):
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
                # 过滤主板股票
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

    def _filter_mainboard_candidates(
        self, stock_pool: list[dict], owned_codes: list[str] = None
    ) -> list[dict]:
        """主板候选股票基础筛选"""
        owned_set = set(owned_codes) if owned_codes else set()

        candidates = []
        for stock in stock_pool:
            code = stock.get("symbol", "")

            # 排除已持仓
            if code in owned_set:
                continue

            # 基础条件（模拟原算法）
            # 这里需要实际数据，暂时返回所有
            candidates.append(stock)

        return candidates[:100]  # 限制数量

    def _filter_long_term_candidates(self, stock_pool: list[dict]) -> list[dict]:
        """长线候选股票筛选"""
        # 模拟原算法筛选条件
        candidates = []
        for stock in stock_pool:
            # 这里需要实际评分数据，暂时返回部分
            candidates.append(stock)

        return candidates[:50]

    def _filter_short_term_candidates(self, stock_pool: list[dict]) -> list[dict]:
        """短线候选股票筛选"""
        # 模拟原算法筛选条件
        candidates = []
        for stock in stock_pool:
            # 这里需要实际评分数据，暂时返回部分
            candidates.append(stock)

        return candidates[:50]

    def _analyze_candidate(self, candidate: dict, days: int = 365) -> dict | None:
        """深度分析候选股票"""
        try:
            code = candidate.get("symbol", "")
            if not code:
                return None

            # 获取日线数据
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

            # 计算技术指标（简化版）
            df = pd.DataFrame(kline_data)
            if len(df) < 20:
                return None

            # 基础分析结果
            result = {
                "code": code,
                "name": candidate.get("name", ""),
                "sector": candidate.get("industry", "未知"),
                "price": float(df.iloc[-1]["close"]) if "close" in df.columns else 0,
                "volume": float(df.iloc[-1]["volume"]) if "volume" in df.columns else 0,
                # 模拟计算指标
                "near_5d": self._calculate_price_change(df, 5),
                "near_20d": self._calculate_price_change(df, 20),
                "rsi": self._calculate_rsi(df),
                "max_dd": self._calculate_max_drawdown(df),
                "roe": 10.0,  # 模拟值，实际需要基本面数据
                "has_nt": False,  # 模拟国家队持股
                "sharpe": 1.5,  # 模拟夏普比率
            }

            return result

        except Exception as e:
            logger.warning(f"分析候选股票失败: {e}")
            return None

    def _calculate_mainboard_scores(self, analysis_result: dict) -> dict:
        """计算主板精选综合评分"""
        r = analysis_result

        # 模拟原算法评分
        nt_bonus = 10 if r.get("has_nt", False) else 0
        sharpe_norm = min(r.get("sharpe", 0), 4) / 4 * 100

        # 长线综合
        long_composite = (
            r.get("long_score", 70) * 0.35
            + r.get("fund_s", 70) * 0.25
            + r.get("risk_s", 70) * 0.20
            + sharpe_norm * 0.10
            + nt_bonus * 0.10
        )

        # 长线惩罚
        long_penalty, penalty_reasons = self._calculate_long_penalty(r)
        long_final = long_composite - long_penalty

        # 短线综合
        short_composite = (
            r.get("short_score", 70) * 0.35
            + r.get("mom_s", 70) * 0.25
            + r.get("tech_s", 70) * 0.20
            + r.get("vol_s", 70) * 0.20
        )

        # 短线惩罚
        short_penalty, _ = self._calculate_short_penalty(r)
        short_final = short_composite - short_penalty - long_penalty * 0.5

        # 最终得分
        final_score = long_final * 0.6 + short_final * 0.4

        result = r.copy()
        result.update(
            {
                "long_composite": long_composite,
                "long_penalty": long_penalty,
                "long_final": long_final,
                "short_composite": short_composite,
                "short_penalty": short_penalty,
                "short_final": short_final,
                "final_score": final_score,
                "penalty_reasons": penalty_reasons,
                "long_score": r.get("long_score", 70),
                "fund_s": r.get("fund_s", 70),
                "risk_s": r.get("risk_s", 70),
                "short_score": r.get("short_score", 70),
                "mom_s": r.get("mom_s", 70),
                "tech_s": r.get("tech_s", 70),
                "vol_s": r.get("vol_s", 70),
            }
        )

        return result

    def _calculate_rational_long_scores(self, analysis_result: dict) -> dict:
        """计算理性选股长线评分"""
        r = analysis_result

        # 模拟原算法评分
        nt_bonus = 10 if r.get("has_nt", False) else 0
        sharpe_norm = min(r.get("sharpe", 0), 4) / 4 * 100

        long_composite = (
            r.get("long_score", 70) * 0.35
            + r.get("fund_s", 70) * 0.25
            + r.get("risk_s", 70) * 0.20
            + sharpe_norm * 0.10
            + nt_bonus * 0.10
        )

        # 惩罚计算
        penalty, reasons = 0, []
        near_20d = r.get("near_20d", 0)
        rsi = r.get("rsi", 50)
        max_dd = r.get("max_dd", 0)
        roe = r.get("roe", 10)

        if near_20d > 30:
            penalty += 10
            reasons.append(f"近20日涨{near_20d:.0f}%")
        elif near_20d > 25:
            penalty += 5
            reasons.append(f"近20日涨{near_20d:.0f}%")

        if rsi > 75:
            penalty += 8
            reasons.append(f"RSI={rsi:.0f}过热")
        elif rsi > 72:
            penalty += 4
            reasons.append(f"RSI={rsi:.0f}偏高")

        if max_dd < -35:
            penalty += 5
            reasons.append(f"回撤{max_dd:.0f}%过大")

        if roe < 0:
            penalty += 10
            reasons.append("ROE为负")

        long_final = long_composite - penalty

        result = r.copy()
        result.update(
            {
                "long_composite": long_composite,
                "penalty": penalty,
                "penalty_reasons": reasons,
                "long_final": long_final,
                "selection_type": "long_term",
            }
        )

        return result

    def _calculate_rational_short_scores(self, analysis_result: dict) -> dict:
        """计算理性选股短线评分"""
        r = analysis_result

        # 短线综合评分
        short_composite = (
            r.get("short_score", 70) * 0.35
            + r.get("mom_s", 70) * 0.25
            + r.get("tech_s", 70) * 0.20
            + r.get("vol_s", 70) * 0.20
        )

        # 短线惩罚
        penalty, reasons = 0, []
        near_5d = r.get("near_5d", 0)

        if near_5d > 18:
            penalty += 10
            reasons.append(f"近5日涨{near_5d:.0f}%")
        elif near_5d > 15:
            penalty += 5
            reasons.append(f"近5日涨{near_5d:.0f}%")

        short_final = short_composite - penalty

        result = r.copy()
        result.update(
            {
                "short_composite": short_composite,
                "penalty": penalty,
                "penalty_reasons": reasons,
                "short_final": short_final,
                "selection_type": "short_term",
            }
        )

        return result

    def _select_top_with_sector_diversification(
        self, all_results: list[dict], top_n: int
    ) -> list[dict]:
        """板块去重选择TOP股票"""
        all_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        picked = []
        used_sectors = set()

        for r in all_results:
            if len(picked) >= top_n:
                break

            sector = r.get("sector", "未知")
            if sector not in used_sectors or r.get("final_score", 0) > 60:
                picked.append(r)
                used_sectors.add(sector)

        return picked

    def _ml_tier_selection(self, mode: str, top_n: int, relaxed: bool) -> list[dict]:
        """ML两阶段筛选"""
        try:
            if not self.data_service.pro:
                return []

            # 获取股票池
            pool = self.data_service.pro.stock_basic(
                exchange="", list_status="L", fields="ts_code,symbol,name,market"
            )

            if mode == "mainboard":
                pool = pool[pool["market"] == "主板"]

            # 获取最新交易日
            today = datetime.now().strftime("%Y%m%d")
            cal = self.data_service.pro.trade_cal(start_date="20260501", end_date=today)

            if cal is not None and len(cal) > 0:
                od = cal[(cal["is_open"] == 1) & (cal["cal_date"] <= today)]["cal_date"]
                latest = od.iloc[0] if len(od) > 0 else today
            else:
                latest = today

            # 获取基本面数据
            db = self.data_service.pro.daily_basic(trade_date=latest)
            if db is None or len(db) == 0:
                return []

            db["code"] = db["ts_code"].str.split(".").str[0]
            dp = db[db["code"].isin(pool["symbol"].tolist())]

            # 筛选条件
            if relaxed:
                # Tier2宽松条件
                cond = (
                    (dp["close"] >= 5)
                    & (dp["close"] <= 100)
                    & (dp["pe"] > 0)
                    & (dp["pe"] <= 100)
                    & (dp["pb"] > 0)
                    & (dp["pb"] <= 15)
                    & (dp["volume_ratio"] >= 0.5)
                    & (dp["turnover_rate"] <= 35)
                )
            else:
                # Tier1严格条件
                cond = (
                    (dp["close"] >= 5)
                    & (dp["close"] <= 80)
                    & (dp["pe"] > 0)
                    & (dp["pe"] <= 60)
                    & (dp["pb"] > 0)
                    & (dp["pb"] <= 8)
                    & (dp["volume_ratio"] >= 0.7)
                    & (dp["turnover_rate"] <= 25)
                )

            fd = dp[cond].copy()
            if len(fd) == 0:
                return []

            # 综合评分
            fd["score"] = (
                fd["pe"].rank(pct=True, ascending=False) * 0.25
                + fd["turnover_rate"].rank(pct=True) * 0.40
                + fd["volume_ratio"].rank(pct=True) * 0.35
            )

            top = fd.sort_values("score", ascending=False).head(top_n * 3)

            results = []
            name_map = dict(zip(pool["symbol"], pool["name"]))

            for _, row in top.iterrows():
                code = row["code"]
                tier = "Tier2" if relaxed else "Tier1"

                results.append(
                    {
                        "code": code,
                        "name": name_map.get(code, ""),
                        "tier": tier,
                        "score": float(row["score"]),
                        "pe": float(row["pe"]),
                        "pb": float(row["pb"]),
                        "close": float(row["close"]),
                        "volume_ratio": float(row["volume_ratio"]),
                        "turnover_rate": float(row["turnover_rate"]),
                    }
                )

                if len(results) >= top_n:
                    break

            return results

        except Exception as e:
            logger.warning(f"ML阶段筛选失败: {e}")
            return []

    def _ml_predict_bullish(self, code: str) -> bool:
        """ML预测是否为看涨"""
        # 模拟ML预测，实际需要集成ML模型
        # 这里返回True模拟看涨预测
        return True

    def _calculate_long_penalty(self, r: dict) -> tuple[float, list[str]]:
        """计算长线惩罚"""
        pen, reasons = 0, []
        near_20d = r.get("near_20d", 0)
        rsi = r.get("rsi", 50)
        max_dd = r.get("max_dd", 0)
        roe = r.get("roe", 10)

        if near_20d > 35:
            pen += 12
            reasons.append(f"近20日涨{near_20d:.0f}%")
        elif near_20d > 30:
            pen += 8
            reasons.append(f"近20日涨{near_20d:.0f}%")
        elif near_20d > 25:
            pen += 4
            reasons.append(f"近20日涨{near_20d:.0f}%")

        if rsi > 78:
            pen += 10
            reasons.append(f"RSI={rsi:.0f}过热")
        elif rsi > 75:
            pen += 6
            reasons.append(f"RSI={rsi:.0f}过热")
        elif rsi > 72:
            pen += 3
            reasons.append(f"RSI={rsi:.0f}偏高")

        if max_dd < -45:
            pen += 8
            reasons.append(f"回撤{max_dd:.0f}%深")
        elif max_dd < -35:
            pen += 4
            reasons.append(f"回撤{max_dd:.0f}%")

        if roe < 0:
            pen += 12
            reasons.append("ROE为负")
        elif roe < 1:
            pen += 5
            reasons.append(f"ROE仅{roe:.1f}%")

        return pen, reasons

    def _calculate_short_penalty(self, r: dict) -> tuple[float, list[str]]:
        """计算短线惩罚"""
        pen, reasons = 0, []
        near_5d = r.get("near_5d", 0)

        if near_5d > 18:
            pen += 10
            reasons.append(f"近5日涨{near_5d:.0f}%")
        elif near_5d > 15:
            pen += 5
            reasons.append(f"近5日涨{near_5d:.0f}%")

        return pen, reasons

    def _calculate_price_change(self, df: pd.DataFrame, days: int) -> float:
        """计算价格变化百分比"""
        if len(df) < days:
            return 0.0

        try:
            close_col = "close" if "close" in df.columns else df.columns[-1]
            start_price = float(df.iloc[-days][close_col])
            end_price = float(df.iloc[-1][close_col])

            if start_price > 0:
                return (end_price - start_price) / start_price * 100
        except Exception as e:
            logger.warning("计算收益率失败: %s", e)

        return 0.0

    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算RSI指标"""
        if len(df) < period + 1:
            return 50.0

        try:
            close_col = "close" if "close" in df.columns else df.columns[-1]
            prices = df[close_col].astype(float).values

            # 简化RSI计算
            deltas = np.diff(prices)
            gains = deltas[deltas > 0]
            losses = -deltas[deltas < 0]

            if len(losses) == 0:
                return 100.0

            avg_gain = np.mean(gains[-period:]) if len(gains) >= period else np.mean(gains)
            avg_loss = np.mean(losses[-period:]) if len(losses) >= period else np.mean(losses)

            if avg_loss == 0:
                return 100.0

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return min(max(rsi, 0), 100)
        except Exception as e:
            logger.warning("计算RSI失败: %s", e)
            return 50.0

    def _calculate_max_drawdown(self, df: pd.DataFrame) -> float:
        """计算最大回撤"""
        if len(df) < 2:
            return 0.0

        try:
            close_col = "close" if "close" in df.columns else df.columns[-1]
            prices = df[close_col].astype(float).values

            peak = prices[0]
            max_dd = 0.0

            for price in prices:
                peak = max(peak, price)
                dd = (price - peak) / peak * 100
                max_dd = min(max_dd, dd)

            return max_dd
        except Exception as e:
            logger.warning("计算最大回撤失败: %s", e)
            return 0.0


# 全局实例
_stock_insight_engine = None


def get_stock_insight_engine(data_service=None):
    """获取StockInsightEngine单例实例"""
    global _stock_insight_engine
    if _stock_insight_engine is None and data_service:
        _stock_insight_engine = StockInsightEngine(data_service)
    return _stock_insight_engine
