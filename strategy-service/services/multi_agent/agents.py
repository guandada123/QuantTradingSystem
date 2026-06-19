"""
多智能体协作框架 — 智能体实现

包含 8 个智能体子类：
- 4 位分析师：FundamentalAnalyst（基本面）、TechnicalAnalyst（技术面）、
             MoneyFlowAnalyst（资金面）、SentimentAnalyst（情绪）
- 2 位研究员：BullResearcher（看涨）、BearResearcher（看跌）
- RiskManager（风险管理员）
- Trader（交易员 / 最终决策者）

v2.2 变更：提示词外置为 YAML 配置文件，支持非程序员调优
"""

import logging
from datetime import datetime
from typing import Any

from .base import BaseAgent
from .models import AnalysiResult, DebateArgument, TradingDecision
from .prompts import SYSTEM_PROMPTS

logger = logging.getLogger(__name__)


# ============================================
# 基本面分析师
# ============================================


class FundamentalAnalyst(BaseAgent):
    """基本面分析师智能体"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("基本面分析师", model_scheduler, ai_client)

    def analyze(self, stock_data: "StockData", context: dict[str, Any] = None) -> AnalysiResult:
        """
        分析基本面
        关注：PE/PB/ROE/营收增长率/利润增长率/负债率
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")

        # 基本面数据采集 (当前仅发送股票基本信息给 AI 分析)
        # 将来可接入 Tushare API 获取:
        #   - income/pro: 营收/利润 (pro-api: income_vip)
        #   - fina_indicator: PE/PB/ROE
        #   - balancsheet: 负债率
        fundamental_data = {
            "pe": "N/A",
            "pb": "N/A",
            "roe": "N/A",
            "revenue_growth": "N/A",
            "profit_growth": "N/A",
            "_note": "需配置 Tushare Pro 权限获取财务数据",
        }

        # 系统提示词（固定→缓存命中）+ 用户消息（仅变量→不命中）
        system_prompt = SYSTEM_PROMPTS["fundamental"]
        user_message = f"""请分析以下股票：

股票代码：{stock_data.ts_code}
股票名称：{stock_data.name}
当前价格：{stock_data.current_price:.2f}
涨跌幅：{stock_data.pct_change:.2f}%

请给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。"""

        analysis = self._call_ai_model(
            user_message, system_prompt=system_prompt, task_type="fundamental_analysis"
        )

        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal="HOLD",  # 模拟结果
            confidence=60.0,
            reason=analysis,
            key_indicators={
                "PE": 25.5,
                "PB": 3.2,
                "ROE": 0.15,
                "revenue_growth": 0.12,
                "profit_growth": 0.18,
            },
            risks=["行业竞争加剧", "原材料价格上涨"],
            timestamp=datetime.now(),
        )


# ============================================
# 技术面分析师
# ============================================


class TechnicalAnalyst(BaseAgent):
    """技术面分析师智能体"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("技术面分析师", model_scheduler, ai_client)

    def analyze(self, stock_data: "StockData", context: dict[str, Any] = None) -> AnalysiResult:
        """
        分析技术面
        关注：MA/MACD/RSI/KDJ/布林带/成交量/形态
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")

        # 技术指标 (当前由 AI 模型自主分析)
        # 将来可预计算后注入 prompt:
        #   Tushare daily + TA-Lib → MA/MACD/RSI/KDJ/BOLL
        tech_indicators = {
            "ma5": "N/A",
            "ma20": "N/A",
            "macd": "N/A",
            "rsi": "N/A",
            "kdj_k": "N/A",
            "_note": "需 K 线数据 (Tushare daily/pro_bar) + TA-Lib",
        }

        system_prompt = SYSTEM_PROMPTS["technical"]
        user_message = f"""请分析以下股票：

股票代码：{stock_data.ts_code}
股票名称：{stock_data.name}
当前价格：{stock_data.current_price:.2f}
开盘价：{stock_data.open:.2f}
最高价：{stock_data.high:.2f}
最低价：{stock_data.low:.2f}
成交量：{stock_data.volume}
涨跌幅：{stock_data.pct_change:.2f}%

请给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。"""

        analysis = self._call_ai_model(
            user_message, system_prompt=system_prompt, task_type="technical_analysis"
        )

        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal="BUY",  # 模拟结果
            confidence=75.0,
            reason=analysis,
            key_indicators={
                "MA5": stock_data.current_price * 0.98,
                "MA10": stock_data.current_price * 0.97,
                "MACD": 0.5,
                "RSI": 65.0,
                "KDJ_K": 70.0,
            },
            risks=["短期涨幅较大", "成交量未能持续放大"],
            timestamp=datetime.now(),
        )


# ============================================
# 资金面分析师
# ============================================


class MoneyFlowAnalyst(BaseAgent):
    """资金面分析师智能体"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("资金面分析师", model_scheduler, ai_client)

    def analyze(self, stock_data: "StockData", context: dict[str, Any] = None) -> AnalysiResult:
        """
        分析资金面
        关注：北向资金/主力资金流/大单成交/融资融券
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")

        # 资金流向 (当前使用 turnover_ratio context)
        # 将来可接入: Tushare moneyflow_hsgt (北向)、moneyflow (主力)
        flow_data = {
            "north_bound": "N/A",
            "main_net_inflow": "N/A",
            "margin_balance": "N/A",
            "_note": "需 Tushare moneyflow 接口 + 北向资金权限",
        }

        system_prompt = SYSTEM_PROMPTS["money_flow"]
        turnover = context.get("turnover_ratio", "N/A") if context else "N/A"
        user_message = f"""请分析以下股票：

股票代码：{stock_data.ts_code}
股票名称：{stock_data.name}
当前价格：{stock_data.current_price:.2f}
涨跌幅：{stock_data.pct_change:.2f}%
换手率：{turnover}%

请给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。"""

        analysis = self._call_ai_model(
            user_message, system_prompt=system_prompt, task_type="money_flow_analysis"
        )

        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal="BUY",  # 模拟结果
            confidence=70.0,
            reason=analysis,
            key_indicators={
                "northbound_flow": 100000000,  # 北向资金净流入1亿
                "main_force_flow": 50000000,  # 主力资金净流入5000万
                "margin_balance": 2000000000,  # 融资余额20亿
            },
            risks=["北向资金近期流出", "解禁压力较大"],
            timestamp=datetime.now(),
        )


# ============================================
# 情绪分析师
# ============================================


class SentimentAnalyst(BaseAgent):
    """情绪分析师智能体"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("情绪分析师", model_scheduler, ai_client)

    def analyze(self, stock_data: "StockData", context: dict[str, Any] = None) -> AnalysiResult:
        """
        分析市场情绪
        关注：新闻舆情/社交媒体/公告/研报/市场热度
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")

        # 市场情绪 (当前由 AI 模型自主分析)
        # 将来可接入: AKShare news, 东方财富公告, 通达信研报
        sentiment_data = {
            "news_score": "N/A",
            "social_heat": "N/A",
            "report_rating": "N/A",
            "_note": "需接入新闻/公告/研报数据源 + NLP 情感分析",
        }

        system_prompt = SYSTEM_PROMPTS["sentiment"]
        user_message = f"""请分析以下股票：

股票代码：{stock_data.ts_code}
股票名称：{stock_data.name}
当前价格：{stock_data.current_price:.2f}
涨跌幅：{stock_data.pct_change:.2f}%

请给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。"""

        analysis = self._call_ai_model(
            user_message, system_prompt=system_prompt, task_type="sentiment_analysis"
        )

        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal="HOLD",  # 模拟结果
            confidence=55.0,
            reason=analysis,
            key_indicators={
                "news_sentiment": 0.6,  # 新闻情绪指数（0-1）
                "social_media_buzz": 0.7,  # 社交媒体热度
                "report_rating": "买入",  # 研报评级
                "market_fear_greed": 0.65,  # 市场恐慌/贪婪指数
            },
            risks=["负面情绪蔓延", "板块整体调整"],
            timestamp=datetime.now(),
        )


# ============================================
# 研究员智能体（多空辩论）
# ============================================


class BullResearcher(BaseAgent):
    """看涨研究员智能体"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("看涨研究员", model_scheduler, ai_client)

    def debate(self, analysis_results: list[AnalysiResult]) -> DebateArgument:
        """
        从多头视角解读分析结果
        """
        logger.info(f"{self.name}正在进行多空辩论（多头观点）")

        # 汇总所有分析结果
        analysis_summary = "\n".join(
            [
                f"- {r.agent_name}: 信号={r.signal}, 置信度={r.confidence:.1f}, 理由={r.reason[:100]}..."
                for r in analysis_results
            ]
        )

        system_prompt = SYSTEM_PROMPTS["bull_debate"]
        user_message = f"""请基于以下分析结果，从多头视角进行辩论：

{analysis_summary}"""

        debate_result = self._call_ai_model(
            user_message, system_prompt=system_prompt, task_type="debate"
        )

        return DebateArgument(
            agent_name=self.name,
            stance="BULL",
            argument=debate_result,
            evidence=[
                "技术指标显示金叉",
                "主力资金持续流入",
                "北向资金大幅加仓",
                "利好公告即将发布",
            ],
            confidence=72.0,
            timestamp=datetime.now(),
        )


class BearResearcher(BaseAgent):
    """看跌研究员智能体"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("看跌研究员", model_scheduler, ai_client)

    def debate(self, analysis_results: list[AnalysiResult]) -> DebateArgument:
        """
        从空头视角解读分析结果
        """
        logger.info(f"{self.name}正在进行多空辩论（空头观点）")

        # 汇总所有分析结果
        analysis_summary = "\n".join(
            [
                f"- {r.agent_name}: 信号={r.signal}, 置信度={r.confidence:.1f}, 理由={r.reason[:100]}..."
                for r in analysis_results
            ]
        )

        system_prompt = SYSTEM_PROMPTS["bear_debate"]
        user_message = f"""请基于以下分析结果，从空头视角进行辩论：

{analysis_summary}"""

        debate_result = self._call_ai_model(
            user_message, system_prompt=system_prompt, task_type="debate"
        )

        return DebateArgument(
            agent_name=self.name,
            stance="BEAR",
            argument=debate_result,
            evidence=[
                "估值过高，PE超过行业平均",
                "主力资金开始流出",
                "技术指标显示超买",
                "即将面临解禁压力",
            ],
            confidence=68.0,
            timestamp=datetime.now(),
        )


# ============================================
# 风险管理智能体
# ============================================


class RiskManager(BaseAgent):
    """风险管理员智能体"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("风险管理员", model_scheduler, ai_client)
        self.max_position_ratio = 0.30  # 单只股票最大仓位30%
        self.max_total_positions = 3  # 最大持仓数量
        self.stop_loss_ratio = 0.08  # 止损比例8%
        self.take_profit_ratio = 0.30  # 止盈比例30%
        self.min_daily_volume = 1_000_000  # 最小日均成交额（万），用于流动性检查

    def assess_risk(
        self,
        ts_code: str,
        current_position: dict[str, Any],
        trading_decision: TradingDecision,
        market_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        评估交易风险
        返回：风险评分、建议操作、风险提示
        """
        logger.info(f"{self.name}正在评估{ts_code}的交易风险")

        risks = []
        risk_score = 0  # 0-100，分数越高风险越大

        # 1. 仓位风险
        if current_position:
            position_ratio = current_position.get("market_value", 0) / market_context.get(
                "total_assets", 1
            )
            if position_ratio > self.max_position_ratio:
                risks.append(
                    f"仓位超标：当前{(position_ratio * 100):.1f}%，最大{self.max_position_ratio * 100}%"
                )
                risk_score += 30

        # 2. 持仓数量风险
        total_positions = market_context.get("total_positions", 0)
        if total_positions >= self.max_total_positions and trading_decision.action == "BUY":
            risks.append(f"持仓数量超标：当前{total_positions}只，最大{self.max_total_positions}只")
            risk_score += 25

        # 3. 止损风险
        if current_position and trading_decision.action == "HOLD":
            cost_price = current_position.get("cost_price", 0)
            current_price = current_position.get("current_price", 0)
            loss_ratio = (current_price - cost_price) / cost_price if cost_price > 0 else 0

            if loss_ratio < -self.stop_loss_ratio:
                risks.append(
                    f"触发止损：亏损{(abs(loss_ratio) * 100):.1f}%，止损线{self.stop_loss_ratio * 100}%"
                )
                risk_score += 40

        # 4. 市场整体风险
        market_trend = market_context.get("market_trend", "neutral")
        if market_trend == "bearish" and trading_decision.action == "BUY":
            risks.append("市场处于下降趋势，不建议买入")
            risk_score += 20

        # 5. 流动性风险 (使用 context 中的 volume/turnover)
        volume = market_context.get("volume", 0)
        turnover = market_context.get("turnover_ratio", 0)
        if volume > 0 and volume < self.min_daily_volume:
            risks.append(f"流动性不足：日均成交{volume:.0f}万 < {self.min_daily_volume}万")
            risk_score += 15
        # 将来可接入 Tushare daily_basic (vol/turnover_rate) 获取准确数据

        # 确定风险等级
        if risk_score >= 70:
            risk_level = "CRITICAL"
            recommended_action = "REJECT"  # 拒绝交易
        elif risk_score >= 40:
            risk_level = "HIGH"
            recommended_action = "REDUCE"  # 降低仓位
        elif risk_score >= 20:
            risk_level = "MEDIUM"
            recommended_action = "CAUTION"  # 谨慎操作
        else:
            risk_level = "LOW"
            recommended_action = "APPROVE"  # 批准交易

        return {
            "ts_code": ts_code,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "risks": risks,
            "recommended_action": recommended_action,
            "max_position_ratio": self.max_position_ratio,
            "stop_loss_price": trading_decision.stop_loss,
            "take_profit_price": trading_decision.take_profit,
        }


# ============================================
# 交易员智能体（最终决策者）
# ============================================


class Trader(BaseAgent):
    """交易员智能体（最终决策者）"""

    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("交易员", model_scheduler, ai_client)
        self.stop_loss_ratio = 0.08
        self.take_profit_ratio = 0.30

    def make_decision(
        self,
        ts_code: str,
        analysis_results: list[AnalysiResult],
        debate_arguments: list[DebateArgument],
        risk_assessment: dict[str, Any],
    ) -> TradingDecision:
        """
        综合所有分析和辩论，做出最终交易决策
        """
        logger.info(f"{self.name}正在为{ts_code}做出最终交易决策")

        # 1. 汇总所有分析结果
        bull_confidence = 0
        bear_confidence = 0
        buy_signals = 0
        sell_signals = 0
        hold_signals = 0

        for result in analysis_results:
            if result.signal == "BUY":
                buy_signals += 1
                bull_confidence += result.confidence
            elif result.signal == "SELL":
                sell_signals += 1
                bear_confidence += result.confidence
            else:
                hold_signals += 1

        # 2. 分析辩论论点
        for argument in debate_arguments:
            if argument.stance == "BULL":
                bull_confidence += argument.confidence
            elif argument.stance == "BEAR":
                bear_confidence += argument.confidence

        # 3. 风险评估
        risk_level = risk_assessment.get("risk_level", "LOW")
        recommended_action = risk_assessment.get("recommended_action", "APPROVE")

        # 4. 做出决策
        # 如果风险过高，拒绝交易
        if recommended_action == "REJECT":
            return TradingDecision(
                ts_code=ts_code,
                action="HOLD",
                confidence=100.0,
                reasoning=f"风险过高（{risk_level}），拒绝交易。风险点：{', '.join(risk_assessment.get('risks', []))}",
                risk_assessment=risk_level,
                timestamp=datetime.now(),
            )

        # 根据多空辩论结果决策
        if bull_confidence > bear_confidence and recommended_action != "REDUCE":
            action = "BUY"
            confidence = bull_confidence / (bull_confidence + bear_confidence) * 100

            # 计算目标价、止损价、止盈价（基于默认风控参数）
            stop_loss_ratio = self.stop_loss_ratio
            take_profit_ratio = self.take_profit_ratio

            # 从分析结果推断当前价格
            current_price = 0
            for r in analysis_results:
                for k, v in r.key_indicators.items():
                    if k in ("MA5", "MA10") and isinstance(v, (int, float)) and v > 0:
                        current_price = v
                        break
                if current_price > 0:
                    break

            if current_price > 0:
                stop_loss_price = round(current_price * (1 - stop_loss_ratio), 2)
                take_profit_price = round(current_price * (1 + take_profit_ratio), 2)
            else:
                stop_loss_price = 0
                take_profit_price = 0

            return TradingDecision(
                ts_code=ts_code,
                action=action,
                quantity=None,
                target_price=take_profit_price,
                stop_loss=stop_loss_price,
                take_profit=take_profit_price,
                confidence=confidence,
                reasoning=f"多头置信度{bull_confidence:.1f}，空头置信度{bear_confidence:.1f}，看多理由更强",
                risk_assessment=risk_level,
                timestamp=datetime.now(),
            )
        if bear_confidence > bull_confidence:
            # 卖出
            action = "SELL"
            confidence = bear_confidence / (bull_confidence + bear_confidence) * 100

            return TradingDecision(
                ts_code=ts_code,
                action=action,
                quantity=None,  # 需要根据持仓计算
                confidence=confidence,
                reasoning=f"空头置信度{bear_confidence:.1f}，多头置信度{bull_confidence:.1f}，看空理由更强",
                risk_assessment=risk_level,
                timestamp=datetime.now(),
            )
        # 持有
        return TradingDecision(
            ts_code=ts_code,
            action="HOLD",
            confidence=50.0,
            reasoning="多空力量均衡，暂不明确方向，建议持有观望",
            risk_assessment=risk_level,
            timestamp=datetime.now(),
        )
