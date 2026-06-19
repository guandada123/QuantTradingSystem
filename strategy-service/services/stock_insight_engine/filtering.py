"""
Stock Insight 候选筛选模块
主板候选、长线候选、短线候选、板块去重
"""

import logging

logger = logging.getLogger(__name__)


def filter_mainboard_candidates(
    stock_pool: list[dict], owned_codes: list[str] = None
) -> list[dict]:
    """主板候选股票基础筛选"""
    owned_set = set(owned_codes) if owned_codes else set()

    candidates = []
    for stock in stock_pool:
        code = stock.get("symbol", "")
        if code in owned_set:
            continue
        candidates.append(stock)

    return candidates[:100]


def filter_long_term_candidates(stock_pool: list[dict]) -> list[dict]:
    """长线候选股票筛选"""
    return stock_pool[:50]


def filter_short_term_candidates(stock_pool: list[dict]) -> list[dict]:
    """短线候选股票筛选"""
    return stock_pool[:50]


def select_top_with_sector_diversification(all_results: list[dict], top_n: int) -> list[dict]:
    """板块去重选择TOP股票"""
    all_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    picked = []
    used_sectors = set()

    for r in all_results:
        if len(picked) >= top_n:
            break

        sector = r.get("sector", "未知")
        if sector not in used_sectors or r.get("final_score", 0) > 60:
            picked.append(r)
            used_sectors.add(sector)

    return picked
