"""降级链熔断测试 — 覆盖 2026-09-01 run#58 修正的两个缺陷

v1 的两个实证缺陷：
  ① 作用域=实例级：定时任务每次 new DataService，冷却表随实例销毁，跨任务无效
     （akshare 实测 24h 调用 48 次、成功 0 次、每次白等 20.4s ≈ 16.4 分钟/天）
  ② 粒度=数据源级：Tushare 限频是按接口的（index_daily 5 次/天 vs daily 50 次/分），
     数据源级冷却会让 index_daily 配额耗尽连带熔断整个 tushare 源

全部用例使用假 provider 注入故障，不发起任何网络请求。
"""

import time

import pytest
from services import data_service as ds_mod


class FakeProvider:
    """假数据源：可注入异常或固定返回值，并记录调用次数"""

    def __init__(self, name, exc=None, result=None):
        self.name = name
        self.exc = exc
        self.result = result
        self.calls = 0

    def _invoke(self):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result

    def get_index_realtime(self, *a, **k):
        return self._invoke()

    def get_daily_kline(self, *a, **k):
        return self._invoke()


class FakeFactory:
    def __init__(self, providers):
        self.providers = providers
        self.default_source = next(iter(providers))

    def get_provider(self, source):
        return self.providers.get(source)


CONN_ERR = ConnectionError(
    "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
)
RATE_ERR = RuntimeError("抱歉，您访问接口(index_daily)频率超限(5次/天)")
BIZ_ERR = ValueError("invalid ts_code format: 999999.XX")


def make_ds(providers):
    """构造一个不触发真实初始化的 DataService"""
    svc = ds_mod.DataService.__new__(ds_mod.DataService)
    svc._factory = FakeFactory(providers)
    return svc


@pytest.fixture(autouse=True)
def _clean_cooldown_state():
    """每个用例前后清空模块级状态，避免用例间互相污染"""
    ds_mod._METHOD_COOLDOWN.clear()
    ds_mod._METHOD_FAILURES.clear()
    yield
    ds_mod._METHOD_COOLDOWN.clear()
    ds_mod._METHOD_FAILURES.clear()


def test_cooldown_shared_across_instances():
    """缺陷①：冷却状态必须跨 DataService 实例共享，否则每个定时任务都要重踩一次坑"""
    broken = FakeProvider("akshare", exc=CONN_ERR)
    healthy = FakeProvider("tushare", result=[{"price": 1.0}])

    ds_a = make_ds({"akshare": broken, "tushare": healthy})
    for _ in range(ds_mod.SYSTEMIC_FAILURE_THRESHOLD):
        ds_a._call_provider_with_fallback(lambda p: p.get_index_realtime, lambda r: True)
    calls_after_first_instance = broken.calls

    # 新实例 = 下一个定时任务
    ds_b = make_ds({"akshare": broken, "tushare": healthy})
    result = ds_b._call_provider_with_fallback(lambda p: p.get_index_realtime, lambda r: True)

    assert broken.calls == calls_after_first_instance, "已熔断的源不应被新实例再次调用"
    assert result == [{"price": 1.0}], "应直接降级到健康源"


def test_cooldown_is_per_method_not_per_source():
    """缺陷②：一个方法限频不应连坐同一数据源的其他方法"""
    provider = FakeProvider("tushare", exc=RATE_ERR)
    ds = make_ds({"tushare": provider})

    ds._call_provider_with_fallback(lambda p: p.get_index_realtime, lambda r: True)
    provider.calls = 0
    ds._call_provider_with_fallback(lambda p: p.get_daily_kline, lambda r: True)

    assert provider.calls == 1, "get_daily_kline 不应被 get_index_realtime 的熔断连坐"


def test_rate_limit_trips_immediately():
    """限频命中即熔断：保留 v1 已实证有效行为（批量 4494 → 48 次）"""
    provider = FakeProvider("tushare", exc=RATE_ERR)
    ds = make_ds({"tushare": provider})

    for _ in range(50):
        ds._call_provider_with_fallback(lambda p: p.get_daily_kline, lambda r: True)

    assert provider.calls == 1, f"限频后不应继续撞击，实际调用 {provider.calls} 次"


def test_business_error_does_not_trip_cooldown():
    """业务性错误（代码无效、停牌）换标的就会成功，不应触发冷却"""
    provider = FakeProvider("tushare", exc=BIZ_ERR)
    ds = make_ds({"tushare": provider})

    for _ in range(10):
        ds._call_provider_with_fallback(lambda p: p.get_daily_kline, lambda r: True)

    assert provider.calls == 10, "业务性错误不应熔断"
    assert not ds_mod._METHOD_COOLDOWN, "业务性错误不应写入冷却表"


def test_single_network_blip_does_not_trip_cooldown():
    """单次网络抖动不误伤：需连续 SYSTEMIC_FAILURE_THRESHOLD 次才熔断"""
    provider = FakeProvider("tushare", exc=CONN_ERR)
    ds = make_ds({"tushare": provider})

    ds._call_provider_with_fallback(lambda p: p.get_daily_kline, lambda r: True)

    assert not ds_mod._METHOD_COOLDOWN, "仅失败 1 次不应熔断"


def test_repeated_failures_back_off_exponentially():
    """反复失败按指数退避拉长冷却

    固定 300s 在 30 分钟周期的定时任务下等于每轮都重试一次，省不下任何时间。
    """
    provider = FakeProvider("tushare", exc=CONN_ERR)
    ds = make_ds({"tushare": provider})
    key = "tushare:get_daily_kline"

    durations = []
    for _ in range(5):
        ds_mod._METHOD_COOLDOWN.pop(key, None)  # 模拟冷却到期后重试
        ds._note_failure(key, "tushare", "get_daily_kline", CONN_ERR)
        durations.append(
            round(ds_mod._METHOD_COOLDOWN[key] - time.time())
            if key in ds_mod._METHOD_COOLDOWN
            else 0
        )

    assert all(b >= a for a, b in zip(durations, durations[1:])), f"冷却时长应单调不减: {durations}"
    assert durations[-1] > durations[0], f"冷却时长应随连续失败增长: {durations}"
    assert max(durations) <= ds_mod.COOLDOWN_MAX_SECONDS


def test_success_clears_failure_counter():
    """恢复后应能正常取数，且连续失败计数清零"""
    provider = FakeProvider("tushare", exc=CONN_ERR)
    ds = make_ds({"tushare": provider})
    key = "tushare:get_daily_kline"

    for _ in range(ds_mod.SYSTEMIC_FAILURE_THRESHOLD):
        ds._call_provider_with_fallback(lambda p: p.get_daily_kline, lambda r: True)

    provider.exc = None
    provider.result = [{"close": 1.0}]
    ds_mod._METHOD_COOLDOWN.pop(key, None)
    result = ds._call_provider_with_fallback(lambda p: p.get_daily_kline, lambda r: True)

    assert result == [{"close": 1.0}]
    assert key not in ds_mod._METHOD_FAILURES, "成功后应清空连续失败计数"
