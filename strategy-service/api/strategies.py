"""
策略市场 API
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 请求/响应模型 ==========

class StrategyCreate(BaseModel):
    name: str
    description: str = ""
    params: Dict[str, Any] = {}

class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    status: Optional[str] = None

class CompareRequest(BaseModel):
    strategy_ids: List[str]
    ts_code: str = "000001"


# ========== 路由 ==========

@router.get("/")
async def list_strategies(
    type: Optional[str] = Query(None, description="过滤类型: builtin/custom"),
    status: str = Query("active", description="过滤状态: active/draft/archived")
):
    """策略列表"""
    from services.strategy_market import strategy_market
    result = strategy_market.list_strategies(type_filter=type, status=status)
    return {"success": True, "data": result, "total": len(result)}


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str):
    """策略详情"""
    from services.strategy_market import strategy_market
    result = strategy_market.get_strategy(strategy_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
    return {"success": True, "data": result}


@router.post("/")
async def create_strategy(body: StrategyCreate):
    """创建自定义策略"""
    from services.strategy_market import strategy_market
    try:
        result = strategy_market.create_strategy(
            name=body.name, params=body.params, description=body.description
        )
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{strategy_id}")
async def update_strategy(strategy_id: str, body: StrategyUpdate):
    """更新策略"""
    from services.strategy_market import strategy_market
    updates = {k: v for k, v in body.dict().items() if v is not None}
    result = strategy_market.update_strategy(strategy_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
    return {"success": True, "data": result}


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str):
    """删除策略（内置策略不可删除）"""
    from services.strategy_market import strategy_market
    try:
        ok = strategy_market.delete_strategy(strategy_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
        return {"success": True, "message": f"策略 {strategy_id} 已删除"}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{strategy_id}/backtest")
async def backtest_strategy(strategy_id: str, ts_code: str = Query("000001")):
    """对指定策略运行回测"""
    from services.strategy_market import strategy_market
    try:
        result = strategy_market.backtest_strategy(strategy_id, ts_code)
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compare")
async def compare_strategies(body: CompareRequest):
    """多策略对比回测"""
    from services.strategy_market import strategy_market
    try:
        result = strategy_market.compare_strategies(body.strategy_ids, body.ts_code)
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ranking")
async def strategy_ranking(metric: str = Query("sharpe", description="排序指标: sharpe/total_return/win_rate")):
    """策略排行榜"""
    from services.strategy_market import strategy_market
    result = strategy_market.get_ranking(metric=metric)
    return {"success": True, "data": result}
