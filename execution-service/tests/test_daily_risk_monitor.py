"""daily_risk_monitor 的「实盘接线」回归测试（2026-10-11 建立）。

背景（取证结论）：本脚本原从**模拟盘**文件（shared/claw_data/portfolio.json）
取 `live.holdings`，而该文件根本没有 `live` 字段 → `load_live_holdings()` 恒 []，
实盘检查块静默恒空、「缺数据告警」也永不触发。实盘权威源是国金账户文档
（顶层 `holdings[]` + `summary.total_assets`），与模拟盘**不是同一个文件**。

本文件钉住修复后的三条口径：
  1. 实盘持仓来自**实盘账户文档**（顶层 holdings / 兼容旧 live.holdings）
  2. 风控判定价优先用**实时价**，缺才回退组合快照价
  3. 取不到实盘源时**显式告警**，不静默当「无风险」

隔离要求（否则测试会写生产状态文件）：`RiskConfig.advanced_rules_state_path`
必须指向 tmp_path —— `run_all_checks` 内 `add_violation` 会**写盘**。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

from shared.risk_config import RiskConfig

# 脚本在 scripts/，用 importlib 按路径加载（scripts/ 不在 sys.path 上）。
# conftest 已把 execution-service 加入 sys.path，故 shared.* 可直接导入。
_SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location(
    "daily_risk_monitor", _SCRIPTS / "daily_risk_monitor.py"
)
drm = importlib.util.module_from_spec(_spec)
sys.modules["daily_risk_monitor"] = drm
_spec.loader.exec_module(drm)


# ──────────────────── 夹具 ────────────────────


class _FakeMarketData:
    """替身行情源：按 symbol 返回预置数据（不打网络）。"""

    def __init__(self, mapping: dict[str, dict]):
        self._mapping = mapping

    async def fetch_market_data(self, symbol: str) -> dict:
        return self._mapping.get(symbol, {})


def _write(path: pathlib.Path, data: dict) -> str:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """把三个可写/可读外部面全部隔离到 tmp_path，并返回构造器。"""
    cfg = RiskConfig(advanced_rules_state_path=str(tmp_path / "advanced_rules_state.json"))
    monkeypatch.setattr(drm, "FEISHU_WEBHOOK_URL", "")
    # 模拟盘镜像指向 tmp（无持仓），避免读到真实 shared/claw_data/
    monkeypatch.setattr(drm, "PORTFOLIO_PATH", str(tmp_path / "sim_portfolio.json"))

    def make(live_doc: dict | None):
        live_path = (
            _write(tmp_path / "live_portfolio.json", live_doc) if live_doc is not None else None
        )
        monkeypatch.setattr(drm, "LIVE_PORTFOLIO_CANDIDATES", [live_path] if live_path else [])
        monitor = drm.DailyRiskMonitor(cfg)
        return monitor, live_path

    return make


LIVE_DOC = {
    "broker": "国金证券",
    "summary": {"total_assets": 47949.72},
    "holdings": [
        {
            "code": "600584",
            "name": "长电科技",
            "shares": 200,
            "avg_cost": 94.656,
            "current_price": 66.33,  # 组合快照价（-29.9%）
            "bought_date": "2026-07-15",
        },
        {
            "code": "002185",
            "name": "华天科技",
            "shares": 500,
            "avg_cost": 22.829,
            "current_price": 16.0,
            "bought_date": "2026-07-15",
        },
    ],
}


# ──────────────────── 实盘源解析 ────────────────────


def test_live_holdings_from_top_level_holdings(isolated):
    monitor, _ = isolated(LIVE_DOC)
    holdings = monitor.load_live_holdings()
    assert [h["code"] for h in holdings] == ["600584", "002185"]


def test_live_holdings_from_legacy_live_wrapper(isolated):
    monitor, _ = isolated({"live": {"holdings": [{"code": "600036"}]}})
    assert monitor.load_live_holdings() == [{"code": "600036"}]


def test_live_total_from_summary(isolated):
    """实盘总资产在顶层 summary.total_assets（国金权威源），不是 live.total_assets。"""
    monitor, _ = isolated(LIVE_DOC)
    doc = monitor.load_live_portfolio()
    assert extract_live_total(doc) == pytest.approx(47949.72)


def extract_live_total(doc: dict) -> float:
    from services.advanced_risk_rules import extract_total_asset

    return extract_total_asset(doc, "live")


def test_no_live_source_warns_and_returns_empty(isolated, capsys):
    """取不到实盘源 → 显式告警（不静默当无风险），且不崩。"""
    monitor, _ = isolated(None)
    assert monitor.load_live_holdings() == []
    assert "[WARN]" in capsys.readouterr().out


def test_resolve_live_path_picks_first_existing(isolated):
    monitor, live_path = isolated(LIVE_DOC)
    assert monitor._resolve_live_path() == live_path


# ──────────────────── 判定价选择 ────────────────────


def test_current_price_prefers_realtime():
    h = {"current_price": 10.0}
    assert drm.DailyRiskMonitor._current_price({"current_price": 12.5}, h) == 12.5


def test_current_price_falls_back_to_snapshot():
    h = {"current_price": 10.0}
    assert drm.DailyRiskMonitor._current_price({}, h) == 10.0
    # 实时价字段存在但为 0/None（拉取失败）→ 也要回退，不能拿 0 当价
    assert drm.DailyRiskMonitor._current_price({"current_price": 0}, h) == 10.0


# ──────────────────── 端到端：实盘块真的跑起来 ────────────────────


async def test_run_checks_live_holdings_with_realtime_price(isolated, monkeypatch, capsys):
    """核心回归：实盘持仓被检查，且 R1 用的是**实时价**而非组合快照价。

    构造：快照价 66.33（已破 -8%），实时价 60.00（更深）——消息里应出现 60.00。
    """
    monitor, _ = isolated(LIVE_DOC)
    monkeypatch.setattr(
        drm,
        "MarketDataProvider",
        lambda *a, **k: _FakeMarketData({"sh600584": {"current_price": 60.0}}),
    )
    await monitor.run()
    out = capsys.readouterr().out
    assert "检查实盘持仓: 2 只" in out
    assert "60.00" in out  # R1 用实时价
    assert "66.33" not in out  # 不应再拿组合快照价做判定


async def test_run_warns_when_live_source_missing(isolated, monkeypatch, capsys):
    monitor, _ = isolated(None)
    monkeypatch.setattr(drm, "MarketDataProvider", lambda *a, **k: _FakeMarketData({}))
    await monitor.run()
    out = capsys.readouterr().out
    assert "实盘持仓为空" in out
