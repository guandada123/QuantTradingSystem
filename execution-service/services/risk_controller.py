"""
风险控制器
交易风险检查、止损止盈监控、仓位限制、熔断机制、DB持久化
"""

import uuid
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.config import settings

logger = logging.getLogger(__name__)


def _fire_alert(coro):
    """安全地在事件循环中调度告警协程（fire-and-forget）"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        logger.debug(f"告警调度失败(非关键): {e}")

DEFAULT_ACCOUNT_ID = "REAL_001"


class CircuitBreaker:
    """交易熔断器 — 连续止损后自动暂停交易"""

    def __init__(self, max_consecutive_losses: int = 3, cooldown_minutes: int = 30):
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self._consecutive_losses = 0
        self._is_open = False
        self._opened_at: Optional[datetime] = None

    def record_loss(self):
        """记录一次止损事件"""
        self._consecutive_losses += 1
        if self._consecutive_losses >= self.max_consecutive_losses:
            self._is_open = True
            self._opened_at = datetime.now()
            logger.warning(f"熔断触发！连续{self._consecutive_losses}次止损，暂停交易{self.cooldown_minutes}分钟")

    def record_profit(self):
        """记录盈利，重置计数"""
        self._consecutive_losses = 0

    def is_allowed(self) -> bool:
        """检查是否允许交易"""
        if not self._is_open:
            return True
        if self._opened_at is None:
            return True
        elapsed = (datetime.now() - self._opened_at).total_seconds() / 60
        if elapsed >= self.cooldown_minutes:
            # 冷却到期，自动恢复
            self._is_open = False
            self._consecutive_losses = 0
            self._opened_at = None
            logger.info("熔断冷却结束，恢复交易")
            return True
        return False

    def reset(self):
        """手动重置熔断器"""
        self._consecutive_losses = 0
        self._is_open = False
        self._opened_at = None
        logger.info("熔断器已手动重置")

    @property
    def status(self) -> Dict[str, Any]:
        return {
            'is_open': self._is_open,
            'consecutive_losses': self._consecutive_losses,
            'opened_at': self._opened_at.isoformat() if self._opened_at else None,
            'cooldown_remaining_minutes': max(0, round((self.cooldown_minutes -
                (datetime.now() - self._opened_at).total_seconds() / 60), 1)) if self._opened_at and self._is_open else 0
        }

# 全局熔断器实例
circuit_breaker = CircuitBreaker(
    max_consecutive_losses=settings.CB_CONSECUTIVE_LOSSES,
    cooldown_minutes=settings.CB_COOLDOWN_MINUTES
)


class RiskController:
    """交易风险控制器"""

    def __init__(
        self,
        db: Optional[Session] = None,
        max_position_ratio: float = 0.30,
        max_total_positions: int = 3,
        stop_loss_ratio: float = 0.08,
        take_profit_ratio: float = 0.30,
        max_daily_loss: float = 0.05,
        account_id: str = DEFAULT_ACCOUNT_ID
    ):
        self.db = db
        self.max_position_ratio = max_position_ratio
        self.max_total_positions = max_total_positions
        self.stop_loss_ratio = stop_loss_ratio
        self.take_profit_ratio = take_profit_ratio
        self.max_daily_loss = max_daily_loss
        self.account_id = account_id

    def pre_trade_check(
        self,
        ts_code: str,
        direction: str,
        quantity: int,
        price: float
    ) -> Dict[str, Any]:
        """
        交易前风控检查（从DB查询真实持仓和账户数据）
        返回：{allowed: bool, risk_level: str, risks: [], recommendation: str}
        """
        risks = []

        if not self.db:
            return {'allowed': True, 'risk_level': 'LOW', 'risks': [], 'recommendation': 'PASS',
                    'timestamp': datetime.now().isoformat()}

        # 获取账户信息
        account = self.db.execute(text(
            "SELECT total_assets, available_cash, market_value FROM accounts WHERE account_id = :aid"
        ), {'aid': self.account_id}).mappings().fetchone()

        if not account:
            risks.append(f"账户 {self.account_id} 不存在")
            return self._build_result(risks)

        total_assets = float(account['total_assets'])
        available_cash = float(account['available_cash'])

        # 获取所有持仓
        positions = self.db.execute(text(
            "SELECT ts_code, total_quantity, market_value, cost_price, current_price FROM positions"
        )).mappings().fetchall()
        position_count = len(positions)

        if direction == 'BUY':
            trade_amount = price * quantity

            # 1. 资金充足性检查
            if trade_amount > available_cash:
                risks.append(f"资金不足：需要{trade_amount:.2f}，可用{available_cash:.2f}")

            # 2. 单只仓位比例检查
            existing_mv = 0
            for p in positions:
                if p['ts_code'] == ts_code:
                    existing_mv = float(p['market_value'] or 0)
                    break
            new_ratio = (existing_mv + trade_amount) / total_assets if total_assets > 0 else 1
            if new_ratio > self.max_position_ratio:
                risks.append(f"仓位超标：{new_ratio*100:.1f}% > {self.max_position_ratio*100}%")

            # 3. 持仓数量检查
            is_new_position = ts_code not in [p['ts_code'] for p in positions]
            if is_new_position and position_count >= self.max_total_positions:
                risks.append(f"持仓数量超标：当前{position_count}只 >= 上限{self.max_total_positions}只")

        elif direction == 'SELL':
            # 检查是否有足够持仓可卖
            pos = self.db.execute(text(
                "SELECT available_quantity FROM positions WHERE ts_code = :tc"
            ), {'tc': ts_code}).mappings().fetchone()
            if not pos or int(pos['available_quantity']) < quantity:
                avail = int(pos['available_quantity']) if pos else 0
                risks.append(f"持仓不足：需要卖出{quantity}股，可用{avail}股")

        # 4. 当日亏损检查
        day_pnl = self.db.execute(text(
            "SELECT day_profit_loss FROM accounts WHERE account_id = :aid"
        ), {'aid': self.account_id}).mappings().fetchone()
        if day_pnl and day_pnl['day_profit_loss'] is not None:
            day_loss_ratio = abs(float(day_pnl['day_profit_loss'])) / total_assets if total_assets > 0 else 0
            if float(day_pnl['day_profit_loss']) < 0 and day_loss_ratio > self.max_daily_loss:
                risks.append(f"当日亏损超标：{day_loss_ratio*100:.1f}% > {self.max_daily_loss*100}%")

        result = self._build_result(risks)

        # 如果有风险，记录风险事件
        if risks:
            self.log_risk_event(
                event_type='PRE_TRADE_CHECK',
                severity=result['risk_level'],
                ts_code=ts_code,
                description='; '.join(risks),
                action_taken=result['recommendation']
            )
            # 飞书告警：风控拒绝交易
            if not result['allowed']:
                try:
                    from services.feishu_alert import get_alert_service
                    alert_svc = get_alert_service()
                    _fire_alert(alert_svc.send_risk_triggered(
                        ts_code, "交易风控拦截",
                        f"方向={direction}, 数量={quantity}, 原因: {'; '.join(risks)}"
                    ))
                except Exception as e:
                    logger.debug(f"风控告警发送失败: {e}")

        return result

    def check_trade_risk(
        self,
        ts_code: str,
        action: str,
        quantity: int,
        account_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查交易风险（兼容旧接口，使用传入的account_info）
        返回：{allowed: bool, risk_level: str, risks: [], recommendation: str}
        """
        risks = []

        if action == 'BUY':
            total_assets = account_info.get('total_assets', 0)
            current_position = account_info.get('positions', {}).get(ts_code, {})
            current_ratio = current_position.get('market_value', 0) / total_assets if total_assets > 0 else 0

            if current_ratio > self.max_position_ratio:
                risks.append(f"仓位超标：{current_ratio*100:.1f}% > {self.max_position_ratio*100}%")

        if action == 'BUY':
            total_positions = account_info.get('total_positions', 0)
            if total_positions >= self.max_total_positions and ts_code not in account_info.get('positions', {}):
                risks.append(f"持仓数量超标：{total_positions} > {self.max_total_positions}")

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
                'ts_code': ts_code,
                'loss_ratio': abs(loss_ratio),
                'message': f"触发止损：亏损{abs(loss_ratio)*100:.1f}% > {self.stop_loss_ratio*100}%"
            }
        return {'triggered': False, 'action': 'HOLD', 'ts_code': ts_code}

    def check_take_profit(self, ts_code: str, cost_price: float, current_price: float) -> Dict[str, Any]:
        """检查是否需要止盈"""
        profit_ratio = (current_price - cost_price) / cost_price if cost_price > 0 else 0

        if profit_ratio > self.take_profit_ratio:
            return {
                'triggered': True,
                'action': 'TAKE_PROFIT',
                'ts_code': ts_code,
                'profit_ratio': profit_ratio,
                'message': f"触发止盈：盈利{profit_ratio*100:.1f}% > {self.take_profit_ratio*100}%"
            }
        return {'triggered': False, 'action': 'HOLD', 'ts_code': ts_code}

    def monitor_positions(self) -> List[Dict[str, Any]]:
        """监控所有持仓的止损/止盈 — 如配置自动执行则自动平仓"""
        alerts = []
        executed = []

        if not self.db:
            return alerts

        positions = self.db.execute(text(
            "SELECT ts_code, cost_price, current_price, total_quantity, available_quantity FROM positions WHERE total_quantity > 0"
        )).mappings().fetchall()

        for pos in positions:
            ts_code = pos['ts_code']
            cost_price = float(pos['cost_price'])
            current_price = float(pos['current_price']) if pos['current_price'] else cost_price
            total_quantity = int(pos['total_quantity'])
            available_quantity = int(pos.get('available_quantity', total_quantity))

            # 止损检查
            sl_result = self.check_stop_loss(ts_code, cost_price, current_price)
            if sl_result['triggered']:
                alerts.append(sl_result)
                self.log_risk_event(
                    event_type='STOP_LOSS',
                    severity='HIGH',
                    ts_code=ts_code,
                    description=sl_result['message'],
                    threshold_value=self.stop_loss_ratio,
                    actual_value=sl_result['loss_ratio']
                )

                # 飞书告警
                try:
                    from services.feishu_alert import get_alert_service
                    alert_svc = get_alert_service()
                    _fire_alert(alert_svc.send_risk_triggered(
                        ts_code, "止损触发", sl_result['message']
                    ))
                    _fire_alert(alert_svc.send_position_alert(
                        {"ts_code": ts_code, "cost_price": cost_price,
                         "current_price": current_price, "quantity": total_quantity},
                        "止损触发"
                    ))
                except Exception as e:
                    logger.debug(f"止损告警发送失败: {e}")

                # 自动执行平仓
                if settings.AUTO_EXECUTE_STOP_LOSS and available_quantity > 0:
                    try:
                        from services.position_manager import PositionManager
                        pm = PositionManager(db=self.db, account_id=self.account_id,
                                            commission_rate=0.0003, min_commission=5.0, tax_rate=0.001)
                        close_result = pm.close_position(
                            ts_code=ts_code,
                            quantity=available_quantity,
                            price=current_price
                        )
                        if close_result['success']:
                            executed.append({
                                'ts_code': ts_code,
                                'action': 'STOP_LOSS_EXECUTED',
                                'quantity': available_quantity,
                                'price': current_price,
                                'pnl': close_result.get('profit_loss', 0)
                            })
                            circuit_breaker.record_loss()
                            self.log_risk_event(
                                event_type='STOP_LOSS_EXECUTED',
                                severity='HIGH',
                                ts_code=ts_code,
                                description=f"止损自动平仓: {available_quantity}股 @{current_price}",
                                action_taken='AUTO_CLOSE'
                            )
                            logger.info(f"止损自动平仓: {ts_code} {available_quantity}股 @{current_price}")
                        else:
                            logger.error(f"止损平仓失败: {ts_code} - {close_result.get('error')}")
                    except Exception as e:
                        logger.error(f"止损平仓异常: {ts_code} - {e}")

            # 止盈检查
            tp_result = self.check_take_profit(ts_code, cost_price, current_price)
            if tp_result['triggered']:
                alerts.append(tp_result)
                self.log_risk_event(
                    event_type='TAKE_PROFIT',
                    severity='MEDIUM',
                    ts_code=ts_code,
                    description=tp_result['message'],
                    threshold_value=self.take_profit_ratio,
                    actual_value=tp_result['profit_ratio']
                )

                # 飞书告警
                try:
                    from services.feishu_alert import get_alert_service
                    alert_svc = get_alert_service()
                    _fire_alert(alert_svc.send_position_alert(
                        {"ts_code": ts_code, "cost_price": cost_price,
                         "current_price": current_price, "quantity": total_quantity},
                        "止盈触发"
                    ))
                except Exception as e:
                    logger.debug(f"止盈告警发送失败: {e}")

                # 自动执行平仓
                if settings.AUTO_EXECUTE_TAKE_PROFIT and available_quantity > 0:
                    try:
                        from services.position_manager import PositionManager
                        pm = PositionManager(db=self.db, account_id=self.account_id,
                                            commission_rate=0.0003, min_commission=5.0, tax_rate=0.001)
                        close_result = pm.close_position(
                            ts_code=ts_code,
                            quantity=available_quantity,
                            price=current_price
                        )
                        if close_result['success']:
                            executed.append({
                                'ts_code': ts_code,
                                'action': 'TAKE_PROFIT_EXECUTED',
                                'quantity': available_quantity,
                                'price': current_price,
                                'pnl': close_result.get('profit_loss', 0)
                            })
                            circuit_breaker.record_profit()
                            self.log_risk_event(
                                event_type='TAKE_PROFIT_EXECUTED',
                                severity='MEDIUM',
                                ts_code=ts_code,
                                description=f"止盈自动平仓: {available_quantity}股 @{current_price}",
                                action_taken='AUTO_CLOSE'
                            )
                            logger.info(f"止盈自动平仓: {ts_code} {available_quantity}股 @{current_price}")
                    except Exception as e:
                        logger.error(f"止盈平仓异常: {ts_code} - {e}")

        return {'alerts': alerts, 'executed': executed, 'total_alerts': len(alerts),
                'total_executed': len(executed)}

    def log_risk_event(
        self,
        event_type: str,
        severity: str,
        ts_code: Optional[str] = None,
        description: Optional[str] = None,
        action_taken: Optional[str] = None,
        threshold_value: Optional[float] = None,
        actual_value: Optional[float] = None
    ):
        """将风险事件写入 risk_events 表"""
        if not self.db:
            logger.warning(f"风险事件(无DB): [{severity}] {event_type} - {description}")
            return

        self.db.execute(text("""
            INSERT INTO risk_events (event_type, severity, ts_code, account_id,
                                     description, threshold_value, actual_value, action_taken, created_at)
            VALUES (:etype, :severity, :tc, :aid, :desc, :thresh, :actual, :action, CURRENT_TIMESTAMP)
        """), {
            'etype': event_type,
            'severity': severity,
            'tc': ts_code,
            'aid': self.account_id,
            'desc': description,
            'thresh': threshold_value,
            'actual': actual_value,
            'action': action_taken
        })
        self.db.commit()
        logger.info(f"风险事件记录: [{severity}] {event_type} {ts_code or ''} - {description}")

    def get_risk_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """查询风险事件列表"""
        if not self.db:
            return []

        rows = self.db.execute(text("""
            SELECT event_type, severity, ts_code, description, action_taken,
                   threshold_value, actual_value, is_resolved, created_at
            FROM risk_events
            ORDER BY created_at DESC LIMIT :limit
        """), {'limit': limit}).mappings().fetchall()

        return [dict(r) for r in rows]

    def _build_result(self, risks: List[str]) -> Dict[str, Any]:
        """构建风控检查结果"""
        risk_level = 'HIGH' if len(risks) > 1 else ('MEDIUM' if len(risks) == 1 else 'LOW')
        allowed = risk_level != 'HIGH'
        return {
            'allowed': allowed,
            'risk_level': risk_level,
            'risks': risks,
            'recommendation': 'PASS' if allowed else 'BLOCK',
            'timestamp': datetime.now().isoformat()
        }
