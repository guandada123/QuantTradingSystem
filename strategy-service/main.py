"""
策略研究服务 - 主应用入口 v2.0
新增：WebSocket实时推送、后台定时任务
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import uvicorn
import logging
import json
from datetime import datetime
from typing import Set

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# WebSocket连接管理
class ConnectionManager:
    """WebSocket连接管理器"""
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.add(ws)
        logger.info(f"WebSocket连接建立，当前连接数：{len(self.active_connections)}")
    
    def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)
        logger.info(f"WebSocket连接断开，当前连接数：{len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        dead = set()
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("策略研究服务启动中...")
    # 启动后台任务：每3秒广播指数行情
    broadcast_task = asyncio.create_task(background_broadcast())
    yield
    broadcast_task.cancel()
    logger.info("策略研究服务关闭中...")

async def background_broadcast():
    """后台任务：定时广播指数行情"""
    from services.data_service import DataService
    from core.config import settings
    
    ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
    
    while True:
        try:
            if manager.active_connections:
                indices = ds.get_index_realtime_quote()
                await manager.broadcast({
                    'type': 'index_update',
                    'data': indices,
                    'timestamp': datetime.now().isoformat()
                })
                logger.debug(f"广播指数行情：{len(indices)}个指数，{len(manager.active_connections)}个连接")
        except Exception as e:
            logger.error(f"广播失败：{e}")
        
        await asyncio.sleep(3)  # 每3秒广播一次

app = FastAPI(
    title="QuantTradingSystem - 策略研究服务",
    description="A股量化交易系统 - 策略研究微服务",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from api import stock_router, signal_router, backtest_router, ai_router
from api.account import router as account_router
from api.trades import router as trades_router

app.include_router(stock_router, prefix="/api/v1/stocks", tags=["股票数据"])
app.include_router(signal_router, prefix="/api/v1/signals", tags=["交易信号"])
app.include_router(backtest_router, prefix="/api/v1/backtest", tags=["回测"])
app.include_router(ai_router, prefix="/api/v1/ai", tags=["AI分析"])
app.include_router(account_router, prefix="/api/v1/account", tags=["账户"])
app.include_router(trades_router, prefix="/api/v1/trades", tags=["交易记录"])

@app.get("/")
async def root():
    return {"service": "QuantTradingSystem Strategy Service", "version": "2.0.0", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket端点：接收客户端连接并推送实时数据"""
    await manager.connect(ws)
    try:
        # 发送欢迎消息
        await ws.send_json({"type": "connected", "message": "已连接实时数据通道", "timestamp": datetime.now().isoformat()})
        
        while True:
            # 接收客户端消息（如订阅特定股票）
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get('action') == 'subscribe':
                    ts_code = msg.get('ts_code')
                    # 订阅指定股票（TODO: 按需推送）
                    await ws.send_json({"type": "subscribed", "ts_code": ts_code})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
