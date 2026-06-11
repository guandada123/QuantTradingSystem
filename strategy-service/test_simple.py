import sys
sys.path.insert(0, '.')

# 模拟 shared.middleware
class MockTraceId:
    def get(self): return "test-123"
trace_id_var = MockTraceId()
sys.modules['shared.middleware'] = type(sys)('shared.middleware')
sys.modules['shared.middleware'].trace_id_var = trace_id_var

# 模拟其他依赖
class MockDataService:
    def get_stock_daily_quote(self, *args, **kwargs): return []
    def get_stock_realtime_quote(self, *args, **kwargs): return {}
    def get_index_realtime_quote(self, *args, **kwargs): return {}
    def get_stock_fundamental(self, *args, **kwargs): return {}
    def get_stock_money_flow(self, *args, **kwargs): return {}
    def get_northbound_flow(self, *args, **kwargs): return {}
    def get_stock_pool(self, *args, **kwargs): return []
    def search_stocks(self, *args, **kwargs): return []

# 测试引擎
from services.stock_insight_engine import StockInsightEngine
engine = StockInsightEngine(MockDataService())
print("✓ 引擎初始化成功")
print(f"✓ 引擎方法: {[m for m in dir(engine) if m.startswith('scan_')]}")
