"""
交易执行服务 - 主应用入口
提供订单管理、MiniQMT集成、交易风险控制等API
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("交易执行服务启动中...")
    yield
    logger.info("交易执行服务关闭中...")

app = FastAPI(
    title="QuantTradingSystem - 交易执行服务",
    description="A股量化交易系统 - 交易执行微服务",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入并注册路由
from api.orders import router as orders_router
from api.positions import router as positions_router
from api.risk import router as risk_router

app.include_router(orders_router, prefix="/api/v1/orders", tags=["订单管理"])
app.include_router(positions_router, prefix="/api/v1/positions", tags=["持仓管理"])
app.include_router(risk_router, prefix="/api/v1/risk", tags=["风险控制"])

@app.get("/")
async def root():
    return {
        "service": "QuantTradingSystem Execution Service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
