"""
风险控制器
交易风险检查、止损止盈监控、仓位限制
"""

import logging
from typing import Dict, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class RiskController:
    """交易风险控制器"""
    
    def __init__(
        self,
        max_position_ratio: float = 0.30,
        max_total_positions: int = 3,
        stop_loss_ratio: float = 0.08,
        take_profit_ratio: float = 0.30,
        max_daily_loss: float = 0.05
    ):
        self.max_position_ratio = max_position_ratio
        self.max_total_positions = max_total_positions
        self.stop_loss_ratio = stop_loss_ratio
        self.take_profit_ratio = take_profit_ratio
        self.max_daily_loss = max_daily_loss
    
    def check_trade_risk(
        self,
        ts_code: str,
        action: str,
        quantity: int,
        account_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查交易风险
        返回：{allowed: bool, risk_level: str, risks: [], recommendation: str}
        """
        risks = []
        
        # 1. 仓位检查
        if action == 'BUY':
            total_assets = account_info.get('total_assets', 0)
            current_position = account_info.get('positions', {}).get(ts_code, {})
            current_ratio = current_position.get('market_value', 0) / total_assets if total_assets > 0 else 0
            
            if current_ratio > self.max_position_ratio:
                risks.append(f"仓位超标：{current_ratio*100:.1f}% > {self.max_position_ratio*100}%")
        
        # 2. 持仓数量检查
        if action == 'BUY':
            total_positions = account_info.get('total_positions', 0)
            if total_positions >= self.max_total_positions and ts_code not in account_info.get('positions', {}):
                risks.append(f"持仓数量超标：{total_positions} > {self.max_total_positions}")
        
        # 3. 风险等级
        risk_level = 'HIGH' if len(risks) > 1 else ('MEDIUM' if len(risks) == 1 else 'LOW')
        allowed = risk_level != 'HIGH'
        
        return {
            'allowed': allowed,
            'risk_level': risk_level,
            'risks': risks,
            'recommendation': 'PASS' if allowed else 'BLOCK',
            'timestamp': datetime.now().isoformat()
        }
    
    def check_stop_loss(self, ts_code: str, cost_price: float, current_price: float) -> Dict[str, Any]:
        """检查是否需要止损"""
        loss_ratio = (current_price - cost_price) / cost_price if cost_price > 0 else 0
        
        if loss_ratio < -self.stop_loss_ratio:
            return {
                'triggered': True,
                'action': 'STOP_LOSS',
                'loss_ratio': abs(loss_ratio),
                'message': f"触发止损：亏损{abs(loss_ratio)*100:.1f}% > {self.stop_loss_ratio*100}%"
            }
        return {'triggered': False, 'action': 'HOLD'}
    
    def check_take_profit(self, ts_code: str, cost_price: float, current_price: float) -> Dict[str, Any]:
        """检查是否需要止盈"""
        profit_ratio = (current_price - cost_price) / cost_price if cost_price > 0 else 0
        
        if profit_ratio > self.take_profit_ratio:
            return {
                'triggered': True,
                'action': 'TAKE_PROFIT',
                'profit_ratio': profit_ratio,
                'message': f"触发止盈：盈利{profit_ratio*100:.1f}% > {self.take_profit_ratio*100}%"
            }
        return {'triggered': False, 'action': 'HOLD'}
