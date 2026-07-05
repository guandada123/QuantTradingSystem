#!/usr/bin/env python3
"""
QMT Bridge Server — Windows端运行的REST API桥接服务。

功能：将MiniQMT xtquant API暴露为HTTP接口，供Mac端QTS调用。

启动方式（在Windows PC上）：
    python qmt_bridge_server.py --port 8580

依赖：
    pip install xtquant fastapi uvicorn
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import time

# ============================================================
#  请先安装 xtquant: pip install xtquant
#  或者从 QMT 客户端目录复制 xtquant 到 site-packages
# ============================================================

logger = logging.getLogger("qmt_bridge")

# ============================================================
#  Configuration
# ============================================================

QMT_PATH = os.environ.get("QMT_PATH", r"D:\国金证券QMT模拟交易端")
ACCOUNT = os.environ.get("QMT_ACCOUNT", "86001853")
SESSION_ID = int(os.environ.get("QMT_SESSION_ID", "123456"))

MAX_RETRIES = 3  # MiniQMT 最大重连次数
RETRY_DELAY = 2  # 重连间隔基数（秒），指数退避: 2s, 4s, 8s

# ============================================================
#  Connect to MiniQMT
# ============================================================


def connect_miniqmt():
    """连接MiniQMT交易端"""
    try:
        from xtquant import xtdata, xttrader
        from xtquant.xtconstant import (
            ACCOUNT_TYPE_T0,
            FIX_PRICE,
            LATEST_PRICE,
            MARKET_SH,
            MARKET_SZ,
            STOCK_BUY,
            STOCK_SELL,
        )
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount
    except ImportError as e:
        logger.error(f"xtquant导入失败: {e}")
        logger.error("请先: pip install xtquant")
        logger.error("或从QMT目录复制xtquant到site-packages")
        return None

    logger.info(f"连接MiniQMT: path={QMT_PATH}, account={ACCOUNT}")

    # 创建session
    session = int(time.time()) % 1000000

    # 创建交易对象
    xt_trader = XtQuantTrader(QMT_PATH, session)

    # 创建账号对象
    acc = StockAccount(ACCOUNT, "STOCK")

    # 启动交易回调
    class TradeCallback:
        def on_disconnected(self):
            logger.warning("QMT连接断开")

        def on_stock_order(self, order):
            logger.info(f"订单回调: {order.order_id} {order.order_status}")

        def on_stock_asset(self, asset):
            logger.info(f"资产回调: 总资产={asset.total_asset}")

        def on_stock_position(self, position):
            logger.info(f"持仓回调: {position.stock_code} {position.volume}")

        def on_order_error(self, order_error):
            logger.error(f"订单错误: {order_error.error_msg}")

        def on_cancel_error(self, cancel_error):
            logger.error(f"撤单错误: {cancel_error.error_msg}")

    cb = TradeCallback()
    xt_trader.register_callback(cb)

    # 启动
    xt_trader.start()

    # 连接
    connect_result = xt_trader.connect()
    if connect_result != 0:
        logger.error(f"QMT连接失败: code={connect_result}")
        return None

    logger.info("QMT连接成功")

    # 订阅账号
    subscribe_result = xt_trader.subscribe(acc)
    if subscribe_result != 0:
        logger.error(f"账号订阅失败: code={subscribe_result}")
        return None

    logger.info(f"账号{ACCOUNT}订阅成功")

    return {
        "xt_trader": xt_trader,
        "xtdata": xtdata,
        "acc": acc,
        "STOCK_BUY": STOCK_BUY,
        "STOCK_SELL": STOCK_SELL,
        "FIX_PRICE": FIX_PRICE,
        "LATEST_PRICE": LATEST_PRICE,
        "MARKET_SH": MARKET_SH,
        "MARKET_SZ": MARKET_SZ,
    }


# ============================================================
#  FastAPI Server
# ============================================================


def build_app(qmt):
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(title="QMT Bridge", version="1.0.0")

    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        logger.error(f"未处理的异常 [{request.method} {request.url}]: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.middleware("http")
    async def request_logging(request, call_next):
        """请求日志中间件：记录每个请求的耗时、方法、路径和状态码"""
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} ({duration:.3f}s)"
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "account": ACCOUNT}

    # ---- 行情 ----

    @app.get("/quote/{code}")
    def get_quote(code: str):
        """获取股票实时行情"""
        full_tick = qmt["xtdata"].get_full_tick([code])
        if code not in full_tick:
            raise HTTPException(404, f"未找到{code}行情")
        tick = full_tick[code]
        return {
            "code": code,
            "price": tick.get("lastPrice", 0),
            "open": tick.get("open", 0),
            "high": tick.get("high", 0),
            "low": tick.get("low", 0),
            "volume": tick.get("volume", 0),
            "amount": tick.get("amount", 0),
            "change_pct": tick.get("pctChg", 0),
        }

    @app.get("/quotes")
    def get_quotes(codes: str):
        """批量获取行情，codes用逗号分隔"""
        code_list = [c.strip() for c in codes.split(",")]
        full_tick = qmt["xtdata"].get_full_tick(code_list)
        result = {}
        for code, tick in full_tick.items():
            result[code] = {
                "price": tick.get("lastPrice", 0),
                "open": tick.get("open", 0),
                "high": tick.get("high", 0),
                "low": tick.get("low", 0),
                "volume": tick.get("volume", 0),
                "amount": tick.get("amount", 0),
                "change_pct": tick.get("pctChg", 0),
            }
        return result

    # ---- 账户 ----

    @app.get("/account")
    def get_account():
        """查询账户资产"""
        asset = qmt["xt_trader"].query_stock_asset(qmt["acc"])
        if asset:
            return {
                "account": ACCOUNT,
                "total_asset": asset.total_asset,
                "available": asset.cash,
                "market_value": asset.market_value,
                "frozen": asset.frozen_cash,
                "fetch_time": asset.m_dwTime if hasattr(asset, "m_dwTime") else None,
            }
        raise HTTPException(500, "查询资产失败")

    @app.get("/positions")
    def get_positions():
        """查询持仓（实时行情字段来自 get_full_tick，非持仓成本价）"""
        positions = qmt["xt_trader"].query_stock_positions(qmt["acc"])
        codes = [pos.stock_code for pos in positions]
        ticks = qmt["xtdata"].get_full_tick(codes) if codes else {}
        result = []
        for pos in positions:
            tick = ticks.get(pos.stock_code, {})
            result.append(
                {
                    "code": pos.stock_code,
                    "name": pos.stock_name,
                    "volume": pos.volume,
                    "available": pos.can_use_volume,
                    "cost": pos.avg_price,
                    "current_price": tick.get("lastPrice", pos.open_price),
                    "market_value": pos.market_value,
                    "pnl": pos.income_balance if hasattr(pos, "income_balance") else 0,
                }
            )
        return {"positions": result, "count": len(result)}

    # ---- 交易 ----

    class OrderRequest(BaseModel):
        code: str  # 如 "000001.SZ"
        price: float = 0  # 0=市价
        quantity: int  # 股数，必须100的倍数
        order_type: str = "LIMIT"  # LIMIT / MARKET

    @app.post("/buy")
    def buy(req: OrderRequest):
        """买入"""
        if req.quantity % 100 != 0:
            raise HTTPException(400, "数量必须是100的倍数")

        price_type = qmt["FIX_PRICE"] if req.order_type == "LIMIT" else qmt["LATEST_PRICE"]

        seq = qmt["xt_trader"].order_stock(
            qmt["acc"],
            req.code,
            qmt["STOCK_BUY"],
            req.quantity,
            price_type,
            req.price,
            "QMT_Bridge",
            f"买入{req.code}",
        )
        return {
            "success": True,
            "order_seq": seq,
            "code": req.code,
            "quantity": req.quantity,
            "price": req.price,
        }

    @app.post("/sell")
    def sell(req: OrderRequest):
        """卖出"""
        if req.quantity % 100 != 0:
            raise HTTPException(400, "数量必须是100的倍数")

        price_type = qmt["FIX_PRICE"] if req.order_type == "LIMIT" else qmt["LATEST_PRICE"]

        seq = qmt["xt_trader"].order_stock(
            qmt["acc"],
            req.code,
            qmt["STOCK_SELL"],
            req.quantity,
            price_type,
            req.price,
            "QMT_Bridge",
            f"卖出{req.code}",
        )
        return {
            "success": True,
            "order_seq": seq,
            "code": req.code,
            "quantity": req.quantity,
            "price": req.price,
        }

    @app.post("/cancel/{order_id}")
    def cancel_order(order_id: int):
        """撤单"""
        result = qmt["xt_trader"].cancel_order_stock(qmt["acc"], order_id)
        return {"success": result == 0, "order_id": order_id}

    @app.get("/orders")
    def get_orders():
        """查询当日委托"""
        orders = qmt["xt_trader"].query_stock_orders(qmt["acc"])
        result = []
        for o in orders:
            result.append(
                {
                    "order_id": o.order_id,
                    "code": o.stock_code,
                    "type": "BUY" if o.order_type == qmt["STOCK_BUY"] else "SELL",
                    "price": o.price,
                    "quantity": o.order_volume,
                    "filled": o.traded_volume,
                    "status": o.order_status,
                    "time": o.order_time,
                }
            )
        return {"orders": result, "count": len(result)}

    return app


# ============================================================
#  Main
# ============================================================


def main():
    global QMT_PATH
    parser = argparse.ArgumentParser(description="QMT Bridge Server")
    parser.add_argument("--port", type=int, default=8580, help="服务端口 (默认 8580)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--qmt-path", type=str, default=QMT_PATH, help="QMT安装目录")
    args = parser.parse_args()

    QMT_PATH = args.qmt_path

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )

    # 连接QMT（自动重试，指数退避）
    qmt = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"正在连接MiniQMT (第{attempt}/{MAX_RETRIES}次)...")
        if attempt > 1:
            delay = RETRY_DELAY * (2 ** (attempt - 2))
            logger.info(f"等待{delay}秒后重试...")
            time.sleep(delay)
        qmt = connect_miniqmt()
        if qmt:
            break
        logger.error(f"连接失败（第{attempt}/{MAX_RETRIES}次）")

    if not qmt:
        logger.error(f"QMT重连{MAX_RETRIES}次均失败，退出")
        sys.exit(1)

    # 启动服务
    import uvicorn

    app = build_app(qmt)

    # ── 启动横幅 ──
    hostname = socket.gethostname()
    local_url = f"http://localhost:{args.port}"
    mac_url = f"http://{hostname}:{args.port}"
    banner = f"""
╔{"═" * 50}╗
║{" " * 18}QMT Bridge Server{" " * 18}║
╠{"═" * 50}╣
║  🟢 状态      Running{" " * 31}║
║  👤 账号      {ACCOUNT}{" " * (43 - len(ACCOUNT))}║
║  🖥️ 监听      {local_url}{" " * (41 - len(local_url))}║
║  🔗 Mac调用   {mac_url}/health{" " * (34 - len(mac_url))}║
║  📦 MiniQMT   {QMT_PATH}{" " * (39 - len(QMT_PATH))}║
╚{"═" * 50}╝"""
    logger.info("\n" + banner)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
