"""腾讯估值兜底的字段契约测试

该模块的价值全在「字段索引 + 单位换算」这一层约定上，一旦腾讯改版它就会静默
返回错误数值（而不是报错），因此必须用固定响应把契约钉死。
"""

from __future__ import annotations

import pytest

from shared.quote_provider import tencent_quote
from shared.quote_provider.tencent_quote import fetch_fundamental, to_tencent_symbol


def build_response(code: str = "600519", name: str = "贵州茅台") -> str:
    """构造 47 字段最小响应体，索引位置与线上一致"""
    fields = ["0"] * 47
    fields[0] = "1"
    fields[1] = name
    fields[2] = code
    fields[3] = "1338.97"
    fields[39] = "20.55"
    fields[44] = "16738.22"
    fields[45] = "16738.22"
    fields[46] = "6.66"
    return f'v_sh{code}="{"~".join(fields)}";\n'


class FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.encoding = None


class TestSymbolMapping:
    @pytest.mark.parametrize(
        ("ts_code", "expected"),
        [
            ("600519.SH", "sh600519"),
            ("000001.SZ", "sz000001"),
            ("430047.BJ", "bj430047"),
        ],
    )
    def test_market_prefix(self, ts_code, expected):
        assert to_tencent_symbol(ts_code) == expected


class TestFetchFundamental:
    def test_parses_pe_pb_and_market_value(self, monkeypatch):
        monkeypatch.setattr(
            tencent_quote.requests, "get", lambda *a, **kw: FakeResp(build_response())
        )

        result = fetch_fundamental("600519.SH")

        assert result["pe_ttm"] == 20.55
        assert result["pb"] == 6.66
        assert result["total_mv"] == pytest.approx(16738.22 * 10000)
        assert result["circ_mv"] == pytest.approx(16738.22 * 10000)
        assert result["ts_code"] == "600519.SH"

    def test_total_mv_is_in_wan_yuan(self, monkeypatch):
        """单位必须是万元（对齐 Tushare 口径），不是元也不是亿元"""
        monkeypatch.setattr(
            tencent_quote.requests, "get", lambda *a, **kw: FakeResp(build_response())
        )

        result = fetch_fundamental("600519.SH")

        assert 1.6e8 < result["total_mv"] < 1.7e8, "茅台总市值应约 1.67 亿万元（即 1.67 万亿元）"

    def test_ps_ttm_is_none_not_zero(self, monkeypatch):
        """腾讯不提供市销率。必须用 None 表示未知，不能填 0 —— 否则下游会把
        「无数据」读成「PS=0」，与 Tushare 路径（有真实 PS）语义冲突。"""
        monkeypatch.setattr(
            tencent_quote.requests, "get", lambda *a, **kw: FakeResp(build_response())
        )

        result = fetch_fundamental("600519.SH")

        assert result["ps_ttm"] is None

    def test_short_response_returns_empty(self, monkeypatch):
        """字段数不足说明布局变更，必须拒绝而不是错位取值"""
        short = 'v_sh600519="1~贵州茅台~600519~1338.97";'
        monkeypatch.setattr(tencent_quote.requests, "get", lambda *a, **kw: FakeResp(short))

        assert fetch_fundamental("600519.SH") == {}

    def test_non_200_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            tencent_quote.requests, "get", lambda *a, **kw: FakeResp("", status_code=502)
        )

        assert fetch_fundamental("600519.SH") == {}

    def test_network_error_returns_empty(self, monkeypatch):
        def boom(*a, **kw):
            raise ConnectionError("timeout")

        monkeypatch.setattr(tencent_quote.requests, "get", boom)

        assert fetch_fundamental("600519.SH") == {}

    def test_malformed_payload_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            tencent_quote.requests, "get", lambda *a, **kw: FakeResp("v_sh600519=1;")
        )

        assert fetch_fundamental("600519.SH") == {}

    def test_non_numeric_field_degrades_to_none(self, monkeypatch):
        """字段缺失 → None，不得填 0。

        同一响应里必须只有一种空值约定：0 代表「值真的是 0」，None 代表「没拿到」。
        填 0 会让下游把缺失当成真实的零值（如 total_mv=0 参与市值加权会静默拉低权重）。
        """
        body = build_response().replace("~20.55~", "~~", 1)
        monkeypatch.setattr(tencent_quote.requests, "get", lambda *a, **kw: FakeResp(body))

        result = fetch_fundamental("600519.SH")

        assert result["pe_ttm"] is None
        # 其他字段不受影响
        assert result["pb"] is not None

    def test_missing_market_value_stays_none_not_zero(self, monkeypatch):
        """市值字段缺失时不得返回 0.0：0 会被当作真实市值为零"""
        result_body = build_response()
        # 清空总市值字段（索引 45）
        fields = result_body.split('="')[1].rstrip('";\n').split("~")
        fields[45] = ""
        mutated = 'v_sh600519="' + "~".join(fields) + '";\n'
        monkeypatch.setattr(tencent_quote.requests, "get", lambda *a, **kw: FakeResp(mutated))

        result = fetch_fundamental("600519.SH")

        assert result["total_mv"] is None
