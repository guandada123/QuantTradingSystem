"""
Stock Insight ML增强扫描模块
两阶段回退筛选、ML预测
"""

from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def ml_tier_selection(data_service, mode: str, top_n: int, relaxed: bool) -> list[dict]:
    """ML两阶段筛选"""
    try:
        if not data_service.pro:
            return []

        pool = data_service.pro.stock_basic(
            exchange="", list_status="L", fields="ts_code,symbol,name,market"
        )

        if mode == "mainboard":
            pool = pool[pool["market"] == "主板"]

        today = datetime.now().strftime("%Y%m%d")
        cal = data_service.pro.trade_cal(start_date="20260501", end_date=today)

        if cal is not None and len(cal) > 0:
            od = cal[(cal["is_open"] == 1) & (cal["cal_date"] <= today)]["cal_date"]
            latest = od.iloc[0] if len(od) > 0 else today
        else:
            latest = today

        db = data_service.pro.daily_basic(trade_date=latest)
        if db is None or len(db) == 0:
            return []

        db = db.copy()
        db["code"] = db["ts_code"].str.split(".").str[0]
        dp = db[db["code"].isin(pool["symbol"].tolist())]

        if relaxed:
            cond = (
                (dp["close"] >= 5)
                & (dp["close"] <= 100)
                & (dp["pe"] > 0)
                & (dp["pe"] <= 100)
                & (dp["pb"] > 0)
                & (dp["pb"] <= 15)
                & (dp["volume_ratio"] >= 0.5)
                & (dp["turnover_rate"] <= 35)
            )
        else:
            cond = (
                (dp["close"] >= 5)
                & (dp["close"] <= 80)
                & (dp["pe"] > 0)
                & (dp["pe"] <= 60)
                & (dp["pb"] > 0)
                & (dp["pb"] <= 8)
                & (dp["volume_ratio"] >= 0.7)
                & (dp["turnover_rate"] <= 25)
            )

        fd = dp[cond].copy()
        if len(fd) == 0:
            return []

        fd["score"] = (
            fd["pe"].rank(pct=True, ascending=False) * 0.25
            + fd["turnover_rate"].rank(pct=True) * 0.40
            + fd["volume_ratio"].rank(pct=True) * 0.35
        )

        top = fd.sort_values("score", ascending=False).head(top_n * 3)

        results = []
        name_map = dict(zip(pool["symbol"], pool["name"]))

        for _, row in top.iterrows():
            code = row["code"]
            tier = "Tier2" if relaxed else "Tier1"

            results.append(
                {
                    "code": code,
                    "name": name_map.get(code, ""),
                    "tier": tier,
                    "score": float(row["score"]),
                    "pe": float(row["pe"]),
                    "pb": float(row["pb"]),
                    "close": float(row["close"]),
                    "volume_ratio": float(row["volume_ratio"]),
                    "turnover_rate": float(row["turnover_rate"]),
                }
            )

            if len(results) >= top_n:
                break

        return results

    except Exception as e:
        logger.warning(f"ML阶段筛选失败: {e}")
        return []


def ml_predict_bullish(code: str) -> bool:
    """ML预测是否为看涨（模拟）"""
    return True
