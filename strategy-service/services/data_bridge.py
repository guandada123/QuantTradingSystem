"""
数据桥接层 v1.0
将通达信MCP数据桥接到策略服务
由WorkBuddy agent定时调用，将数据写入JSON缓存
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from shared.exceptions import DataSourceException
from shared.structured_log import get_logger

logger = get_logger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def save_index_data(indices_data: list[dict[str, Any]]) -> None:
    """保存指数数据到缓存"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = DATA_DIR / "index_cache.json"
        with open(cache_file, "w") as f:
            json.dump(
                {"data": indices_data, "updated_at": datetime.now().isoformat()},
                f,
                ensure_ascii=False,
            )
        logger.info("指数缓存已保存", file=str(cache_file), count=len(indices_data))
    except OSError as e:
        logger.error("保存指数缓存失败", error=str(e))
        raise DataSourceException("保存指数缓存失败", code="SAVE_INDEX_CACHE_FAILED", cause=e)


def save_stock_data(ts_code: str, stock_data: dict[str, Any]) -> None:
    """保存个股数据到缓存"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = DATA_DIR / f"stock_{ts_code.replace('.', '_')}.json"
        with open(cache_file, "w") as f:
            json.dump(
                {"data": stock_data, "updated_at": datetime.now().isoformat()},
                f,
                ensure_ascii=False,
            )
        logger.info("个股缓存已保存", ts_code=ts_code, file=str(cache_file))
    except OSError as e:
        logger.error("保存个股缓存失败", ts_code=ts_code, error=str(e))
        raise DataSourceException(
            f"保存个股缓存失败: {ts_code}", code="SAVE_STOCK_CACHE_FAILED", cause=e
        )


def load_index_data() -> list[dict[str, Any]]:
    """读取指数缓存数据"""
    try:
        cache_file = DATA_DIR / "index_cache.json"
        if not cache_file.exists():
            logger.debug("指数缓存不存在，返回空列表")
            return []
        with open(cache_file) as f:
            data = json.load(f)
        return data.get("data", [])
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取指数缓存失败", error=str(e))
        return []


def load_stock_data(ts_code: str) -> dict[str, Any]:
    """读取个股缓存数据"""
    try:
        cache_file = DATA_DIR / f"stock_{ts_code.replace('.', '_')}.json"
        if not cache_file.exists():
            logger.debug("个股缓存不存在", ts_code=ts_code)
            return {}
        with open(cache_file) as f:
            data = json.load(f)
        return data.get("data", {})
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取个股缓存失败", ts_code=ts_code, error=str(e))
        return {}
