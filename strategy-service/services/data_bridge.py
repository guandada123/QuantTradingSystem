"""
数据桥接层 v1.0
将通达信MCP数据桥接到策略服务
由WorkBuddy agent定时调用，将数据写入JSON缓存
"""

import json
import os
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"

def save_index_data(indices_data: list):
    """保存指数数据到缓存"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "index_cache.json", "w") as f:
        json.dump({
            "data": indices_data,
            "updated_at": datetime.now().isoformat()
        }, f, ensure_ascii=False)

def save_stock_data(ts_code: str, stock_data: dict):
    """保存个股数据到缓存"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = DATA_DIR / f"stock_{ts_code.replace('.', '_')}.json"
    with open(cache_file, "w") as f:
        json.dump({
            "data": stock_data,
            "updated_at": datetime.now().isoformat()
        }, f, ensure_ascii=False)

def load_index_data() -> list:
    """读取指数缓存数据"""
    cache_file = DATA_DIR / "index_cache.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)["data"]
    return []

def load_stock_data(ts_code: str) -> dict:
    """读取个股缓存数据"""
    cache_file = DATA_DIR / f"stock_{ts_code.replace('.', '_')}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)["data"]
    return {}
