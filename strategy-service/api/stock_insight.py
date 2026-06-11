"""
Stock Insight 选股API路由
提供主板精选、理性10选股、ML增强扫描的API接口
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import Optional, List, Dict, Any
import logging
import uuid
import time
from datetime import datetime
from pydantic import BaseModel, Field

from services.stock_insight_engine import get_stock_insight_engine
from services.data_service import DataService
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存存储扫描结果（生产环境应使用Redis）
_scan_results = {}
_scan_tasks = {}


# ==================== 请求/响应模型 ====================

class ScanRequest(BaseModel):
    """扫描请求模型"""
    scan_type: str = Field(
        default="mainboard",
        description="扫描类型: mainboard(主板精选), rational(理性10选股), ml(ML增强扫描)"
    )
    top_n: int = Field(default=10, ge=1, le=50, description="返回股票数量")
    owned_codes: Optional[List[str]] = Field(default=None, description="已持仓代码列表")
    mode: Optional[str] = Field(default="mainboard", description="ML扫描模式: mainboard(主板)或all(全市场)")


class ScanResult(BaseModel):
    """扫描结果模型"""
    scan_id: str = Field(description="扫描任务ID")
    scan_type: str = Field(description="扫描类型")
    status: str = Field(description="状态: pending/running/completed/failed")
    created_at: str = Field(description="创建时间")
    completed_at: Optional[str] = Field(default=None, description="完成时间")
    total_stocks: Optional[int] = Field(default=0, description="选中股票数量")
    stocks: Optional[List[Dict[str, Any]]] = Field(default=None, description="股票列表")
    error: Optional[str] = Field(default=None, description="错误信息")


class LatestResult(BaseModel):
    """最新结果模型"""
    scan_type: str = Field(description="扫描类型")
    timestamp: str = Field(description="结果时间")
    stocks: List[Dict[str, Any]] = Field(description="股票列表")
    total: int = Field(description="股票数量")


# ==================== API路由 ====================

@router.post("/scan", response_model=ScanResult)
async def trigger_stock_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks
):
    """
    触发Stock Insight选股扫描
    
    支持三种扫描类型：
    - mainboard: 主板精选（惩罚机制+板块去重）
    - rational: 理性10选股（长线5只+短线5只）
    - ml: ML增强扫描（两阶段回退+ML预测）
    
    示例请求：
    ```json
    {
        "scan_type": "mainboard",
        "top_n": 10,
        "owned_codes": ["600519", "000858"],
        "mode": "mainboard"
    }
    ```
    """
    scan_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    # 初始化结果存储
    _scan_results[scan_id] = {
        "scan_id": scan_id,
        "scan_type": request.scan_type,
        "status": "pending",
        "created_at": created_at,
        "completed_at": None,
        "total_stocks": 0,
        "stocks": None,
        "error": None
    }
    
    # 在后台执行扫描任务
    background_tasks.add_task(
        _execute_scan_task,
        scan_id=scan_id,
        scan_type=request.scan_type,
        top_n=request.top_n,
        owned_codes=request.owned_codes,
        mode=request.mode
    )
    
    logger.info(f"创建扫描任务: {scan_id}, 类型: {request.scan_type}")
    
    return ScanResult(
        scan_id=scan_id,
        scan_type=request.scan_type,
        status="pending",
        created_at=created_at
    )


@router.get("/results/{scan_id}", response_model=ScanResult)
async def get_scan_result(scan_id: str):
    """
    查询扫描结果
    
    根据scan_id获取扫描任务的执行结果
    """
    if scan_id not in _scan_results:
        raise HTTPException(status_code=404, detail=f"扫描任务不存在: {scan_id}")
    
    result = _scan_results[scan_id]
    
    # 如果任务还在运行，检查是否超时
    if result["status"] == "running":
        created_time = datetime.fromisoformat(result["created_at"])
        elapsed = (datetime.now() - created_time).total_seconds()
        
        if elapsed > 300:  # 5分钟超时
            result["status"] = "failed"
            result["error"] = "扫描任务执行超时"
            result["completed_at"] = datetime.now().isoformat()
    
    return ScanResult(**result)


@router.get("/latest", response_model=LatestResult)
async def get_latest_scan_results(
    scan_type: str = Query(
        default="mainboard",
        description="扫描类型: mainboard/rational/ml"
    ),
    limit: int = Query(default=10, ge=1, le=50, description="返回股票数量")
):
    """
    获取最新选股结果
    
    返回最近一次成功的扫描结果
    """
    try:
        # 查找最近的成功扫描
        latest_scan = None
        latest_time = None
        
        for scan_id, result in _scan_results.items():
            if (result["scan_type"] == scan_type and 
                result["status"] == "completed" and 
                result["stocks"]):
                
                completed_at = result["completed_at"]
                if completed_at and (latest_time is None or completed_at > latest_time):
                    latest_time = completed_at
                    latest_scan = result
        
        if latest_scan:
            stocks = latest_scan["stocks"][:limit]
            return LatestResult(
                scan_type=scan_type,
                timestamp=latest_scan["completed_at"],
                stocks=stocks,
                total=len(stocks)
            )
        
        # 如果没有历史结果，执行实时扫描
        logger.info(f"无历史{scan_type}结果，执行实时扫描")
        
        # 初始化数据服务和引擎
        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        engine = get_stock_insight_engine(ds)
        
        if not engine:
            raise HTTPException(status_code=500, detail="选股引擎初始化失败")
        
        # 执行实时扫描
        stocks = await _execute_real_time_scan(engine, scan_type, limit)
        
        return LatestResult(
            scan_type=scan_type,
            timestamp=datetime.now().isoformat(),
            stocks=stocks,
            total=len(stocks)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取最新结果失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取最新结果失败: {str(e)}")


@router.get("/types")
async def get_scan_types():
    """
    获取支持的扫描类型列表
    
    返回所有可用的选股算法类型
    """
    return {
        "code": 0,
        "data": [
            {
                "type": "mainboard",
                "name": "主板精选",
                "description": "基于惩罚机制和板块去重的主板精选算法",
                "parameters": {
                    "top_n": "返回股票数量(1-50)",
                    "owned_codes": "已持仓代码列表(可选)"
                }
            },
            {
                "type": "rational",
                "name": "理性10选股",
                "description": "长线5只(基本面+低波动) + 短线5只(动量+技术+量能)",
                "parameters": {
                    "top_n": "返回股票数量(默认10)"
                }
            },
            {
                "type": "ml",
                "name": "ML增强扫描",
                "description": "两阶段回退筛选 + ML集成预测",
                "parameters": {
                    "top_n": "返回股票数量(1-50)",
                    "mode": "扫描模式: mainboard(主板)或all(全市场)"
                }
            }
        ]
    }


# ==================== 后台任务 ====================

async def _execute_scan_task(
    scan_id: str,
    scan_type: str,
    top_n: int,
    owned_codes: List[str] = None,
    mode: str = "mainboard"
):
    """执行扫描任务（后台运行）"""
    try:
        # 更新状态为运行中
        _scan_results[scan_id]["status"] = "running"
        logger.info(f"开始执行扫描任务: {scan_id}")
        
        # 初始化数据服务和引擎
        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        engine = get_stock_insight_engine(ds)
        
        if not engine:
            raise Exception("选股引擎初始化失败")
        
        # 根据扫描类型执行不同的算法
        stocks = []
        
        if scan_type == "mainboard":
            stocks = engine.scan_mainboard(
                top_n=top_n,
                owned_codes=owned_codes
            )
            
        elif scan_type == "rational":
            stocks = engine.scan_rational(top_n=top_n)
            
        elif scan_type == "ml":
            stocks = engine.scan_ml(
                mode=mode,
                top_n=top_n
            )
            
        else:
            raise ValueError(f"不支持的扫描类型: {scan_type}")
        
        # 更新结果
        _scan_results[scan_id].update({
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "total_stocks": len(stocks),
            "stocks": stocks,
            "error": None
        })
        
        logger.info(f"扫描任务完成: {scan_id}, 选中{len(stocks)}只股票")
        
    except Exception as e:
        logger.error(f"扫描任务失败: {scan_id}, 错误: {e}")
        
        # 更新失败状态
        _scan_results[scan_id].update({
            "status": "failed",
            "completed_at": datetime.now().isoformat(),
            "total_stocks": 0,
            "stocks": None,
            "error": str(e)
        })


async def _execute_real_time_scan(engine, scan_type: str, limit: int) -> List[Dict]:
    """执行实时扫描"""
    try:
        if scan_type == "mainboard":
            stocks = engine.scan_mainboard(top_n=limit)
        elif scan_type == "rational":
            stocks = engine.scan_rational(top_n=limit)
        elif scan_type == "ml":
            stocks = engine.scan_ml(mode="mainboard", top_n=limit)
        else:
            stocks = []
        
        return stocks
        
    except Exception as e:
        logger.error(f"实时扫描失败: {e}")
        return []


# ==================== 定时清理任务 ====================

def cleanup_old_scans():
    """清理旧的扫描结果"""
    try:
        current_time = datetime.now()
        scan_ids_to_remove = []
        
        for scan_id, result in _scan_results.items():
            created_at = datetime.fromisoformat(result["created_at"])
            age_hours = (current_time - created_at).total_seconds() / 3600
            
            # 清理24小时前的扫描结果
            if age_hours > 24:
                scan_ids_to_remove.append(scan_id)
        
        for scan_id in scan_ids_to_remove:
            del _scan_results[scan_id]
        
        if scan_ids_to_remove:
            logger.info(f"清理了{len(scan_ids_to_remove)}个旧的扫描结果")
            
    except Exception as e:
        logger.warning(f"清理扫描结果失败: {e}")


# ==================== 健康检查 ====================

@router.get("/health")
async def health_check():
    """健康检查接口"""
    try:
        # 检查数据服务
        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        
        # 检查引擎
        engine = get_stock_insight_engine(ds)
        
        return {
            "status": "healthy",
            "data_service": "available" if ds else "unavailable",
            "engine": "available" if engine else "unavailable",
            "active_scans": len([r for r in _scan_results.values() if r["status"] == "running"]),
            "total_results": len(_scan_results)
        }
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }