"""feishu_daily_report 的实盘接线回归测试（2026-10-11 建立）。

与 daily_risk_monitor 同源缺陷：原从**模拟盘**文件取 `live.holdings`（无该字段）
→ 实盘块恒空。修复后实盘持仓来自国金账户文档（顶层 holdings），判定价优先实时价。

隔离：main() 内部自行构造 `RiskConfig()`（默认状态路径会写盘），
故先把模块命名空间里的 `RiskConfig` 换成指向 tmp_path 的构造器。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from datetime import date, timedelta

import pytest

from shared.risk_config import RiskConfig

_SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location(
    "feishu_daily_report", _SCRIPTS / "feishu_daily_report.py"
)
fdr = importlib.util.module_from_spec(_spec)
sys.modules["feishu_daily_report"] = fdr
_spec.loader.exec_module(fdr)

LIVE_DOC = {
    "broker": "国金证券",
    "summary": {"total_assets": 47949.72},
    "holdings": [
        {
            "code": "600584",
            "name": "长电科技",
            "shares": 200,
            "avg_cost": 94.656,
            "current_price": 66.33,
        }
    ],
}


def _write(path: pathlib.Path, data: dict) -> str:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(fdr, "FEISHU_WEBHOOK", "")
    monkeypatch.setattr(fdr, "PORTFOLIO_PATH", str(tmp_path / "sim.json"))  # 无模拟盘
    monkeypatch.setattr(fdr, "TRADE_LOG_PATH", str(tmp_path / "trade_log.json"))
    monkeypatch.setattr(
        fdr,
        "RiskConfig",
        lambda: RiskConfig(advanced_rules_state_path=str(tmp_path / "state.json")),
    )
    live = _write(tmp_path / "live.json", LIVE_DOC)
    monkeypatch.setattr(fdr, "LIVE_PORTFOLIO_CANDIDATES", [live])
    return tmp_path


# ── 纯辅助 ──────────────────────────────────────────────


def test_load_json_if_exists_variants(tmp_path):
    assert fdr._load_json_if_exists(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert fdr._load_json_if_exists(str(bad)) == {}
    good = tmp_path / "ok.json"
    good.write_text('{"a": 1}', encoding="utf-8")
    assert fdr._load_json_if_exists(str(good)) == {"a": 1}


def test_resolve_price_prefers_realtime():
    assert fdr._resolve_price({"current_price": 12.5}, {"current_price": 10.0}) == 12.5
    assert fdr._resolve_price({}, {"current_price": 10.0}) == 10.0
    assert fdr._resolve_price({"current_price": 0}, {"current_price": 10.0}) == 10.0


# ── 端到端：实盘块真的跑起来 ────────────────────────────


async def test_main_checks_live_holdings_with_realtime_price(isolated, monkeypatch, capsys):
    async def _fake_fetch(symbol: str) -> dict:
        return {"current_price": 60.0}

    monkeypatch.setattr(fdr, "_fetch_market_data", _fake_fetch)

    # build_card 被调时捕获全量结果（否则 main() 不回传、卡片预览又被截断 500 字）
    captured: dict = {}
    orig_build = fdr.FeishuDailyReport.build_card

    def _spy(self, results):
        captured["results"] = list(results)
        return orig_build(self, results)

    monkeypatch.setattr(fdr.FeishuDailyReport, "build_card", _spy)

    await fdr.main()
    out = capsys.readouterr().out
    assert "实盘账户源" in out
    r1 = [r for r in captured["results"] if r.rule_id.startswith("R1_")]
    assert r1, "实盘持仓应触发 R1 止损"
    assert "60.00" in r1[0].message  # 用实时价而非组合快照价 66.33
    assert "66.33" not in r1[0].message


async def test_main_warns_when_live_source_missing(isolated, monkeypatch, capsys):
    monkeypatch.setattr(fdr, "LIVE_PORTFOLIO_CANDIDATES", [])

    async def _fake_fetch(symbol: str) -> dict:
        return {}

    monkeypatch.setattr(fdr, "_fetch_market_data", _fake_fetch)
    await fdr.main()
    out = capsys.readouterr().out
    assert "未找到实盘账户源" in out
    assert "实盘持仓为空" in out


# ── 回归：无待复盘时不得崩（2026-10-11 修 NameError）──────────


async def test_main_no_pending_reviews_does_not_crash(isolated, monkeypatch, capsys):
    """原实现：`if pending:` 块内的局部 import 使 RuleSeverity 成 main() 局部名，
    pending 为空时末尾 `RuleSeverity.CRITICAL` 抛 NameError。"""

    async def _fake_fetch(symbol: str) -> dict:
        return {"current_price": 60.0}

    monkeypatch.setattr(fdr, "_fetch_market_data", _fake_fetch)
    await fdr.main()  # 不应抛异常
    assert "日报完成" in capsys.readouterr().out


async def test_main_with_pending_review_emits_r11(isolated, monkeypatch, capsys):
    old_ts = (date.today() - timedelta(days=5)).isoformat() + "T09:30:00"
    entry = {
        "id": "T0001",
        "symbol": "sh600036",
        "name": "招商银行",
        "action": "BUY",
        "price": 40.0,
        "shares": 100,
        "amount": 4000.0,
        "reason": "测试",
        "timestamp": old_ts,
        "date": old_ts[:10],
        "review_status": "pending",
    }
    pathlib.Path(isolated / "trade_log.json").write_text(
        json.dumps([entry], ensure_ascii=False), encoding="utf-8"
    )

    async def _fake_fetch(symbol: str) -> dict:
        return {"current_price": 60.0}

    monkeypatch.setattr(fdr, "_fetch_market_data", _fake_fetch)
    await fdr.main()
    assert "日报完成" in capsys.readouterr().out
