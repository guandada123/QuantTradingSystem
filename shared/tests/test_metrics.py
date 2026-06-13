"""shared/metrics.py 单元测试 — Counter/Histogram/Gauge 指标采集"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.metrics import COUNTER, GAUGE, HISTOGRAM, _Counter, _Gauge, _Histogram


class TestCounter:
    def test_increment(self):
        c = _Counter()
        c.inc("requests")
        c.inc("requests")
        assert c.get_all()["requests"] == 2.0

    def test_increment_with_value(self):
        c = _Counter()
        c.inc("bytes", 1024)
        assert c.get_all()["bytes"] == 1024.0

    def test_labels(self):
        c = _Counter()
        c.inc("http_requests", labels={"method": "GET", "status": "200"})
        c.inc("http_requests", labels={"method": "POST", "status": "201"})
        data = c.get_all()
        assert len(data) == 2
        assert any("GET" in k for k in data)
        assert any("POST" in k for k in data)

    def test_same_label_accumulates(self):
        c = _Counter()
        c.inc("hits", labels={"path": "/api"})
        c.inc("hits", labels={"path": "/api"})
        data = c.get_all()
        assert list(data.values())[0] == 2.0


class TestHistogram:
    def test_observe(self):
        h = _Histogram()
        h.observe("duration", 0.05)
        h.observe("duration", 0.15)
        h.observe("duration", 0.5)
        data = h.get_all()["duration"]
        assert data["count"] == 3
        assert data["sum"] > 0

    def test_bucket_distribution(self):
        h = _Histogram()
        for v in [0.005, 0.008, 0.5, 1.0, 5.0]:
            h.observe("latency", v)
        data = h.get_all()["latency"]
        assert data["count"] == 5
        # 0.005 和 0.008 均 <=0.01，应落入第一个桶
        assert data["buckets"][0] >= 2

    def test_labels(self):
        h = _Histogram()
        h.observe("req_time", 0.1, labels={"method": "GET"})
        h.observe("req_time", 0.2, labels={"method": "POST"})
        assert len(h.get_all()) == 2


class TestGauge:
    def test_set(self):
        g = _Gauge()
        g.set("connections", 42)
        assert g.get_all()["connections"] == 42

    def test_inc_dec(self):
        g = _Gauge()
        g.set("active", 0)
        g.inc("active")
        g.inc("active")
        g.dec("active")
        assert g.get_all()["active"] == 1

    def test_labels(self):
        g = _Gauge()
        g.set("temp", 36.5, labels={"location": "cpu"})
        data = g.get_all()
        assert any("cpu" in k for k in data)


class TestGlobalInstances:
    def test_global_counter_is_counter(self):
        assert isinstance(COUNTER, _Counter)

    def test_global_histogram_is_histogram(self):
        assert isinstance(HISTOGRAM, _Histogram)

    def test_global_gauge_is_gauge(self):
        assert isinstance(GAUGE, _Gauge)
