"""
回测API路由 v2 - 对接 EnhancedBacktestEngine (backtest_engine_v2)
前端 dashboard/backtest.html 通过 POST /api/v1/backtest/run JSON body 调用

前端请求格式兼容：{ts_code, strategy, strategies, start_date, end_date, initial_cash/cash, params: {slippage, commission_rate}}
"""

from __future__ import annotations

import asyncio
import logging
import re
import traceback
from datetime import date, datetime

from fastapi import APIRouter, Request
from models.database import get_db_session
from models.enums import StrategyName
from pydantic import BaseModel, ConfigDict, Field, field_validator
from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine
from services.data_fetcher import fetch_kline_eastmoney, fetch_kline_tencent
from services.param_grids import DEFAULT_PARAM_GRIDS
from services.result_persistence import ResultPersistence

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Pydantic 请求模型 — 输入参数校验增强 (#137)
# ============================================================


class BacktestRequestBase(BaseModel):
    """回测请求基类 — 共享字段与校验器，消除 Pydantic DRY 重复"""

    model_config = ConfigDict(validate_default=True)

    ts_code: str = Field(default="", description="股票代码")
    strategy: StrategyName = Field(default=StrategyName.MA_CROSS, description="策略名称")
    start_date: str = Field(default="", description="起始日期 YYYY-MM-DD")
    end_date: str = Field(default="", description="结束日期 YYYY-MM-DD")
    initial_cash: float | None = Field(default=None, description="初始资金")
    cash: float | None = Field(default=None, description="初始资金（兼容旧字段）")
    params: dict = Field(default_factory=dict, description="策略参数 {slippage, commission_rate}")
    benchmark: str = Field(default="000300.SH", description="基准指数")

    @field_validator("ts_code")
    @classmethod
    def validate_ts_code(cls, v: str) -> str:
        if not v:
            raise ValueError("请提供股票代码 ts_code")
        v = v.strip()
        if not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", v):
            raise ValueError(f"代码格式无效: {v}，应为 000001.SZ / 600000.SH / 430047.BJ")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_dates(cls, v: str) -> str:
        stripped = v.replace("-", "")
        if not stripped or len(stripped) != 8:
            raise ValueError(f"日期格式无效: {v}，应为 YYYY-MM-DD")
        try:
            datetime.strptime(stripped, "%Y%m%d")
        except ValueError:
            raise ValueError(f"日期格式无效: {v}")
        return stripped

    @field_validator("benchmark")
    @classmethod
    def validate_benchmark(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", v.strip()):
            raise ValueError(f"基准代码格式无效: {v}")
        return v.strip()


class BacktestRunRequest(BacktestRequestBase):
    """回测执行请求参数"""

    strategies: list[StrategyName] | None = Field(default=None, description="策略列表（多值）")


class WalkForwardRequest(BacktestRequestBase):
    """Walk-Forward 请求参数"""

    train_days: int = Field(default=126, description="训练期天数")
    test_days: int = Field(default=42, description="测试期天数")
    step_days: int = Field(default=42, description="滑动步长")
    param_grid: dict[str, list] | None = Field(default=None, description="自定义参数搜索空间，不传则使用默认网格")


# ============================================================
# 异步超时保护 — 同步 urllib 调用包装 (#138)
# ============================================================


async def _run_sync_with_timeout(func, timeout_secs: float, *args, **kwargs):
    """在 executor 中运行同步函数，带超时保护

    Args:
        func: 同步函数
        timeout_secs: 超时秒数
        args, kwargs: 传给 func 的参数

    Returns:
        func 的返回值

    Raises:
        asyncio.TimeoutError: 超时未返回
    """
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
        timeout=timeout_secs,
    )


# ============================================================
# 响应构建辅助函数 — 消除 metrics/curves/trades 重复编写 (#CODE-03)
# ============================================================


def _build_response_metrics(
    *,
    total_return=None, annual_return=None, sharpe_ratio=None,
    max_drawdown=None, win_rate=None, profit_loss_ratio=None,
    total_trades=None, alpha=None, beta=None, volatility=None,
    calmar_ratio=None, sortino_ratio=None,
) -> dict:
    """构建标准化的 metrics 响应字典（双字段别名）

    统一 POST /run 和 GET /{id} 的 metrics 格式。
    空值保持 None，非空值按 4 或 6 位小数舍入。
    """
    def _r6(v):
        return round(v, 6) if v is not None else None

    def _r4(v):
        return round(v, 4) if v is not None else None

    return {
        "total_return": _r6(total_return),
        "annual_return": _r6(annual_return),
        "sharpe": _r4(sharpe_ratio),
        "sharpe_ratio": _r4(sharpe_ratio),
        "max_drawdown": _r6(max_drawdown),
        "win_rate": _r6(win_rate),
        "profit_loss_ratio": _r4(profit_loss_ratio),
        "profit_factor": _r4(profit_loss_ratio),
        "trade_count": total_trades,
        "total_trades": total_trades,
        "alpha": _r6(alpha),
        "beta": _r6(beta),
        "volatility": _r6(volatility),
        "calmar_ratio": _r4(calmar_ratio),
        "sortino_ratio": _r4(sortino_ratio),
    }


def _convert_trades(trades: list) -> list[dict]:
    """将 TradeRecord 列表转换为前端期望的 dict 列表"""
    result = []
    for t in trades:
        result.append(
            {
                "date": t.date,
                "stock": t.ts_code,
                "direction": "买入" if t.direction == "BUY" else "卖出",
                "price": round(t.price, 2),
                "quantity": t.quantity,
                "amount": round(t.amount, 2),
                "pnl": round(t.pnl, 2),
                "hold_days": t.hold_days or "",
            }
        )
    return result


# ============================================================
# DB 持久化服务 — 将回测结果保存到 backtest_results 表 (#136, #CODE-02)
# ============================================================

_persistence = ResultPersistence()


# ============================================================
# API 端点
# ============================================================


@router.post("/run")
async def run_backtest(request: Request):
    """执行单/多策略回测（V2引擎）

    前端发送格式（兼容多种）:
    {
      "ts_code": "000333.SZ",
      "strategy": "ma-cross",  // 或 "strategies": ["ma-cross", "breakout"]
      "start_date": "2025-06-12",  // YYYY-MM-DD
      "end_date": "2026-06-12",
      "initial_cash": 100000.0,
      "params": {"slippage": 0.001, "commission_rate": 0.00025}
    }
    """
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "error": "请求体JSON解析失败"}

    # Pydantic 参数校验
    try:
        p = BacktestRunRequest(**body)
    except Exception as e:
        return {"success": False, "error": f"参数校验失败: {e}"}

    ts_code = p.ts_code
    start_date = p.start_date  # YYYYMMDD
    end_date = p.end_date

    # 策略兼容：strategy（单值）或 strategies（数组）
    strategies = p.strategies or [p.strategy]
    if not strategies:
        return {"success": False, "error": "请选择至少一个策略"}

    # 资金和费率参数
    initial_cash = p.initial_cash or p.cash or 100000.0
    params = p.params
    slippage = params.get("slippage", 0.001)
    commission_rate = params.get("commission_rate", 0.00025)
    benchmark = p.benchmark

    # 构建策略参数（过滤掉全局配置键，按策略名分组传递给引擎）
    strategy_params: dict[str, dict] = {}
    for s in strategies:
        strat_p = {k: v for k, v in params.items() if k not in ("slippage", "commission_rate")}
        if strat_p:
            strategy_params[s] = strat_p

    results = []
    last_bt_id = None

    # ── 数据预处理函数（所有策略共享同份行情数据，避免重复抓取） ──
    def _normalize(rows: list[dict]) -> list[dict]:
        norm = []
        for r in rows or []:
            td = str(r.get("trade_date", "")).replace("-", "")
            if not td:
                continue
            norm.append(
                {
                    "trade_date": td,
                    "open": float(r.get("open", 0)),
                    "close": float(r.get("close", 0)),
                    "high": float(r.get("high", 0)),
                    "low": float(r.get("low", 0)),
                    "vol": int(float(r.get("vol", 0))),
                    "amount": float(r.get("amount", 0)),
                }
            )
        return norm

    # ── 行情数据抓取（一次抓取，多策略共用） ──
    pre_data = None
    bench_data = None
    try:
        pre_data = await _run_sync_with_timeout(
            fetch_kline_tencent, 15,
            ts_code, start_date, end_date,
        )
        if not pre_data:
            pre_data = await _run_sync_with_timeout(
                fetch_kline_eastmoney, 15,
                ts_code, start_date, end_date,
            )

        if benchmark:
            bench_data = await _run_sync_with_timeout(
                fetch_kline_tencent, 15,
                benchmark, start_date, end_date,
            )
            if not bench_data:
                bench_data = await _run_sync_with_timeout(
                    fetch_kline_eastmoney, 15,
                    benchmark, start_date, end_date,
                )
    except Exception:
        logger.error(f"K线数据抓取失败: {traceback.format_exc()}")

    data_arg = {ts_code: _normalize(pre_data)} if pre_data else None
    bench_arg = _normalize(bench_data) if bench_data else None

    if not data_arg:
        return {"success": False, "error": "无法获取行情数据，请检查网络或换一只股票再试"}

    # ── 创建唯一引擎实例（所有策略共享，避免重复初始化 + 重复抓数据） ──
    engine = EnhancedBacktestEngine(BacktestConfig(
        ts_codes=[ts_code],
        strategies=[strategies[0]],  # 占位；回测前会替换为当前策略
        start_date=start_date,
        end_date=end_date,
        initial_cash=float(initial_cash),
        slippage=float(slippage),
        commission_rate=float(commission_rate),
        benchmark=benchmark,
    ))

    for strategy in strategies:
        try:
            engine.config.strategies = [strategy]
            result = await _run_sync_with_timeout(
                engine.run, 30, data=data_arg, benchmark_data=bench_arg,
                strategy_params=strategy_params if strategy_params else None,
            )
        except Exception:
            logger.error(f"回测引擎执行失败 [{strategy}]: {traceback.format_exc()}")
            continue

        # 转换 equity_curve 为前端期望格式 [[date, nav], ...]
        equity_curve = (
            [[d["date"], d["nav"]] for d in result.equity_curve] if result.equity_curve else []
        )
        benchmark_curve = (
            [[d["date"], d.get("benchmark_nav", 1.0)] for d in result.equity_curve]
            if result.equity_curve
            else []
        )
        drawdown_curve = (
            [[d["date"], d.get("drawdown", 0.0)] for d in result.equity_curve]
            if result.equity_curve
            else []
        )

        # 转换 trades 为前端期望格式
        trades = _convert_trades(result.trades)

        result_dict = {
            "strategy": strategy,
            "ts_code": ts_code,
            "metrics": _build_response_metrics(
                total_return=result.total_return,
                annual_return=result.annual_return,
                sharpe_ratio=result.sharpe_ratio,
                max_drawdown=result.max_drawdown,
                win_rate=result.win_rate,
                profit_loss_ratio=result.profit_factor,
                total_trades=result.total_trades,
                alpha=result.alpha,
                beta=result.beta,
                volatility=result.volatility,
                calmar_ratio=result.calmar_ratio,
                sortino_ratio=result.sortino_ratio,
            ),
            "equity_curve": equity_curve,
            "benchmark_curve": benchmark_curve,
            "drawdown_curve": drawdown_curve,
            "monthly_returns": result.monthly_returns or [],
            "trades": trades,
            "data_source": "tencent",
        }

        # ========== DB 持久化 ==========
        bt_id = _persistence.save(
            strategy, ts_code, start_date, end_date, float(initial_cash), result, result_dict
        )
        if bt_id:
            result_dict["backtest_id"] = bt_id
            last_bt_id = bt_id

        results.append(result_dict)

    if not results:
        return {"success": False, "error": "所有策略回测均失败，请检查网络或换一只股票再试"}

    if len(results) == 1:
        return {"success": True, "data": results[0]}

    # 多策略：附带对比
    return {"success": True, "data": results[0], "comparison": results}


@router.get("/")
async def list_backtest_results(
    limit: int = 20,
    strategy: StrategyName | None = None,
):
    """列出最近回测结果（从数据库读取）"""
    try:
        from repositories.backtest_repo import get_backtest_history

        with get_db_session() as db:
            history = get_backtest_history(db, limit=limit, strategy_name=strategy)

        return {"success": True, "data": {"backtests": history, "total": len(history)}}
    except Exception as e:
        logger.warning(f"读取回测历史失败: {e}")
        return {"success": True, "data": {"backtests": [], "total": 0}}


@router.get("/status")
async def backtest_status():
    """回测服务状态"""
    return {"success": True, "data": {"status": "available", "engine": "enhanced_v2"}}


@router.get("/{backtest_id}")
async def get_backtest_detail(backtest_id: str):
    """按 ID 查询单条回测结果详情"""
    try:
        from repositories.backtest_repo import get_backtest_result_with_details

        with get_db_session() as db:
            bt = get_backtest_result_with_details(db, backtest_id)

        if bt is None:
            return {"success": False, "error": f"回测记录不存在: {backtest_id}"}

        # 展开 backtest_details 中的 curves 和 trades（与 POST /run 响应格式对齐）
        details = bt.pop("backtest_details", {}) or {}
        response_data = {
            **bt,
            "equity_curve": details.get("equity_curve", []),
            "benchmark_curve": details.get("benchmark_curve", []),
            "drawdown_curve": details.get("drawdown_curve", []),
            "monthly_returns": details.get("monthly_returns", []),
            "trades": details.get("trades", []),
        }
        # 将基础指标也放入 metrics 字段
        response_data["metrics"] = _build_response_metrics(
            total_return=bt.get("total_return"),
            annual_return=bt.get("annual_return"),
            sharpe_ratio=bt.get("sharpe_ratio"),
            max_drawdown=bt.get("max_drawdown"),
            win_rate=bt.get("win_rate"),
            profit_loss_ratio=bt.get("profit_loss_ratio"),
            total_trades=bt.get("total_trades"),
            alpha=details.get("alpha"),
            beta=details.get("beta"),
            volatility=details.get("volatility"),
            calmar_ratio=details.get("calmar_ratio"),
            sortino_ratio=details.get("sortino_ratio"),
        )

        return {"success": True, "data": response_data}
    except Exception as e:
        logger.error(f"查询回测详情失败: {e}")
        return {"success": False, "error": "查询回测详情失败"}


@router.get("/walk-forward/param-grids")
async def list_param_grids(strategy: str | None = None):
    """获取 Walk-Forward 可用参数网格定义

    Args:
        strategy: 可选，按策略名筛选（ma-cross / breakout / rsi / macd / kdj / vwm / bollinger / adx / obv / vbm / vpb / combo-vwm-bbr）

    Returns:
        参数网格字典，未传入 strategy 时返回所有策略的网格
    """
    if strategy:
        from services.param_grids import get_default_param_grid

        grid = get_default_param_grid(strategy)
        if not grid:
            return {
                "success": False,
                "error": f"未知策略 '{strategy}'，可用策略: {', '.join(DEFAULT_PARAM_GRIDS.keys())}",
            }
        return {"success": True, "data": {strategy: grid}}
    return {"success": True, "data": DEFAULT_PARAM_GRIDS}


@router.post("/walk-forward")
async def run_walk_forward(request: Request):
    """执行真实 Walk-Forward 前进分析"""
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "error": "请求体JSON解析失败"}

    # Pydantic 参数校验
    try:
        p = WalkForwardRequest(**body)
    except Exception as e:
        return {"success": False, "error": f"参数校验失败: {e}"}

    ts_code = p.ts_code
    strategy = p.strategy
    start_date = p.start_date
    end_date = p.end_date

    params = p.params
    config = BacktestConfig(
        ts_codes=[ts_code],
        strategies=[strategy],
        start_date=start_date,
        end_date=end_date,
        initial_cash=float(p.initial_cash or p.cash or 100000),
        slippage=float(params.get("slippage", 0.001)),
        commission_rate=float(params.get("commission_rate", 0.00025)),
        benchmark=p.benchmark,
    )

    try:
        engine = EnhancedBacktestEngine(config)
        wf = await _run_sync_with_timeout(
            engine.walk_forward, 60,
            ts_code=ts_code, strategy=strategy,
            train_days=p.train_days, test_days=p.test_days, step_days=p.step_days,
            param_grid=p.param_grid,
        )
    except Exception as e:
        if isinstance(e, asyncio.TimeoutError):
            logger.error(f"Walk-Forward超时 [{strategy}]: 超过60秒")
            return {"success": False, "error": "Walk-Forward执行超时，请缩短回测范围"}
        logger.error(f"Walk-Forward执行失败 [{strategy}]: {traceback.format_exc()}")
        return {"success": False, "error": "Walk-Forward执行失败，请检查数据源或参数"}

    if wf.get("error"):
        return {"success": False, "error": wf.get("error")}

    windows = []
    for idx, w in enumerate(wf.get("windows", [])):
        windows.append(
            {
                "window": f"W{idx + 1}",
                "train_start": w.get("train_start"),
                "train_end": w.get("train_end"),
                "test_start": w.get("test_start"),
                "test_end": w.get("test_end"),
                "best_params": w.get("best_params", {}),
                "train_sharpe": round(float(w.get("train_sharpe") or 0), 4),
                "test_sharpe": round(float(w.get("test_sharpe") or 0), 4),
                "train_return": round(float(w.get("train_return") or 0), 6),
                "test_return": round(float(w.get("test_return") or 0), 6),
                "test_max_dd": round(float(w.get("test_max_dd") or 0), 6),
            }
        )

    # ========== DB 持久化 ==========
    try:
        from repositories.walkforward_repo import save_walkforward_result

        with get_db_session() as db:
            wf_id = save_walkforward_result(
                db,
                strategy_name=strategy,
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                train_days=p.train_days,
                test_days=p.test_days,
                step_days=p.step_days,
                param_grid=p.param_grid,
                initial_cash=float(p.initial_cash or p.cash or 100000),
                slippage=float(params.get("slippage", 0.001)),
                commission_rate=float(params.get("commission_rate", 0.00025)),
                benchmark=p.benchmark,
                windows=windows,
                overall_test_return=wf.get("overall_test_return", 0),
                overfit_ratio=wf.get("overfit_ratio", 0),
                num_windows=len(windows),
            )
    except Exception as e:
        logger.warning(f"Walk-Forward结果持久化失败: {e}")
        wf_id = None

    response_data = {
        "strategy": strategy,
        "windows": windows,
        "overall_test_return": round(float(wf.get("overall_test_return") or 0), 6),
        "overfit_ratio": round(float(wf.get("overfit_ratio") or 0), 4),
        "num_windows": len(windows),
        "data_source": "tencent",
    }
    if wf_id:
        response_data["wf_id"] = wf_id

    return {"success": True, "data": response_data}


@router.get("/walk-forward/results")
async def list_walkforward_results(
    limit: int = 20,
    strategy: str | None = None,
):
    """列出 Walk-Forward 分析历史（从数据库读取）"""
    try:
        from repositories.walkforward_repo import get_walkforward_history

        with get_db_session() as db:
            history = get_walkforward_history(db, limit=limit, strategy_name=strategy)

        return {"success": True, "data": {"results": history, "total": len(history)}}
    except Exception as e:
        logger.warning(f"读取Walk-Forward历史失败: {e}")
        return {"success": True, "data": {"results": [], "total": 0}}


@router.get("/walk-forward/results/{wf_id}")
async def get_walkforward_detail(wf_id: str):
    """按 ID 查询 Walk-Forward 完整结果（含窗口详情）"""
    try:
        from repositories.walkforward_repo import get_walkforward_detail

        with get_db_session() as db:
            detail = get_walkforward_detail(db, wf_id)

        if detail is None:
            return {"success": False, "error": f"Walk-Forward记录不存在: {wf_id}"}

        return {"success": True, "data": detail}
    except Exception as e:
        logger.error(f"查询Walk-Forward详情失败: {e}")
        return {"success": False, "error": "查询Walk-Forward详情失败"}
