"""数据源探活失败分类 + 告警文案作用域的回归测试。

背景（2026-11-25 11:02 群告警「数据源不可达」）：启动自检把「一条行情接口失败」
写成了「整个数据源不可用」，与同仓 services/data_quality.py 的探活结论互斥，
属于把可用说成不可用。本测试锁住三件事：

1. 分类器：连接层/DNS/代理/证书 → 数据源级；超时、远端断连、HTTP 错误 → 接口级；
   认不出的 → 未知（保守，仍按数据源级出告警）。注意 requests 的 HTTPError / Timeout
   都是 RuntimeError 的子类，必须按**类名**识别，否则会落到「未知」升级成数据源告警。
2. 文案作用域：只有数据源级失败才允许出现「数据源不可达」这个标题；
   接口级失败必须是 INFO 级。
3. 执行路径：直接驱动 lifespan 的探活失败分支（假 akshare + 假告警服务），
   确认接口级失败发出的是 INFO「行情接口瞬时失败」、数据源级失败才发 WARNING
   「数据源不可达」，且两条路径都**不会**因为引用异常对象而炸掉（静默）。

判定时**先剥掉注释行**：改动说明里会引用旧标题，那不是告警文案本身。
"""

from __future__ import annotations

import ast
import asyncio
import re
import sys
import types
from http.client import RemoteDisconnected
from pathlib import Path

import requests.exceptions as rq

SERVICE_DIR = Path(__file__).resolve().parent.parent
MAIN_PY = SERVICE_DIR / "main.py"
SOURCE = MAIN_PY.read_text(encoding="utf-8")

LEGACY_TITLE = "数据源不可达"


def _code_only(text: str) -> str:
    """去掉整行注释与空行，只留真正的代码行。"""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


# ---------------------------------------------------------------- 分类器

WANTED_NAMES = {
    "classify_source_probe_error",
    "_SOURCE_LEVEL_ERRORS",
    "PROBE_KIND_ENDPOINT",
    "PROBE_KIND_SOURCE",
    "PROBE_KIND_UNKNOWN",
}


def _classify_ns() -> dict:
    """从 main.py 里取分类器相关模块级对象（不 import 整个 FastAPI 应用）。"""
    tree = ast.parse(SOURCE)
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in WANTED_NAMES:
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            names = {getattr(t, "id", None) for t in node.targets}
            if names & WANTED_NAMES:
                nodes.append(node)
        elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) in WANTED_NAMES:
            nodes.append(node)
    ns: dict = {"__builtins__": __builtins__, "BaseException": BaseException}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MAIN_PY), "exec"), ns)  # noqa: S102
    assert "classify_source_probe_error" in ns, (
        "main.py 里没有 classify_source_probe_error —— 分类逻辑不存在，探活失败仍会一律说成数据源不可用"
    )
    return ns


def test_source_error_classification():
    """DNS/代理/证书类异常必须判成「数据源级」。"""
    classify = _classify_ns()["classify_source_probe_error"]
    assert (
        classify(OSError("NameResolutionError: Failed to resolve push2.eastmoney.com"))
        == "数据源级"
    )
    assert classify(OSError("ProxyError: tunnel connection failed")) == "数据源级"
    assert classify(OSError("SSLError: certificate verify failed")) == "数据源级"


def test_endpoint_error_classification():
    """单接口抖动必须判成「接口级」，不能升级成数据源不可用。"""
    classify = _classify_ns()["classify_source_probe_error"]
    assert classify(RemoteDisconnected("Remote end closed connection without response")) == "接口级"
    assert classify(TimeoutError("read timeout=5")) == "接口级"
    assert classify(ConnectionError("Connection aborted")) == "接口级"
    # requests 这三类都是 RuntimeError 子类：只靠 isinstance(OSError) 会判不出来
    assert classify(rq.HTTPError("502 Server Error for url")) == "接口级"
    assert classify(rq.ReadTimeout("HTTPSConnectionPool read timed out")) == "接口级"
    assert classify(rq.ConnectionError("node is down")) == "接口级"


def test_unknown_falls_back_conservatively():
    """认不出的异常标「未知」，在文案分支里走 else 即按数据源级告警，不得静默。"""
    ns = _classify_ns()
    classify = ns["classify_source_probe_error"]
    assert classify(ValueError("unexpected payload")) == "未知"
    assert ns["PROBE_KIND_ENDPOINT"] == "接口级"


# ---------------------------------------------------------------- 文案作用域


def _startup_probe_block() -> str:
    """切出 lifespan 里数据源探活那段（AK 检查 → 告警发送），并剥掉注释行。"""
    start = SOURCE.index("import akshare as ak")
    end = SOURCE.index("启动后台任务", start)
    return _code_only(SOURCE[start:end])


def test_no_legacy_alert_for_instant_failure():
    """接口级失败不得使用「数据源不可达」标题。

    旧实现（改动前）是 `title="数据源不可达"` 无条件发送，本断言在旧实现上必然失败。
    """
    block = _startup_probe_block()
    titles = re.findall(r'title="([^"]+)"', block)
    assert titles, "探活失败分支里没有任何告警标题，等于静默失败"
    endpoint_branch, sep, _ = block.partition("else:")
    assert sep, "探活失败分支没有分类（缺 else 分支），接口级与数据源级共用同一套文案"
    legacy_titles = [t for t in titles if LEGACY_TITLE in t]
    assert legacy_titles, "连一条数据源级告警都没有，等于静默——fail-visible 不成立"
    assert LEGACY_TITLE not in endpoint_branch, (
        "接口级分支仍在用「数据源不可达」标题：一条接口失败被写成整个数据源不可用"
    )


def test_endpoint_branch_is_info_level():
    """接口级分支必须是 INFO 级（不惊动人），数据源级分支保留 WARNING。"""
    block = _startup_probe_block()
    endpoint_branch, sep, source_branch = block.partition("else:")
    assert sep, "探活失败分支没有分类（缺 else 分支）"
    assert "AlertLevel.INFO" in endpoint_branch, "接口级失败没有降级为 INFO"
    assert "AlertLevel.WARNING" in source_branch, "数据源级失败没有保留 WARNING"


# ---------------------------------------------------------------- 执行路径（真的跑一遍）


def _run_startup_probe(exc: BaseException, monkeypatch) -> list[dict]:
    """用假 akshare + 假告警服务跑 lifespan 的探活段，返回发出去的告警。"""
    sent: list[dict] = []

    class _FakeAlert:
        enabled = True

        async def send_alert(self, **kwargs):
            sent.append(kwargs)

    fake_ak = types.ModuleType("akshare")

    def _boom(**_kwargs):
        raise exc

    fake_ak.stock_zh_index_daily = _boom
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    import services.feishu_alert as fa

    monkeypatch.setattr(fa, "get_alert_service", lambda *_a, **_k: _FakeAlert(), raising=False)

    import main as svc_main

    # 只跑到告警发送为止：让后续后台任务注册处抛哨兵异常提前退出
    class _StopSignalError(Exception):
        pass

    def _stop(*_a, **_k):
        raise _StopSignalError

    monkeypatch.setattr(svc_main, "run_index_broadcast_loop", _stop, raising=False)
    try:
        asyncio.run(_drive_lifespan(svc_main))
    except _StopSignalError:
        pass
    return sent


async def _drive_lifespan(svc_main):
    async with svc_main.lifespan(svc_main.app):
        pass


def test_endpoint_failure_sends_info_only(monkeypatch):
    """接口级失败：发 INFO「行情接口瞬时失败」，不发「数据源不可达」，且不炸。"""
    sent = _run_startup_probe(
        RemoteDisconnected("Remote end closed connection without response"), monkeypatch
    )
    assert len(sent) == 1, f"应只发 1 条告警，实际 {[s.get('title') for s in sent]}"
    alert = sent[0]
    assert alert["title"] != LEGACY_TITLE, "接口级失败仍以「数据源不可达」发出"
    assert str(alert.get("level")).endswith("INFO"), f"级别应为 INFO，实际 {alert.get('level')}"
    assert "接口级" in alert.get("data", {}).get("探活结论", ""), alert.get("data")
    assert "Remote end closed" in alert.get("content", ""), "告警正文里丢了原始错误，排障没法用"


def test_source_failure_still_warns(monkeypatch):
    """数据源级失败：仍发 WARNING「数据源不可达」（fail-visible，不静默）。"""
    sent = _run_startup_probe(OSError("NameResolutionError: Failed to resolve push2"), monkeypatch)
    assert len(sent) == 1, f"应只发 1 条告警，实际 {[s.get('title') for s in sent]}"
    alert = sent[0]
    assert alert["title"] == LEGACY_TITLE, f"数据源级失败标题应保留告警语，实际 {alert['title']}"
    assert str(alert.get("level")).endswith("WARNING"), (
        f"级别应为 WARNING，实际 {alert.get('level')}"
    )
    assert "数据源级" in alert.get("data", {}).get("探活结论", ""), alert.get("data")
