"""
交易信号API路由 - 已接入数据库
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Query
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session

from models.database import get_db
from repositories import signal_repo

router = APIRouter()


@router.post("/generate/{ts_code}")
async def generate_signal(ts_code: str, background_tasks: BackgroundTasks,
                          db: Session = Depends(get_db)):
    """
    为指定股票生成交易信号并保存到数据库
    例：POST /api/v1/signals/generate/600519.SH
    """
    try:
        from services.multi_agent import MultiAgentTradingSystem, StockData
        from services.data_service import DataService
        from core.config import settings

        ds = DataService(redis_url=settings.REDIS_URL)
        quote = ds.get_stock_realtime_quote(ts_code)

        if not quote or quote.get('price', 0) == 0:
            raise HTTPException(status_code=404, detail=f"未找到股票：{ts_code}")

        indices = ds.get_index_realtime_quote()
        market_context = {
            "indices": indices,
            "market_trend": "neutral",
            "total_assets": 30000.0,
            "total_positions": 0,
            "positions": {}
        }

        mas = MultiAgentTradingSystem()
        stock_data = StockData(
            ts_code=ts_code,
            name=quote.get('name', ''),
            current_price=quote.get('price', 0),
            open=quote.get('open', 0),
            high=quote.get('high', 0),
            low=quote.get('low', 0),
            volume=quote.get('volume', 0),
            amount=quote.get('amount', 0),
            change=quote.get('change', 0),
            pct_change=quote.get('pct_change', 0)
        )

        decision = mas.analyze_stock(stock_data, market_context)

        # 保存信号到数据库
        signal_data = {
            "ts_code": ts_code.upper(),
            "signal_type": decision.action,
            "signal_strength": decision.confidence / 100.0 if hasattr(decision, 'confidence') else None,
            "strategy_name": "multi-agent",
            "strategy_version": "2.0",
            "confidence_score": decision.confidence,
            "target_price": float(decision.target_price) if hasattr(decision, 'target_price') and decision.target_price else None,
            "stop_loss_price": float(decision.stop_loss) if hasattr(decision, 'stop_loss') and decision.stop_loss else None,
            "take_profit_price": float(decision.take_profit) if hasattr(decision, 'take_profit') and decision.take_profit else None,
            "generated_at": datetime.now(),
        }
        saved = signal_repo.save_signal(db, signal_data)

        # 更新 Prometheus 指标
        from main import signals_generated_today, signals_buy_count, signals_sell_count, trading_signals
        signals_generated_today.inc()
        if decision.action.upper() == 'BUY':
            signals_buy_count.inc()
        elif decision.action.upper() == 'SELL':
            signals_sell_count.inc()
        trading_signals.labels(
            ts_code=ts_code, action=decision.action,
            reason=(decision.reasoning or '')[:50]
        ).set(decision.confidence or 50)

        # 高置信度信号推送飞书告警 (confidence > 70 即 0.7)
        if decision.confidence and decision.confidence > 70:
            try:
                from services.feishu_alert import get_alert_service
                alert = get_alert_service(settings.FEISHU_WEBHOOK)
                if alert and alert.enabled:
                    await alert.send_signal_alert(
                        ts_code=ts_code,
                        action=decision.action,
                        price=quote.get('price', 0),
                        confidence=decision.confidence,
                        reason=getattr(decision, 'reasoning', '')[:200] or '高置信度信号'
                    )
            except Exception as alert_e:
                logger.warning(f"信号告警推送失败(非致命): {alert_e}")

        return {
            "code": 0,
            "data": {
                "ts_code": decision.ts_code,
                "action": decision.action,
                "confidence": decision.confidence,
                "reasoning": decision.reasoning,
                "risk_assessment": decision.risk_assessment,
                "target_price": decision.target_price,
                "stop_loss": decision.stop_loss,
                "take_profit": decision.take_profit,
                "timestamp": decision.timestamp.isoformat(),
                "signal_id": saved["signal_id"],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_signal_history(
    ts_code: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db)
):
    """查询历史交易信号（从数据库读取）"""
    try:
        signals = signal_repo.get_history(db, ts_code=ts_code, limit=limit)
        return {"code": 0, "data": signals, "total": len(signals), "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/latest/{ts_code}")
async def get_latest_signal(ts_code: str, db: Session = Depends(get_db)):
    """获取某只股票的最新交易信号（从数据库读取）"""
    try:
        signal = signal_repo.get_latest(db, ts_code)
        return {"code": 0, "data": signal}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
