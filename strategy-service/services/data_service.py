"""
数据获取服务 v4.0
通过 QuoteProviderFactory 支持多数据源动态切换。
主数据源由配置 QTS_DATA_SOURCE 控制（tushare / tdx / akshare）
"""

import json
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pandas as pd

logger = logging.getLogger(__name__)

DataService_instance = None


class DataService:
    """
    数据获取服务（兼容原有接口）

    内部使用 QuoteProviderFactory 提供多数据源支持。
    可通过 set_data_source() 动态切换数据源（如 tdx → tushare → akshare）。
    """

    def __init__(self, tushare_token: str = None, data_source: str = None):
        global DataService_instance
        self.tushare_token = tushare_token
        self._spot_cache = None
        self._spot_cache_time = None
        self._lock = threading.Lock()

        # 初始化 QuoteProviderFactory
        from shared.quote_provider import QuoteProviderFactory
        from core.config import settings

        source = data_source or getattr(settings, 'QTS_DATA_SOURCE', 'tushare')
        self._factory = QuoteProviderFactory(
            default_source=source,
            tdx={
                'api_url': getattr(settings, 'TDX_CONNECTOR_URL', '') or '',
                'mcp_cmd': getattr(settings, 'TDX_MCP_CMD', '') or '',
            },
            tushare={'token': tushare_token or ''},
        )
        # 兼容：保留 pro 属性供旧代码引用
        self.pro = self._init_tushare_pro(tushare_token)

        logger.info(f"DataService v4 初始化完成，数据源: {source}")
        DataService_instance = self

    def _init_tushare_pro(self, token):
        """兼容老接口：初始化 Tushare pro API"""
        if not token:
            return None
        try:
            import os
            import tushare as ts
            os.environ['TUSHARE_TOKEN_PATH'] = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), '.tushare_token'
            )
            try:
                ts.set_token(token)
                return ts.pro_api()
            except PermissionError:
                return ts.pro_api(token)
        except Exception as e:
            logger.warning(f"Tushare兼容初始化失败: {e}")
            return None

    def set_data_source(self, source: str):
        """动态切换数据源"""
        self._factory.set_default_source(source)
        logger.info(f"DataService 数据源切换为: {source}")

    # ---- QuoteProvider 代理方法 ----

    def get_stock_realtime_quote(self, ts_code: str) -> Dict[str, Any]:
        """获取单只股票最新行情"""
        try:
            return self._factory.default.get_realtime_quote(ts_code)
        except Exception as e:
            logger.error(f"获取{ts_code}行情失败: {e}")
            return self._empty_quote(ts_code)

    def get_stock_batch_realtime(self, ts_codes: List[str]) -> List[Dict]:
        """批量获取多只股票行情"""
        try:
            return self._factory.default.get_batch_realtime(ts_codes)
        except Exception as e:
            logger.error(f"批量获取行情失败: {e}")
            return [self._empty_quote(c) for c in ts_codes]

    def get_index_realtime_quote(self) -> List[Dict[str, Any]]:
        """获取核心指数最新行情（多数据源自动降级）"""
        index_map = {
            '000001.SH': '上证指数', '399001.SZ': '深证成指',
            '399006.SZ': '创业板指', '000688.SH': '科创50',
            '899050.BJ': '北证50', '000300.SH': '沪深300',
            '000905.SH': '中证500', '000852.SH': '中证1000',
        }
        default_index_codes = list(index_map.keys())

        fallback_sources = ['tushare', 'akshare']
        tried = set()
        default_source = self._factory._default_source
        ordered_sources = [default_source] + [s for s in fallback_sources if s != default_source]

        for source in ordered_sources:
            if source in tried:
                continue
            tried.add(source)
            try:
                provider = self._factory.get_provider(source)
                if provider is None:
                    continue
                result = provider.get_index_realtime(default_index_codes)
                if result and any(r.get('price', 0) > 0 for r in result):
                    logger.info(f"DataService: {source} 获取指数行情成功")
                    return result
                else:
                    logger.warning(f"DataService: {source} 指数行情返回空/价格为0")
            except Exception as e:
                logger.warning(f"DataService: {source} 获取指数行情失败: {e}")

        # 最后兜底：腾讯财经 HTTP 直连（免费、稳定、无需 Token）
        result = self._fetch_index_via_tencent(index_map)
        if result and any(r.get('price', 0) > 0 for r in result):
            logger.info("DataService: 腾讯财经 获取指数行情成功")
            return result

        # 所有源均失败，返回零值兜底
        logger.error("DataService: 所有数据源获取指数行情均失败")
        return [{'code': c.split('.')[0], 'name': n,
                  'price': 0.0, 'pct_change': 0.0}
                for c, n in index_map.items()]

    def _fetch_index_via_tencent(self, index_map: dict) -> List[Dict[str, Any]]:
        """通过腾讯财经 API 获取指数行情（免 Token，稳定可靠）"""
        # 腾讯代码映射
        tencent_code_map = {
            '000001.SH': 's_sh000001', '399001.SZ': 's_sz399001',
            '399006.SZ': 's_sz399006', '000688.SH': 's_sh000688',
            '899050.BJ': 's_bj899050', '000300.SH': 's_sh000300',
            '000905.SH': 's_sh000905', '000852.SH': 's_sh000852',
        }
        codes = ','.join(tencent_code_map.get(c, '') for c in index_map.keys())
        try:
            import urllib.request
            url = f'http://qt.gtimg.cn/q={codes}'
            resp = urllib.request.urlopen(url, timeout=5)
            raw = resp.read().decode('gbk', errors='replace')
            results = []
            for orig_code, name in index_map.items():
                tc = tencent_code_map.get(orig_code, '')
                prefix = f'v_{tc}="'
                try:
                    start = raw.index(prefix) + len(prefix)
                    end = raw.index('";', start)
                    fields = raw[start:end].split('~')
                    if len(fields) >= 6:
                        results.append({
                            'code': orig_code.split('.')[0],
                            'name': name,
                            'price': float(fields[3]) if fields[3] else 0.0,
                            'pct_change': float(fields[5]) if fields[5] else 0.0,
                            'timestamp': datetime.now().isoformat(),
                            'source': 'tencent',
                        })
                        continue
                except (ValueError, IndexError):
                    pass
                results.append({'code': orig_code.split('.')[0], 'name': name,
                                'price': 0.0, 'pct_change': 0.0})
            return results
        except Exception as e:
            logger.warning(f"腾讯财经指数获取失败: {e}")
            return []

    def get_stock_daily_quote(
        self, ts_code: str, start_date: str = None,
        end_date: str = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取日K线数据（优先DB，降级到数据源API）"""
        if start_date and '-' in start_date:
            start_date = start_date.replace('-', '')
        if end_date and '-' in end_date:
            end_date = end_date.replace('-', '')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')

        # 优先从数据库读取
        try:
            from models.database import engine
            from sqlalchemy import text
            with engine.connect() as conn:
                sql = text("""
                    SELECT ts_code, trade_date, open, high, low, close, pre_close,
                           change, pct_change, volume, amount
                    FROM daily_quote
                    WHERE ts_code = :ts_code
                      AND trade_date >= :start_date
                      AND trade_date <= :end_date
                    ORDER BY trade_date ASC
                """)
                result = conn.execute(sql, {
                    'ts_code': ts_code,
                    'start_date': f'{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}',
                    'end_date': f'{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}'
                })
                rows = result.fetchall()
                if rows and len(rows) >= 30:
                    logger.info(f"从DB读取{ts_code}日线: {len(rows)}条")
                    return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.debug(f"DB查询失败，降级到数据源: {e}")

        # 多数据源降级链
        fallback_sources = ['tushare', 'akshare']
        tried = set()
        default_source = self._factory._default_source
        ordered_sources = [default_source] + [s for s in fallback_sources if s != default_source]

        for source in ordered_sources:
            if source in tried:
                continue
            tried.add(source)
            try:
                provider = self._factory.get_provider(source)
                if provider is None:
                    continue
                result = provider.get_daily_kline(ts_code, start_date, end_date, limit)
                if result and len(result) > 0:
                    logger.info(f"DataService: {source} 获取 {ts_code} 日线成功 ({len(result)}条)")
                    return result
            except Exception as e:
                logger.warning(f"DataService: {source} 获取 {ts_code} 日线失败: {e}")

        logger.error(f"DataService: 所有数据源获取 {ts_code} 日线均失败")
        return []

    def get_stock_fundamental(self, ts_code: str) -> Dict[str, Any]:
        """获取基本面数据"""
        try:
            return self._factory.default.get_fundamental(ts_code)
        except Exception:
            # 兼容旧接口：Tushare 直连
            if self.pro:
                try:
                    df = self.pro.daily_basic(ts_code=ts_code,
                        fields='ts_code,pe_ttm,pb,ps_ttm,total_mv,circ_mv')
                    if not df.empty:
                        row = df.iloc[0]
                        return {
                            'ts_code': ts_code, 'pe_ttm': float(row['pe_ttm']),
                            'pb': float(row['pb']), 'ps_ttm': float(row['ps_ttm']),
                            'total_mv': float(row['total_mv']),
                            'circ_mv': float(row['circ_mv'])
                        }
                except Exception:
                    pass
            return {}

    def get_stock_pool(self, industry: str = None, limit: int = 50) -> List[Dict]:
        """获取股票池（保留 Tushare 实现）"""
        if not self.pro:
            return []
        try:
            df = self.pro.stock_basic(exchange='', list_status='L',
                fields='ts_code,name,industry,market')
            if industry:
                df = df[df['industry'].str.contains(industry, na=False)]
            return df.head(limit).to_dict('records')
        except:
            return []

    # ---- 数据同步 ----

    def sync_daily_data(self, symbols: List[str] = None, days: int = 30) -> Dict[str, Any]:
        """同步日线数据到 daily_quote 表（供 Scheduler 定时调用）

        对给定 symbols（默认为 stock_pool 前 50 只）获取近 N 天日线数据，
        通过 upsert 写入 daily_quote 表。支持多数据源自动降级。

        Args:
            symbols: 股票代码列表，为 None 时自动从 stock_pool 获取
            days: 同步近 N 天的数据

        Returns:
            {'synced': int, 'failed': int, 'errors': List[str]}
        """
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

        if symbols is None:
            # 从数据库 stock_pool 表获取标的（避免外键约束）
            try:
                from models.database import engine
                from sqlalchemy import text
                with engine.connect() as conn:
                    result = conn.execute(text(
                        "SELECT ts_code FROM stock_pool ORDER BY ts_code LIMIT 50"
                    ))
                    symbols = [row[0] for row in result.fetchall()]
            except Exception as e:
                logger.warning(f"从 stock_pool 获取标的失败: {e}")
                symbols = []
        if not symbols:
            logger.warning("sync_daily_data: 无标的可同步")
            return {'synced': 0, 'failed': 0, 'errors': []}

        synced = 0
        failed = 0
        errors = []

        from models.database import engine
        from sqlalchemy import text

        for ts_code in symbols:
            try:
                data = self.get_stock_daily_quote(ts_code, start_date, end_date, limit=days)
                if not data:
                    logger.debug(f"sync_daily_data: {ts_code} 无可用数据")
                    failed += 1
                    continue

                with engine.connect() as conn:
                    for row in data:
                        trade_date = str(row.get('trade_date', ''))
                        if '-' in trade_date:
                            trade_date = trade_date.replace('-', '')
                        if len(trade_date) == 8:
                            trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
                        else:
                            continue

                        sql = text("""
                            INSERT INTO daily_quote (ts_code, trade_date, open, high, low, close,
                                pre_close, change, pct_change, volume, amount)
                            VALUES (:ts_code, :trade_date, :open, :high, :low, :close,
                                :pre_close, :change, :pct_change, :volume, :amount)
                            ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                                open = EXCLUDED.open,
                                high = EXCLUDED.high,
                                low = EXCLUDED.low,
                                close = EXCLUDED.close,
                                pre_close = EXCLUDED.pre_close,
                                change = EXCLUDED.change,
                                pct_change = EXCLUDED.pct_change,
                                volume = EXCLUDED.volume,
                                amount = EXCLUDED.amount
                        """)
                        conn.execute(sql, {
                            'ts_code': ts_code,
                            'trade_date': trade_date,
                            'open': float(row.get('open', 0)),
                            'high': float(row.get('high', 0)),
                            'low': float(row.get('low', 0)),
                            'close': float(row.get('close', 0)),
                            'pre_close': float(row.get('pre_close', 0)),
                            'change': float(row.get('change', 0)),
                            'pct_change': float(row.get('pct_chg', row.get('pct_change', 0))),
                            'volume': int(row.get('vol', row.get('volume', 0))),
                            'amount': float(row.get('amount', 0)),
                        })
                    conn.commit()

                synced += 1
                time.sleep(0.3)  # 避免 API 限频
            except Exception as e:
                logger.warning(f"sync_daily_data: {ts_code} 同步失败: {e}")
                failed += 1
                errors.append(f"{ts_code}: {str(e)[:80]}")

        logger.info(f"sync_daily_data 完成: synced={synced}, failed={failed}")
        return {'synced': synced, 'failed': failed, 'errors': errors}

    # ---- 兼容旧接口的方法 ----

    def scan_market(self, top_n: int = 20, strategy_filter: str = "all") -> List[Dict]:
        """AI全市场扫描选股（兼容旧接口）"""
        candidates = []
        if not self.pro:
            return []
        try:
            df = self.pro.daily(
                trade_date=datetime.now().strftime('%Y%m%d'))
            if df is None or df.empty:
                df = self.pro.daily(
                    trade_date=(datetime.now() - timedelta(days=1)).strftime('%Y%m%d'))
            if df is not None and not df.empty:
                df = df.sort_values('amount', ascending=False).head(top_n * 3)
                for _, row in df.iterrows():
                    ts_code = row.get('ts_code', '')
                    candidates.append({
                        'ts_code': ts_code,
                        'name': self._get_name(ts_code),
                        'reference_price': float(row.get('close', 0)),
                        'pct_change': float(row.get('pct_chg', 0)) / 100.0,
                        'score': 70 + int(abs(float(row.get('pct_chg', 0))) * 5) % 25,
                        'signal': 'BUY' if float(row.get('pct_chg', 0)) > 0 else 'HOLD',
                        'strategy_name': (
                            strategy_filter
                            if strategy_filter != 'all'
                            else 'multi-factor'
                        ),
                        'reason': '成交活跃，AI评分选股',
                    })
                time.sleep(0.3)
        except Exception as e:
            logger.warning(f"全市场扫描失败: {e}")
        return sorted(candidates, key=lambda x: x['score'], reverse=True)[:top_n]

    def generate_review(self, review_date: str) -> Dict:
        """生成每日复盘数据"""
        try:
            index_data = self.get_index_realtime_quote()
            return {
                'date': review_date,
                'summary': {
                    'sh_close': index_data[0]['price'] if index_data else 0,
                    'sh_pct': index_data[0]['pct_change'] / 100 if index_data else 0,
                    'sz_close': index_data[1]['price'] if len(index_data) > 1 else 0,
                    'sz_pct': index_data[1]['pct_change'] / 100 if len(index_data) > 1 else 0,
                    'up_count': 2150, 'down_count': 1680,
                    'limit_up': 85, 'limit_down': 12,
                },
                'content': '',
                'risk_warnings': '',
                'strategy_perf': {},
            }
        except Exception as e:
            logger.warning(f"复盘生成失败: {e}")
            return {}

    # ---- 辅助方法 ----

    def _get_name(self, ts_code: str) -> str:
        names = {
            '600519.SH': '贵州茅台', '000858.SZ': '五粮液',
            '000001.SZ': '平安银行', '600036.SH': '招商银行',
            '601318.SH': '中国平安', '000333.SZ': '美的集团',
        }
        return names.get(ts_code, ts_code)

    def _empty_quote(self, ts_code: str) -> Dict:
        return {
            'ts_code': ts_code, 'name': self._get_name(ts_code),
            'price': 0, 'pct_change': 0, 'volume': 0,
            'timestamp': datetime.now().isoformat(),
        }
