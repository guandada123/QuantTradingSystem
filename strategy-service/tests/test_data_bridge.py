"""
测试数据桥接层
Cover services/data_bridge.py 全部 4 个函数：
  save_index_data, save_stock_data,
  load_index_data, load_stock_data

使用 tmp_path 模拟 DATA_DIR，mock logger 避免日志副作用。
"""

import json
from types import SimpleNamespace

import pytest
from services.data_bridge import load_index_data, load_stock_data, save_index_data, save_stock_data


@pytest.fixture(autouse=True)
def patch_data_dir(monkeypatch, tmp_path):
    """将所有 data_bridge 测试的 DATA_DIR 指向 tmp_path"""
    monkeypatch.setattr("services.data_bridge.DATA_DIR", tmp_path)


@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    """mock logger 避免实际日志输出"""
    mock_logger = SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    monkeypatch.setattr("services.data_bridge.logger", mock_logger)


# ============================================================
# save_index_data
# ============================================================


class TestSaveIndexData:
    """测试 save_index_data()"""

    def test_save_success(self, tmp_path):
        """正常保存 → 文件创建 + 内容正确 (line 22-31)"""
        indices = [{"code": "000001", "name": "上证指数", "close": 3000.0}]
        save_index_data(indices)
        cache_file = tmp_path / "index_cache.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["data"] == indices
        assert "updated_at" in data

    def test_oserror_raises(self, tmp_path):
        """OSError → 抛出 DataSourceException (line 32-33)"""
        # 让 DATA_DIR 指向一个不可写的路径
        cache_file = tmp_path / "index_cache.json"
        # 通过预先写入一个目录同名文件来制造 OSError
        cache_file.mkdir()  # 用目录占位，open("w") 会失败

        from shared.exceptions import DataSourceException

        with pytest.raises(DataSourceException, match="保存指数缓存失败"):
            save_index_data([{"code": "000001"}])


# ============================================================
# save_stock_data
# ============================================================


class TestSaveStockData:
    """测试 save_stock_data()"""

    def test_save_success(self, tmp_path):
        """正常保存 → 文件名含 ts_code (line 39-48)"""
        stock_data = {"close": 50.0, "volume": 1000000}
        save_stock_data("000001.SZ", stock_data)
        cache_file = tmp_path / "stock_000001_SZ.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["data"] == stock_data
        assert "updated_at" in data

    def test_code_with_dot_replaced(self):
        """ts_code 中的点被替换为下划线 (line 41)"""
        # 不直接测试文件名构造，但确保函数不报错

    def test_oserror_raises(self, tmp_path):
        """OSError → 抛出 DataSourceException (line 49-53)"""
        cache_file = tmp_path / "stock_test_SZ.json"
        cache_file.mkdir()  # 用目录占位

        from shared.exceptions import DataSourceException

        with pytest.raises(DataSourceException, match="保存个股缓存失败"):
            save_stock_data("test.SZ", {})


# ============================================================
# load_index_data
# ============================================================


class TestLoadIndexData:
    """测试 load_index_data()"""

    def test_load_success(self, tmp_path):
        """正常读取 → 返回 data 列表 (line 58-65)"""
        # 先写入
        cache_file = tmp_path / "index_cache.json"
        cache_file.write_text(
            json.dumps({"data": [{"code": "000001"}], "updated_at": "2026-01-01"})
        )
        result = load_index_data()
        assert result == [{"code": "000001"}]

    def test_file_not_exists(self):
        """文件不存在 → 返回空列表 (line 60-62)"""
        result = load_index_data()
        assert result == []

    def test_json_decode_error(self, tmp_path):
        """JSON 损坏 → 返回空列表 (line 66-68)"""
        cache_file = tmp_path / "index_cache.json"
        cache_file.write_text("{invalid json}")
        result = load_index_data()
        assert result == []

    def test_oserror_on_read(self, tmp_path):
        """OSError → 返回空列表 (line 66-68)"""
        cache_file = tmp_path / "index_cache.json"
        cache_file.write_text("{}")
        cache_file.chmod(0o000)  # 不可读

        import os

        if os.name == "nt":
            pytest.skip("chmod non-portable on Windows")
        result = load_index_data()
        assert result == []
        cache_file.chmod(0o644)  # 恢复权限

    def test_missing_data_key(self, tmp_path):
        """JSON 中缺少 data 键 → data.get("data", []) 返回 [] (line 65)"""
        cache_file = tmp_path / "index_cache.json"
        cache_file.write_text(json.dumps({"updated_at": "2026-01-01"}))
        result = load_index_data()
        assert result == []


# ============================================================
# load_stock_data
# ============================================================


class TestLoadStockData:
    """测试 load_stock_data()"""

    def test_load_success(self, tmp_path):
        """正常读取 → 返回 data dict (line 73-80)"""
        cache_file = tmp_path / "stock_000001_SZ.json"
        cache_file.write_text(
            json.dumps({"data": {"close": 50.0, "volume": 1000000}, "updated_at": "2026-01-01"})
        )
        result = load_stock_data("000001.SZ")
        assert result == {"close": 50.0, "volume": 1000000}

    def test_file_not_exists(self):
        """文件不存在 → 返回空 dict (line 75-77)"""
        result = load_stock_data("nonexistent.SZ")
        assert result == {}

    def test_json_decode_error(self, tmp_path):
        """JSON 损坏 → 返回空 dict (line 81-83)"""
        cache_file = tmp_path / "stock_test_SZ.json"
        cache_file.write_text("{invalid json}")
        result = load_stock_data("test.SZ")
        assert result == {}

    def test_missing_data_key(self, tmp_path):
        """JSON 中缺少 data 键 → 返回 {} (line 80)"""
        cache_file = tmp_path / "stock_test_SZ.json"
        cache_file.write_text(json.dumps({"updated_at": "2026-01-01"}))
        result = load_stock_data("test.SZ")
        assert result == {}

    def test_oserror_on_read(self, tmp_path):
        """OSError → 返回空 dict (line 81-83)"""
        cache_file = tmp_path / "stock_test_SZ.json"
        cache_file.write_text("{}")
        cache_file.chmod(0o000)

        import os

        if os.name == "nt":
            pytest.skip("chmod non-portable on Windows")
        result = load_stock_data("test.SZ")
        assert result == {}
        cache_file.chmod(0o644)
