#!/usr/bin/env python3
"""
Stock Insight 集成测试脚本
测试新创建的选股引擎和API路由
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.data_service import DataService
from services.stock_insight_engine import StockInsightEngine, get_stock_insight_engine
from core.config import settings

def test_engine_initialization():
    """测试引擎初始化"""
    print("=== 测试引擎初始化 ===")
    
    try:
        # 初始化数据服务
        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        print(f"✓ DataService 初始化成功")
        
        # 初始化选股引擎
        engine = StockInsightEngine(ds)
        print(f"✓ StockInsightEngine 初始化成功")
        
        # 测试单例获取
        engine2 = get_stock_insight_engine(ds)
        print(f"✓ 单例获取成功: {engine is engine2}")
        
        return engine
        
    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        return None

def test_engine_methods(engine):
    """测试引擎方法"""
    print("\n=== 测试引擎方法 ===")
    
    try:
        # 测试主板精选
        print("测试主板精选...")
        mainboard_results = engine.scan_mainboard(top_n=5)
        print(f"✓ 主板精选返回 {len(mainboard_results)} 个结果")
        if mainboard_results:
            for i, stock in enumerate(mainboard_results[:3]):
                print(f"  {i+1}. {stock.get('code', 'N/A')} - {stock.get('name', 'N/A')}")
        
        # 测试理性选股
        print("\n测试理性选股...")
        rational_results = engine.scan_rational(top_n=5)
        print(f"✓ 理性选股返回 {len(rational_results)} 个结果")
        if rational_results:
            for i, stock in enumerate(rational_results[:3]):
                print(f"  {i+1}. {stock.get('code', 'N/A')} - {stock.get('selection_type', 'N/A')}")
        
        # 测试ML扫描
        print("\n测试ML增强扫描...")
        ml_results = engine.scan_ml(mode="mainboard", top_n=5)
        print(f"✓ ML扫描返回 {len(ml_results)} 个结果")
        if ml_results:
            for i, stock in enumerate(ml_results[:3]):
                print(f"  {i+1}. {stock.get('code', 'N/A')} - {stock.get('tier', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"✗ 引擎方法测试失败: {e}")
        return False

def test_api_structure():
    """测试API结构"""
    print("\n=== 测试API结构 ===")
    
    try:
        from api.stock_insight import router, ScanRequest, ScanResult, LatestResult
        
        print(f"✓ API路由导入成功: {router}")
        print(f"✓ 请求模型导入成功: {ScanRequest}")
        print(f"✓ 结果模型导入成功: {ScanResult}")
        print(f"✓ 最新结果模型导入成功: {LatestResult}")
        
        # 测试请求模型创建
        request = ScanRequest(
            scan_type="mainboard",
            top_n=10,
            owned_codes=["600519", "000858"]
        )
        print(f"✓ 请求模型创建成功: {request.dict()}")
        
        return True
        
    except Exception as e:
        print(f"✗ API结构测试失败: {e}")
        return False

def test_main_integration():
    """测试主程序集成"""
    print("\n=== 测试主程序集成 ===")
    
    try:
        with open("main.py", "r") as f:
            content = f.read()
            
        if "stock_insight_router" in content and "Stock Insight选股" in content:
            print("✓ 主程序路由注册正确")
        else:
            print("✗ 主程序路由注册缺失")
            return False
        
        # 检查导入
        if "from api.stock_insight import router as stock_insight_router" in content:
            print("✓ 主程序导入正确")
        else:
            print("✗ 主程序导入缺失")
            return False
        
        return True
        
    except Exception as e:
        print(f"✗ 主程序集成测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("Stock Insight 集成测试")
    print("=" * 50)
    
    # 测试引擎初始化
    engine = test_engine_initialization()
    if not engine:
        print("\n❌ 引擎初始化测试失败")
        return 1
    
    # 测试引擎方法
    if not test_engine_methods(engine):
        print("\n❌ 引擎方法测试失败")
        return 1
    
    # 测试API结构
    if not test_api_structure():
        print("\n❌ API结构测试失败")
        return 1
    
    # 测试主程序集成
    if not test_main_integration():
        print("\n❌ 主程序集成测试失败")
        return 1
    
    print("\n" + "=" * 50)
    print("✅ 所有测试通过！Stock Insight 集成成功")
    print("\n可用API端点:")
    print("  POST   /api/v1/stock-insight/scan     - 触发选股扫描")
    print("  GET    /api/v1/stock-insight/results/{scan_id} - 查询扫描结果")
    print("  GET    /api/v1/stock-insight/latest   - 获取最新选股结果")
    print("  GET    /api/v1/stock-insight/types    - 获取支持的扫描类型")
    print("  GET    /api/v1/stock-insight/health   - 健康检查")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())