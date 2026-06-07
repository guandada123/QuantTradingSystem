"""
多智能体协作框架
参考TradingAgents-CN架构，实现AI原生交易决策系统
包含：基本面分析师、技术面分析师、资金面分析师、情绪分析师、研究员（多空辩论）、风险管理员、交易员
"""

from typing import Dict, List, Any, Optional
from enum import Enum
import logging
from datetime import datetime
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ============================================
# 数据模型
# ============================================

class StockData(BaseModel):
    """股票数据模型"""
    ts_code: str
    name: str
    current_price: float
    open: float
    high: float
    low: float
    volume: int
    amount: float
    change: float
    pct_change: float

class AnalysiResult(BaseModel):
    """分析结果模型"""
    agent_name: str
    ts_code: str
    signal: str  # 'BUY'/'SELL'/'HOLD'
    confidence: float  # 0-100
    reason: str
    key_indicators: Dict[str, Any]
    risks: List[str]
    timestamp: datetime = Field(default_factory=datetime.now)

class DebateArgument(BaseModel):
    """辩论论点模型"""
    agent_name: str
    stance: str  # 'BULL'/'BEAR'/'NEUTRAL'
    argument: str
    evidence: List[str]
    confidence: float
    timestamp: datetime = Field(default_factory=datetime.now)

class TradingDecision(BaseModel):
    """交易决策模型"""
    ts_code: str
    action: str  # 'BUY'/'SELL'/'HOLD'
    quantity: Optional[int] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float
    reasoning: str
    risk_assessment: str
    timestamp: datetime = Field(default_factory=datetime.now)

# ============================================
# 智能体基类
# ============================================

class BaseAgent:
    """智能体基类"""
    
    def __init__(self, name: str, model_scheduler=None, ai_client=None):
        self.name = name
        self.model_scheduler = model_scheduler
        self.ai_client = ai_client
        logger.info(f"智能体初始化：{name}")
    
    def analyze(self, stock_data: StockData, context: Dict[str, Any] = None) -> AnalysiResult:
        """
        分析股票
        子类必须实现此方法
        """
        raise NotImplementedError("子类必须实现analyze方法")
    
    def _call_ai_model(self, prompt: str, task_type: str = 'analysis') -> str:
        """
        调用AI模型（真实API调用）
        支持智能调度和成本优化
        """
        if not self.ai_client:
            logger.warning(f"{self.name}: AIClient未配置，使用模拟分析")
            return self._simulate_analysis(prompt)
        
        import asyncio
        import asyncio
        try:
            # 使用智能调度选择模型
            model_name = 'deepseek-chat'  # 默认Flash
            provider = None
            
            if self.model_scheduler:
                from .ai_scheduler import TaskType, TaskComplexity
                task_map = {
                    'analysis': TaskType.MULTI_AGENT_DEBATE,
                    'sentiment': TaskType.NEWS_SENTIMENT,
                    'selection': TaskType.STOCK_SELECTION,
                    'report': TaskType.DATA_CLEANING,
                }
                selected = self.model_scheduler.select_model(
                    task_map.get(task_type, TaskType.MULTI_AGENT_DEBATE),
                    TaskComplexity.HIGH
                )
                # 映射到实际模型名称
                model_name = {
                    'Deepseek-V4-Flash': 'deepseek-chat',
                    'Deepseek-V4-Pro': 'deepseek-reasoner',
                    'DeepSeek-V3.2': 'deepseek-chat',
                }.get(selected, 'deepseek-chat')
                logger.info(f"智能调度选择: {selected} → {model_name}")
            
            from .ai_client import ModelProvider, AIClient
            result = self.ai_client.call_sync(
                provider=ModelProvider.DEEPSEEK,
                model_name=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4096
            )
            
            if result.success:
                return result.content
            else:
                logger.warning(f"AI调用失败（降级模拟）: {result.error}")
                return self._simulate_analysis(prompt)
                
        except Exception as e:
            logger.warning(f"AI模型调用异常（降级模拟）: {e}")
            return self._simulate_analysis(prompt)
    
    def _simulate_analysis(self, prompt: str) -> str:
        """降级：模拟分析结果（当AI不可用时）"""
        return f"{self.name}的分析结果（模拟模式）"

# ============================================
# 分析师智能体
# ============================================

class FundamentalAnalyst(BaseAgent):
    """基本面分析师智能体"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("基本面分析师", model_scheduler, ai_client)
    
    def analyze(self, stock_data: StockData, context: Dict[str, Any] = None) -> AnalysiResult:
        """
        分析基本面
        关注：PE/PB/ROE/营收增长率/利润增长率/负债率
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")
        
        # TODO: 获取基本面数据
        # - 财务数据（PE/PB/ROE/营收/利润）
        # - 行业对比
        # - 估值水平
        
        # 模拟分析结果
        prompt = f"""
        你是一位资深基本面分析师。请分析以下股票：
        
        股票代码：{stock_data.ts_code}
        股票名称：{stock_data.name}
        当前价格：{stock_data.current_price}
        涨跌幅：{stock_data.pct_change}%
        
        请从以下角度分析：
        1. 估值水平（PE/PB是否合理）
        2. 盈利能力（ROE/利润率趋势）
        3. 成长性（营收/利润增长率）
        4. 财务健康度（负债率/现金流）
        5. 行业地位与竞争优势
        
        给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。
        """
        
        analysis = self._call_ai_model(prompt, task_type='fundamental_analysis')
        
        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal='HOLD',  # 模拟结果
            confidence=60.0,
            reason=analysis,
            key_indicators={
                'PE': 25.5,
                'PB': 3.2,
                'ROE': 0.15,
                'revenue_growth': 0.12,
                'profit_growth': 0.18
            },
            risks=['行业竞争加剧', '原材料价格上涨'],
            timestamp=datetime.now()
        )

class TechnicalAnalyst(BaseAgent):
    """技术面分析师智能体"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("技术面分析师", model_scheduler, ai_client)
    
    def analyze(self, stock_data: StockData, context: Dict[str, Any] = None) -> AnalysiResult:
        """
        分析技术面
        关注：MA/MACD/RSI/KDJ/布林带/成交量/形态
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")
        
        # TODO: 计算技术指标
        # - 均线系统（MA5/MA10/MA20/MA60）
        # - MACD指标
        # - RSI指标
        # - KDJ指标
        # - 布林带
        # - 成交量分析
        # - K线形态识别
        
        prompt = f"""
        你是一位资深技术面分析师。请分析以下股票：
        
        股票代码：{stock_data.ts_code}
        股票名称：{stock_data.name}
        当前价格：{stock_data.current_price}
        开盘价：{stock_data.open}
        最高价：{stock_data.high}
        最低价：{stock_data.low}
        成交量：{stock_data.volume}
        涨跌幅：{stock_data.pct_change}%
        
        请从以下角度分析：
        1. 趋势判断（上升趋势/下降趋势/震荡）
        2. 均线系统（多头排列/空头排列/金叉/死叉）
        3. 动量指标（MACD/RSI/KDJ）
        4. 支撑位与压力位
        5. K线形态（头肩顶/头肩底/双顶/双底/旗形等）
        6. 成交量配合情况
        
        给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。
        """
        
        analysis = self._call_ai_model(prompt, task_type='technical_analysis')
        
        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal='BUY',  # 模拟结果
            confidence=75.0,
            reason=analysis,
            key_indicators={
                'MA5': stock_data.current_price * 0.98,
                'MA10': stock_data.current_price * 0.97,
                'MACD': 0.5,
                'RSI': 65.0,
                'KDJ_K': 70.0
            },
            risks=['短期涨幅较大', '成交量未能持续放大'],
            timestamp=datetime.now()
        )

class MoneyFlowAnalyst(BaseAgent):
    """资金面分析师智能体"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("资金面分析师", model_scheduler, ai_client)
    
    def analyze(self, stock_data: StockData, context: Dict[str, Any] = None) -> AnalysiResult:
        """
        分析资金面
        关注：北向资金/主力资金流/大单成交/融资融券
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")
        
        # TODO: 获取资金流向数据
        # - 北向资金流向
        # - 主力资金净流入
        # - 大单/中单/小单成交分布
        # - 融资余额变化
        # - 解禁压力
        
        prompt = f"""
        你是一位资深资金面分析师。请分析以下股票：
        
        股票代码：{stock_data.ts_code}
        股票名称：{stock_data.name}
        当前价格：{stock_data.current_price}
        涨跌幅：{stock_data.pct_change}%
        换手率：{context.get('turnover_ratio', 'N/A')}%
        
        请从以下角度分析：
        1. 北向资金动向（外资流入/流出）
        2. 主力资金流向（净流入/净流出）
        3. 大单成交情况（机构动向）
        4. 融资融券变化（杠杆资金态度）
        5. 股东户数变化（筹码集中度）
        6. 解禁压力（未来解禁规模）
        
        给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。
        """
        
        analysis = self._call_ai_model(prompt, task_type='money_flow_analysis')
        
        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal='BUY',  # 模拟结果
            confidence=70.0,
            reason=analysis,
            key_indicators={
                'northbound_flow': 100000000,  # 北向资金净流入1亿
                'main_force_flow': 50000000,  # 主力资金净流入5000万
                'margin_balance': 2000000000  # 融资余额20亿
            },
            risks=['北向资金近期流出', '解禁压力较大'],
            timestamp=datetime.now()
        )

class SentimentAnalyst(BaseAgent):
    """情绪分析师智能体"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("情绪分析师", model_scheduler, ai_client)
    
    def analyze(self, stock_data: StockData, context: Dict[str, Any] = None) -> AnalysiResult:
        """
        分析市场情绪
        关注：新闻舆情/社交媒体/公告/研报/市场热度
        """
        logger.info(f"{self.name}正在分析{stock_data.ts_code}")
        
        # TODO: 获取情绪数据
        # - 新闻标题和情感倾向
        # - 社交媒体讨论热度
        # - 公告利好/利空
        # - 研报评级变化
        # - 市场整体情绪指标
        
        prompt = f"""
        你是一位资深市场情绪分析师。请分析以下股票：
        
        股票代码：{stock_data.ts_code}
        股票名称：{stock_data.name}
        当前价格：{stock_data.current_price}
        涨跌幅：{stock_data.pct_change}%
        
        请从以下角度分析：
        1. 新闻舆情（正面/负面新闻数量）
        2. 社交媒体热度（讨论量/情感倾向）
        3. 公告影响（利好/利空公告）
        4. 研报评级（买入/持有/卖出评级变化）
        5. 市场整体情绪（恐慌指数/贪婪指数）
        6. 板块联动效应
        
        给出明确的交易信号（BUY/SELL/HOLD）和置信度（0-100）。
        """
        
        analysis = self._call_ai_model(prompt, task_type='sentiment_analysis')
        
        return AnalysiResult(
            agent_name=self.name,
            ts_code=stock_data.ts_code,
            signal='HOLD',  # 模拟结果
            confidence=55.0,
            reason=analysis,
            key_indicators={
                'news_sentiment': 0.6,  # 新闻情绪指数（0-1）
                'social_media_buzz': 0.7,  # 社交媒体热度
                'report_rating': '买入',  # 研报评级
                'market_fear_greed': 0.65  # 市场恐慌/贪婪指数
            },
            risks=['负面情绪蔓延', '板块整体调整'],
            timestamp=datetime.now()
        )

# ============================================
# 研究员智能体（多空辩论）
# ============================================

class BullResearcher(BaseAgent):
    """看涨研究员智能体"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("看涨研究员", model_scheduler, ai_client)
    
    def debate(self, analysis_results: List[AnalysiResult]) -> DebateArgument:
        """
        从多头视角解读分析结果
        """
        logger.info(f"{self.name}正在进行多空辩论（多头观点）")
        
        # 汇总所有分析结果
        analysis_summary = "\n".join([
            f"- {r.agent_name}: 信号={r.signal}, 置信度={r.confidence}, 理由={r.reason[:100]}..."
            for r in analysis_results
        ])
        
        prompt = f"""
        你是一位看涨（多头）研究员。请基于以下分析结果，从多头视角进行辩论：
        
        {analysis_summary}
        
        请提供：
        1. 支持买入的核心理由（至少3条）
        2. 对空头观点的反驳
        3. 潜在的上涨催化剂
        4. 风险评估与应对
        
        输出JSON格式，包含：argument（论点）、evidence（证据列表）、confidence（置信度0-100）。
        """
        
        debate_result = self._call_ai_model(prompt, task_type='debate')
        
        return DebateArgument(
            agent_name=self.name,
            stance='BULL',
            argument=debate_result,
            evidence=[
                '技术指标显示金叉',
                '主力资金持续流入',
                '北向资金大幅加仓',
                '利好公告即将发布'
            ],
            confidence=72.0,
            timestamp=datetime.now()
        )

class BearResearcher(BaseAgent):
    """看跌研究员智能体"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("看跌研究员", model_scheduler, ai_client)
    
    def debate(self, analysis_results: List[AnalysiResult]) -> DebateArgument:
        """
        从空头视角解读分析结果
        """
        logger.info(f"{self.name}正在进行多空辩论（空头观点）")
        
        # 汇总所有分析结果
        analysis_summary = "\n".join([
            f"- {r.agent_name}: 信号={r.signal}, 置信度={r.confidence}, 理由={r.reason[:100]}..."
            for r in analysis_results
        ])
        
        prompt = f"""
        你是一位看跌（空头）研究员。请基于以下分析结果，从空头视角进行辩论：
        
        {analysis_summary}
        
        请提供：
        1. 支持卖出的核心理由（至少3条）
        2. 对多头观点的反驳
        3. 潜在的下跌催化剂
        4. 风险提示与应对
        
        输出JSON格式，包含：argument（论点）、evidence（证据列表）、confidence（置信度0-100）。
        """
        
        debate_result = self._call_ai_model(prompt, task_type='debate')
        
        return DebateArgument(
            agent_name=self.name,
            stance='BEAR',
            argument=debate_result,
            evidence=[
                '估值过高，PE超过行业平均',
                '主力资金开始流出',
                '技术指标显示超买',
                '即将面临解禁压力'
            ],
            confidence=68.0,
            timestamp=datetime.now()
        )

# ============================================
# 风险管理智能体
# ============================================

class RiskManager(BaseAgent):
    """风险管理员智能体"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("风险管理员", model_scheduler, ai_client)
        self.max_position_ratio = 0.30  # 单只股票最大仓位30%
        self.max_total_positions = 3      # 最大持仓数量
        self.stop_loss_ratio = 0.08       # 止损比例8%
        self.take_profit_ratio = 0.30     # 止盈比例30%
    
    def assess_risk(
        self, 
        ts_code: str,
        current_position: Dict[str, Any],
        trading_decision: TradingDecision,
        market_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        评估交易风险
        返回：风险评分、建议操作、风险提示
        """
        logger.info(f"{self.name}正在评估{ts_code}的交易风险")
        
        risks = []
        risk_score = 0  # 0-100，分数越高风险越大
        
        # 1. 仓位风险
        if current_position:
            position_ratio = current_position.get('market_value', 0) / market_context.get('total_assets', 1)
            if position_ratio > self.max_position_ratio:
                risks.append(f"仓位超标：当前{(position_ratio*100):.1f}%，最大{self.max_position_ratio*100}%")
                risk_score += 30
        
        # 2. 持仓数量风险
        total_positions = market_context.get('total_positions', 0)
        if total_positions >= self.max_total_positions and trading_decision.action == 'BUY':
            risks.append(f"持仓数量超标：当前{total_positions}只，最大{self.max_total_positions}只")
            risk_score += 25
        
        # 3. 止损风险
        if current_position and trading_decision.action == 'HOLD':
            cost_price = current_position.get('cost_price', 0)
            current_price = current_position.get('current_price', 0)
            loss_ratio = (current_price - cost_price) / cost_price if cost_price > 0 else 0
            
            if loss_ratio < -self.stop_loss_ratio:
                risks.append(f"触发止损：亏损{(abs(loss_ratio)*100):.1f}%，止损线{self.stop_loss_ratio*100}%")
                risk_score += 40
        
        # 4. 市场整体风险
        market_trend = market_context.get('market_trend', 'neutral')
        if market_trend == 'bearish' and trading_decision.action == 'BUY':
            risks.append("市场处于下降趋势，不建议买入")
            risk_score += 20
        
        # 5. 流动性风险
        # TODO: 检查股票流动性（成交量/换手率）
        
        # 确定风险等级
        if risk_score >= 70:
            risk_level = 'CRITICAL'
            recommended_action = 'REJECT'  # 拒绝交易
        elif risk_score >= 40:
            risk_level = 'HIGH'
            recommended_action = 'REDUCE'  # 降低仓位
        elif risk_score >= 20:
            risk_level = 'MEDIUM'
            recommended_action = 'CAUTION'  # 谨慎操作
        else:
            risk_level = 'LOW'
            recommended_action = 'APPROVE'  # 批准交易
        
        return {
            'ts_code': ts_code,
            'risk_score': risk_score,
            'risk_level': risk_level,
            'risks': risks,
            'recommended_action': recommended_action,
            'max_position_ratio': self.max_position_ratio,
            'stop_loss_price': trading_decision.stop_loss,
            'take_profit_price': trading_decision.take_profit
        }

# ============================================
# 交易员智能体（最终决策者）
# ============================================

class Trader(BaseAgent):
    """交易员智能体（最终决策者）"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        super().__init__("交易员", model_scheduler, ai_client)
    
    def make_decision(
        self,
        ts_code: str,
        analysis_results: List[AnalysiResult],
        debate_arguments: List[DebateArgument],
        risk_assessment: Dict[str, Any]
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
            if result.signal == 'BUY':
                buy_signals += 1
                bull_confidence += result.confidence
            elif result.signal == 'SELL':
                sell_signals += 1
                bear_confidence += result.confidence
            else:
                hold_signals += 1
        
        # 2. 分析辩论论点
        for argument in debate_arguments:
            if argument.stance == 'BULL':
                bull_confidence += argument.confidence
            elif argument.stance == 'BEAR':
                bear_confidence += argument.confidence
        
        # 3. 风险评估
        risk_level = risk_assessment.get('risk_level', 'LOW')
        recommended_action = risk_assessment.get('recommended_action', 'APPROVE')
        
        # 4. 做出决策
        # 如果风险过高，拒绝交易
        if recommended_action == 'REJECT':
            return TradingDecision(
                ts_code=ts_code,
                action='HOLD',
                confidence=100.0,
                reasoning=f"风险过高（{risk_level}），拒绝交易。风险点：{', '.join(risk_assessment.get('risks', []))}",
                risk_assessment=risk_level,
                timestamp=datetime.now()
            )
        
        # 根据多空辩论结果决策
        if bull_confidence > bear_confidence and recommended_action != 'REDUCE':
            # 买入
            action = 'BUY'
            confidence = bull_confidence / (bull_confidence + bear_confidence) * 100
            
            # TODO: 计算目标价、止损价、止盈价
            target_price = 0  # 需要计算
            stop_loss = 0
            take_profit = 0
            
            return TradingDecision(
                ts_code=ts_code,
                action=action,
                quantity=None,  # 需要根据仓位管理计算
                target_price=target_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                reasoning=f"多头置信度{bull_confidence:.1f}，空头置信度{bear_confidence:.1f}，看多理由更强",
                risk_assessment=risk_level,
                timestamp=datetime.now()
            )
        elif bear_confidence > bull_confidence:
            # 卖出
            action = 'SELL'
            confidence = bear_confidence / (bull_confidence + bear_confidence) * 100
            
            return TradingDecision(
                ts_code=ts_code,
                action=action,
                quantity=None,  # 需要根据持仓计算
                confidence=confidence,
                reasoning=f"空头置信度{bear_confidence:.1f}，多头置信度{bull_confidence:.1f}，看空理由更强",
                risk_assessment=risk_level,
                timestamp=datetime.now()
            )
        else:
            # 持有
            return TradingDecision(
                ts_code=ts_code,
                action='HOLD',
                confidence=50.0,
                reasoning="多空力量均衡，暂不明确方向，建议持有观望",
                risk_assessment=risk_level,
                timestamp=datetime.now()
            )

# ============================================
# 多智能体协作系统
# ============================================

class MultiAgentTradingSystem:
    """多智能体交易系统"""
    
    def __init__(self, model_scheduler=None, ai_client=None):
        """初始化多智能体系统"""
        self.model_scheduler = model_scheduler
        self.ai_client = ai_client
        
        # 初始化所有智能体（传递ai_client以支持真实AI调用）
        self.agents = {
            'fundamental_analyst': FundamentalAnalyst(model_scheduler, ai_client),
            'technical_analyst': TechnicalAnalyst(model_scheduler, ai_client),
            'money_flow_analyst': MoneyFlowAnalyst(model_scheduler, ai_client),
            'sentiment_analyst': SentimentAnalyst(model_scheduler, ai_client),
            'bull_researcher': BullResearcher(model_scheduler, ai_client),
            'bear_researcher': BearResearcher(model_scheduler, ai_client),
            'risk_manager': RiskManager(model_scheduler, ai_client),
            'trader': Trader(model_scheduler, ai_client)
        }
        
        logger.info("多智能体交易系统初始化完成")
    
    def analyze_stock(self, stock_data: StockData, market_context: Dict[str, Any]) -> TradingDecision:
        """
        完整的股票分析流程（多智能体协作）
        
        流程：
        1. 并行分析（4个分析师智能体）
        2. 多空辩论（2个研究员智能体）
        3. 风险评估（风险管理员智能体）
        4. 交易决策（交易员智能体）
        """
        logger.info(f"开始分析股票：{stock_data.ts_code}")
        
        # ===== 第一阶段：并行分析 =====
        analysis_results = []
        
        # 基本面分析
        fundamental_result = self.agents['fundamental_analyst'].analyze(stock_data, market_context)
        analysis_results.append(fundamental_result)
        
        # 技术面分析
        technical_result = self.agents['technical_analyst'].analyze(stock_data, market_context)
        analysis_results.append(technical_result)
        
        # 资金面分析
        money_flow_result = self.agents['money_flow_analyst'].analyze(stock_data, market_context)
        analysis_results.append(money_flow_result)
        
        # 情绪分析
        sentiment_result = self.agents['sentiment_analyst'].analyze(stock_data, market_context)
        analysis_results.append(sentiment_result)
        
        logger.info(f"第一阶段完成：4个分析师完成分析")
        
        # ===== 第二阶段：多空辩论 =====
        debate_arguments = []
        
        # 看涨研究员辩论
        bull_argument = self.agents['bull_researcher'].debate(analysis_results)
        debate_arguments.append(bull_argument)
        
        # 看跌研究员辩论
        bear_argument = self.agents['bear_researcher'].debate(analysis_results)
        debate_arguments.append(bear_argument)
        
        logger.info(f"第二阶段完成：多空辩论结束")
        
        # ===== 第三阶段：风险评估 =====
        # 获取当前持仓（如果有）
        current_position = market_context.get('positions', {}).get(stock_data.ts_code)
        
        # 初步交易决策（用于风险评估）
        preliminary_decision = self.agents['trader'].make_decision(
            stock_data.ts_code,
            analysis_results,
            debate_arguments,
            {'risk_level': 'LOW', 'recommended_action': 'APPROVE'}  # 临时，后面会重新评估
        )
        
        # 风险评估
        risk_assessment = self.agents['risk_manager'].assess_risk(
            stock_data.ts_code,
            current_position,
            preliminary_decision,
            market_context
        )
        
        logger.info(f"第三阶段完成：风险评估完成，风险等级={risk_assessment['risk_level']}")
        
        # ===== 第四阶段：最终交易决策 =====
        final_decision = self.agents['trader'].make_decision(
            stock_data.ts_code,
            analysis_results,
            debate_arguments,
            risk_assessment
        )
        
        logger.info(f"第四阶段完成：最终决策={final_decision.action}，置信度={final_decision.confidence:.1f}")
        
        # 返回最终决策
        return final_decision
    
    def batch_analyze(self, stock_list: List[StockData], market_context: Dict[str, Any]) -> List[TradingDecision]:
        """
        批量分析多只股票
        """
        decisions = []
        
        for stock_data in stock_list:
            decision = self.analyze_stock(stock_data, market_context)
            decisions.append(decision)
        
        return decisions
