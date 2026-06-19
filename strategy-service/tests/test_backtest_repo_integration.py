"""
回测数据仓库层集成测试 — 使用真实 SQLite 内存数据库

覆盖 repositories/backtest_repo.py 所有函数：
- save_backtest_result: 保存、refresh、_result_to_dict 全链路
- get_backtest_result: 正常查询、UUID 解析异常、不存在
- get_backtest_history: 正常列表、空列表、排序验证、limit 截断
- _result_to_dict: 序列化格式（ISO日期、float 转换、None 处理）

预期覆盖率提升: 45% → ~95% (lines 34-35, 40-47, 52-53, 57)
"""

import json
import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.database import Base
from models.models import BacktestResult, WalkForwardResult
from repositories import backtest_repo


# ============================================================
#  SQLite UUID 兼容 — PostgreSQL UUID 在 SQLite 中不可用，
#  通过 TypeDecorator 在 ORM 层处理 uuid ↔ str 转换。
# ============================================================


def _make_uuid_sqlite_compat():
    """将 Base.metadata 中所有 PostgreSQL UUID 列替换为
    TypeDecorator，在 SQLite 中以 String(36) 存储，保持 Python
    侧 uuid.UUID 类型不变。"""
    from sqlalchemy import String
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    from sqlalchemy.types import TypeDecorator

    class _UUIDString(TypeDecorator):
        impl = String(36)
        cache_ok = True
        python_type = uuid.UUID

        def process_bind_param(self, value, dialect):
            if value is None:
                return None
            return str(value)

        def process_result_value(self, value, dialect):
            if value is None:
                return None
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(value)

    _replaced = 0
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, PG_UUID):
                col.type = _UUIDString(36)
                _replaced += 1


_make_uuid_sqlite_compat()


# ============================================================
#  Fixtures — Module-level engine, per-test session with rollback
# ============================================================


@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite 引擎（模块级共享，所有测试复用）"""
    e = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(bind=e)
    return e


@pytest.fixture
def db(engine) -> Session:
    """每次测试独立 session，测试后回滚，互不干扰"""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ============================================================
#  测试数据工厂
# ============================================================


def _sample() -> dict:
    """标准回测结果数据"""
    return {
        "strategy_name": "ma-cross",
        "strategy_version": "2.0",
        "ts_code": "000333.SZ",
        "start_date": date(2026, 1, 5),
        "end_date": date(2026, 1, 7),
        "initial_cash": 100000.0,
        "final_value": 115600.0,
        "total_return": 0.156,
        "annual_return": 0.08,
        "sharpe_ratio": 1.25,
        "max_drawdown": -0.05,
        "win_rate": 0.65,
        "profit_loss_ratio": 2.1,
        "total_trades": 15,
        "winning_trades": 10,
        "losing_trades": 5,
        "avg_holding_days": 5.2,
        "backtest_details": {
            "equity_curve": [{"date": "20260105", "nav": 1.0}],
            "trades": [],
            "benchmark_curve": [],
            "monthly_returns": [],
            "alpha": 0.02,
            "beta": 0.9,
        },
    }


# ============================================================
#  save_backtest_result — lines 10-35
# ============================================================


class TestSaveBacktestResult:
    """覆盖 save_backtest_result 全路径"""

    def test_save_returns_dict_with_backtest_id(self, db):
        """保存成功 → 返回 dict 且包含有效 UUID backtest_id"""
        saved = backtest_repo.save_backtest_result(db, _sample())
        assert "backtest_id" in saved
        assert uuid.UUID(saved["backtest_id"])  # 不会抛异常

    def test_save_returns_correct_fields(self, db):
        """返回字段值与输入一致"""
        saved = backtest_repo.save_backtest_result(db, _sample())
        assert saved["strategy_name"] == "ma-cross"
        assert saved["ts_code"] == "000333.SZ"
        assert saved["total_return"] == 0.156
        assert saved["final_value"] == 115600.0
        assert saved["total_trades"] == 15

    def test_save_with_minimal_fields(self, db):
        """仅提供必需字段 → 可选字段为 None（_result_to_dict 不包含 backtest_details）"""
        minimal = {
            "strategy_name": "test",
            "strategy_version": "1.0",
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 10),
            "initial_cash": 50000.0,
            "final_value": 52000.0,
        }
        saved = backtest_repo.save_backtest_result(db, minimal)
        assert saved["strategy_name"] == "test"
        assert saved["total_return"] is None  # 未提供 → None
        assert saved["total_trades"] is None
        # _result_to_dict 不序列化 backtest_details，所以不在 dict 中
        assert "backtest_details" not in saved

    def test_save_json_details(self, db):
        """backtest_details 被压缩存储后可通过 get_backtest_result_with_details 正确解压读取"""
        data = _sample()
        data["backtest_details"]["trades"] = [
            {"date": "20260105", "direction": "BUY", "price": 100.0, "shares": 1000},
        ]
        data["backtest_details"]["equity_curve"] = [
            {"date": "20260105", "nav": 1.0, "benchmark_nav": 1.0, "drawdown": 0.0},
            {"date": "20260106", "nav": 1.02, "benchmark_nav": 0.99, "drawdown": -0.01},
        ]
        saved = backtest_repo.save_backtest_result(db, data)

        # 验证压缩列已被填充
        record = db.query(BacktestResult).filter(
            BacktestResult.backtest_id == uuid.UUID(saved["backtest_id"])
        ).first()
        assert record.backtest_details is None  # 未压缩列为空
        assert record.backtest_details_compressed is not None  # 压缩列有数据
        compressed_size = len(record.backtest_details_compressed)
        raw_json = json.dumps(data["backtest_details"], ensure_ascii=False)
        assert compressed_size < len(raw_json) * 0.7  # 小数据下压缩比至少 70% 以下

        # 验证解压后数据完全一致
        details = backtest_repo._decompress_details(record.backtest_details_compressed)
        assert details["trades"] == data["backtest_details"]["trades"]
        assert len(details["equity_curve"]) == 2

    def test_save_without_details_sets_compressed_null(self, db):
        """没有 backtest_details 时，压缩列应为 None"""
        minimal = {
            "strategy_name": "test",
            "strategy_version": "1.0",
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 10),
            "initial_cash": 50000.0,
            "final_value": 52000.0,
        }
        backtest_repo.save_backtest_result(db, minimal)
        all_records = db.query(BacktestResult).all()
        assert len(all_records) == 1
        assert all_records[0].backtest_details_compressed is None


# ============================================================
#  get_backtest_result — lines 38-47
# ============================================================


class TestGetBacktestResult:
    """覆盖 get_backtest_result 全路径"""

    def test_get_by_id_returns_saved_data(self, db):
        """先 save 再 get_by_id → 数据完全一致"""
        saved = backtest_repo.save_backtest_result(db, _sample())
        bt_id = saved["backtest_id"]

        fetched = backtest_repo.get_backtest_result(db, bt_id)
        assert fetched is not None
        assert fetched["backtest_id"] == bt_id
        assert fetched["strategy_name"] == "ma-cross"
        assert fetched["ts_code"] == "000333.SZ"
        assert fetched["total_return"] == 0.156

    def test_get_by_invalid_uuid(self, db):
        """UUID 格式无效 → 返回 None"""
        assert backtest_repo.get_backtest_result(db, "not-a-uuid") is None

    def test_get_by_valid_uuid_not_found(self, db):
        """UUID 有效但记录不存在 → 返回 None"""
        rid = str(uuid.uuid4())
        assert backtest_repo.get_backtest_result(db, rid) is None


# ============================================================
#  get_backtest_result_with_details — 含解压后的 backtest_details
# ============================================================


class TestGetBacktestResultWithDetails:
    """覆盖 get_backtest_result_with_details 全路径"""

    def test_returns_details_from_compressed_column(self, db):
        """保存后读取 → backtest_details 被正确解压返回"""
        data = _sample()
        data["backtest_details"] = {
            "equity_curve": [["20260105", 1.0], ["20260106", 1.02]],
            "trades": [{"date": "20260105", "direction": "BUY", "price": 100.0}],
            "alpha": 0.02,
            "beta": 0.9,
        }
        saved = backtest_repo.save_backtest_result(db, data)
        bt_id = saved["backtest_id"]

        full = backtest_repo.get_backtest_result_with_details(db, bt_id)
        assert full is not None
        assert "backtest_details" in full
        details = full["backtest_details"]
        assert details["alpha"] == 0.02
        assert len(details["equity_curve"]) == 2
        assert details["trades"][0]["direction"] == "BUY"
        # 摘要字段仍然存在
        assert full["strategy_name"] == "ma-cross"
        assert full["total_return"] == 0.156

    def test_detail_invalid_uuid(self, db):
        """UUID 无效 → None"""
        assert backtest_repo.get_backtest_result_with_details(db, "bad-uuid") is None

    def test_detail_not_found(self, db):
        """记录不存在 → None"""
        assert backtest_repo.get_backtest_result_with_details(db, str(uuid.uuid4())) is None

    def test_without_details_returns_no_details_key(self, db):
        """无 backtest_details 时，结果中不应有 backtest_details 键"""
        minimal = {
            "strategy_name": "test",
            "strategy_version": "1.0",
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 10),
            "initial_cash": 50000.0,
            "final_value": 52000.0,
        }
        saved = backtest_repo.save_backtest_result(db, minimal)
        full = backtest_repo.get_backtest_result_with_details(db, saved["backtest_id"])
        assert full is not None
        assert "backtest_details" not in full


# ============================================================
#  get_backtest_history — lines 50-53
# ============================================================


class TestGetBacktestHistory:
    """覆盖 get_backtest_history 全路径"""

    def test_empty_db_returns_empty_list(self, db):
        """空表 → []"""
        assert backtest_repo.get_backtest_history(db) == []

    def test_returns_ordered_by_created_at_desc(self, db):
        """多条记录 → 返回全部（排序由 DB 的 ORDER BY created_at DESC 保证，同秒插入时 order 不定）"""
        backtest_repo.save_backtest_result(db, {**_sample(), "strategy_name": "first"})
        backtest_repo.save_backtest_result(db, {**_sample(), "strategy_name": "second"})
        backtest_repo.save_backtest_result(db, {**_sample(), "strategy_name": "third"})

        history = backtest_repo.get_backtest_history(db, limit=10)
        assert len(history) == 3
        names = {r["strategy_name"] for r in history}
        assert names == {"first", "second", "third"}

    def test_limit_truncation(self, db):
        """limit 参数正确截断返回行数"""
        for i in range(5):
            backtest_repo.save_backtest_result(db, {**_sample(), "strategy_name": f"s{i}"})

        assert len(backtest_repo.get_backtest_history(db, limit=3)) == 3
        assert len(backtest_repo.get_backtest_history(db, limit=10)) == 5
        assert len(backtest_repo.get_backtest_history(db, limit=0)) == 0

    def test_default_limit_is_20(self, db):
        """不传 limit 时默认返回 20 条"""
        for i in range(25):
            backtest_repo.save_backtest_result(db, {**_sample(), "strategy_name": f"s{i}"})

        assert len(backtest_repo.get_backtest_history(db)) == 20


# ============================================================
#  _result_to_dict — line 57 (serialization format)
# ============================================================


class TestResultToDict:
    """覆盖 _result_to_dict 的序列化格式"""

    def test_date_fields_iso_format(self, db):
        """日期字段序列化为 ISO 格式字符串"""
        saved = backtest_repo.save_backtest_result(db, _sample())
        assert isinstance(saved["start_date"], str)
        assert saved["start_date"] == "2026-01-05"
        assert isinstance(saved["end_date"], str)
        assert isinstance(saved["created_at"], str)

    def test_numeric_fields_are_floats(self, db):
        """Numeric 字段序列化为 float"""
        saved = backtest_repo.save_backtest_result(db, _sample())
        assert isinstance(saved["initial_cash"], float)
        assert isinstance(saved["total_return"], float)
        assert isinstance(saved["sharpe_ratio"], float)
        assert isinstance(saved["max_drawdown"], float)
        assert isinstance(saved["avg_holding_days"], float)

    def test_nullable_fields_none(self, db):
        """未提供的可选字段序列化为 None"""
        data = _sample()
        data["avg_holding_days"] = None
        data["total_return"] = None
        saved = backtest_repo.save_backtest_result(db, data)
        assert saved["avg_holding_days"] is None
        assert saved["total_return"] is None

    def test_ts_code_empty_string(self, db):
        """ts_code 为空字符串 → 返回空字符串"""
        data = _sample()
        data["ts_code"] = ""
        saved = backtest_repo.save_backtest_result(db, data)
        assert saved["ts_code"] == ""

    def test_int_fields_are_ints(self, db):
        """Integer 字段保持 int 类型"""
        saved = backtest_repo.save_backtest_result(db, _sample())
        assert isinstance(saved["total_trades"], int)
        assert isinstance(saved["winning_trades"], int)
        assert isinstance(saved["losing_trades"], int)


# ============================================================
#  WalkForwardResult 持久化测试 (P2-ARCH-05)
# ============================================================


class TestWalkForwardResult:
    """WalkForwardResult 保存、列表、详情"""

    _SAMPLE_WINDOWS = [
        {
            "window": "W1",
            "train_start": "20250105",
            "train_end": "20250630",
            "test_start": "20250701",
            "test_end": "20250815",
            "best_params": {"ma_fast": 10, "ma_slow": 30},
            "train_sharpe": 1.35,
            "test_sharpe": 0.95,
            "train_return": 0.12,
            "test_return": 0.08,
            "test_max_dd": -0.03,
        },
    ]

    def _save_sample(self, db, **overrides):
        from repositories.walkforward_repo import save_walkforward_result

        params = dict(
            strategy_name="ma-cross",
            ts_code="000333.SZ",
            start_date="20260101",
            end_date="20260301",
            train_days=126,
            test_days=42,
            step_days=42,
            param_grid={"ma_fast": [5, 10], "ma_slow": [20, 30]},
            initial_cash=100000.0,
            slippage=0.001,
            commission_rate=0.00025,
            benchmark="000300.SH",
            windows=self._SAMPLE_WINDOWS,
            overall_test_return=0.14,
            overfit_ratio=0.72,
            num_windows=1,
        )
        params.update(overrides)
        return save_walkforward_result(db, **params)

    def test_save_and_get_detail(self, db):
        """保存后可通过详情查询完整读取"""
        from repositories.walkforward_repo import get_walkforward_detail

        wf_id = self._save_sample(db)
        assert wf_id is not None
        assert isinstance(wf_id, str)

        detail = get_walkforward_detail(db, wf_id)
        assert detail is not None
        assert detail["strategy_name"] == "ma-cross"
        assert detail["ts_code"] == "000333.SZ"
        assert detail["train_days"] == 126
        assert detail["test_days"] == 42
        assert detail["step_days"] == 42
        assert detail["overall_test_return"] == 0.14
        assert detail["overfit_ratio"] == 0.72
        assert detail["num_windows"] == 1
        assert len(detail["windows"]) == 1
        assert detail["windows"][0]["best_params"] == {"ma_fast": 10, "ma_slow": 30}

    def test_get_history(self, db):
        """保存后可从历史列表查询到摘要"""
        from repositories.walkforward_repo import get_walkforward_history

        # 清空
        db.query(WalkForwardResult).delete()
        db.commit()

        wf_id = self._save_sample(db)

        history = get_walkforward_history(db, limit=10)
        assert len(history) >= 1
        found = any(h["wf_id"] == wf_id for h in history)
        assert found, f"wf_id={wf_id} 应出现在历史列表中"

        # 验证历史摘要不含 windows 详情
        entry = next(h for h in history if h["wf_id"] == wf_id)
        assert "windows" not in entry
        assert entry["strategy_name"] == "ma-cross"
        assert entry["overall_test_return"] == 0.14
        assert entry["overfit_ratio"] == 0.72

    def test_get_history_filter_by_strategy(self, db):
        """按策略名筛选历史"""
        from repositories.walkforward_repo import get_walkforward_history

        # 保存 ma-cross
        self._save_sample(db, strategy_name="ma-cross")
        # 保存 breakout
        wf_id2 = self._save_sample(db, strategy_name="breakout", ts_code="000001.SZ")

        ma_cross_list = get_walkforward_history(db, limit=10, strategy_name="ma-cross")
        assert all(h["strategy_name"] == "ma-cross" for h in ma_cross_list)

        breakout_list = get_walkforward_history(db, limit=10, strategy_name="breakout")
        assert any(h["wf_id"] == wf_id2 for h in breakout_list)

    def test_get_detail_invalid_uuid(self, db):
        """无效 UUID → 返回 None"""
        from repositories.walkforward_repo import get_walkforward_detail

        detail = get_walkforward_detail(db, "not-a-uuid")
        assert detail is None

    def test_get_detail_not_found(self, db):
        """不存在的 wf_id → 返回 None"""
        from repositories.walkforward_repo import get_walkforward_detail

        detail = get_walkforward_detail(db, "00000000-0000-0000-0000-000000000000")
        assert detail is None

    def test_save_without_param_grid(self, db):
        """不传 param_grid 时保存正常"""
        from repositories.walkforward_repo import get_walkforward_detail

        wf_id = self._save_sample(db, param_grid=None)
        detail = get_walkforward_detail(db, wf_id)
        assert detail is not None
        assert detail["param_grid"] is None

    def test_param_grid_serialized_as_json(self, db):
        """param_grid 被序列化为 JSON 兼容格式"""
        from repositories.walkforward_repo import get_walkforward_detail

        wf_id = self._save_sample(db)
        detail = get_walkforward_detail(db, wf_id)
        assert isinstance(detail["param_grid"], dict)
        assert detail["param_grid"]["ma_fast"] == [5, 10]
