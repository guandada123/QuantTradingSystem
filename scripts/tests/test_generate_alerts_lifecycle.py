"""T-020 回归用例：告警生命周期（命中复用 / 未命中关闭 / 无输入绝不关闭）

无库可跑：用 `FakeCursor` 记录脚本发出的 SQL 与参数，断言的是**行为**（发了什么写语句、
关闭了几行），不是实现细节。

注坏验证（实施轮实测）：把「未命中 → 关闭」这一支去掉 → `test_quiet_closes_open_rows` 翻红；
把「无输入提前返回」去掉（让无输入落进关闭分支）→ `test_no_input_does_not_close` 翻红。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_alerts as ga  # noqa: E402


class FakeCursor:
    """按 SQL 语义返回预设行，并记录所有执行过的语句。"""

    def __init__(self, positions=(), open_rows=(), dedup_rows=(), trades=()):
        self.positions = list(positions)
        self.open_rows = list(open_rows)  # 该规则现有 open 行 id，最新在前
        self.dedup_rows = list(dedup_rows)
        self.trades = list(trades)
        self.executed: list[tuple[str, object]] = []
        self.rowcount = 0
        self._rows: list[tuple] = []

    # ---- 断言辅助 ----
    def sql_matching(self, needle: str) -> list[tuple[str, object]]:
        return [(s, p) for s, p in self.executed if needle in s]

    @property
    def inserts(self):
        return self.sql_matching("INSERT INTO alerts")

    @property
    def updates(self):
        return self.sql_matching("UPDATE alerts")

    # ---- psycopg2 兼容面 ----
    def execute(self, sql: str, params=None):
        norm = " ".join(sql.split())
        self.executed.append((norm, params))
        self._rows = []
        self.rowcount = 0

        if norm.startswith("UPDATE alerts"):
            keep = params[1] if params and len(params) > 1 else None
            stale = [i for i in self.open_rows if keep is None or i != keep]
            self.rowcount = len(stale)
            self.open_rows = [i for i in self.open_rows if i not in stale]
            return
        if norm.startswith("INSERT INTO alerts"):
            self.rowcount = 1
            return
        if "FROM positions" in norm:
            self._rows = (
                [(len(self.positions), *self.positions[:2])]
                if self.positions
                else [(0, None, None)]
            )
            return
        if "FROM trades" in norm:
            self._rows = [(len(self.trades),)]
            return
        if norm.startswith("SELECT id FROM alerts"):
            self._rows = [(i,) for i in self.open_rows]
            return
        if "triggered_at >=" in norm:
            self._rows = [(len(self.dedup_rows),)]
            return
        if "count(*)" in norm and "status = 'open'" in norm:
            keep = params[1] if params and len(params) > 1 else None
            self._rows = [(len([i for i in self.open_rows if keep is None or i != keep]),)]
            return
        raise AssertionError(f"未预料到的 SQL: {norm}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


CONC_RULE = {
    "id": 3,
    "name": "持仓集中度超50%",
    "expr": "concentration > 0.5",
    "threshold": 0.5,
    "level": "warning",
}
LOSS_RULE = {
    "id": 4,
    "name": "连续亏损3次",
    "expr": "consecutive_loss >= 3",
    "threshold": 3,
    "level": "info",
}

# 命中：单一持仓 530 / 合计 1000 = 53% > 50%
HIT_POSITIONS = (530.0, 1000.0)
# 未命中：单一持仓 200 / 合计 1000 = 20%
MISS_POSITIONS = (200.0, 1000.0)


def test_hit_with_existing_open_row_reuses():
    """命中 + 已有 open 行 → 不发 INSERT，复用（只留那一行）。"""
    cur = FakeCursor(positions=HIT_POSITIONS, open_rows=[7])
    res = ga.process_rule(cur, CONC_RULE, dedup_hours=24, dry_run=False)

    assert res["outcome"] == "reused"
    assert cur.inserts == [], "命中且已有 open 行时不得新增告警行"
    assert cur.updates == [], "只有一行 open 时无需收口"
    assert res["closed"] == 0


def test_hit_consolidates_duplicate_open_rows():
    """命中 + 同一规则多行 open（历史逐日叠加）→ 收口成 1 行，其余置 resolved。"""
    cur = FakeCursor(positions=HIT_POSITIONS, open_rows=[7, 5, 3])
    res = ga.process_rule(cur, CONC_RULE, dedup_hours=24, dry_run=False)

    assert res["outcome"] == "reused"
    assert cur.inserts == []
    assert len(cur.updates) == 1
    sql, params = cur.updates[0]
    assert "status = 'resolved'" in sql and "resolved_at = NOW()" in sql
    assert params == (3, 7), "应保留最新一行 id=7，关闭 id=5/3"
    assert res["closed"] == 2
    assert cur.open_rows == [7]


def test_hit_without_open_row_inserts_open():
    """命中 + 无 open 行 → 发 1 条 INSERT，status 写死 open。"""
    cur = FakeCursor(positions=HIT_POSITIONS, open_rows=[], dedup_rows=[])
    res = ga.process_rule(cur, CONC_RULE, dedup_hours=24, dry_run=False)

    assert res["outcome"] == "new"
    assert len(cur.inserts) == 1
    sql, params = cur.inserts[0]
    assert "INSERT INTO alerts" in sql
    assert "'open'" in sql
    assert params[0] == 3
    assert params[3] == "concentration"
    assert cur.updates == []


def test_quiet_closes_open_rows():
    """确定未命中（条件消失）→ 发 1 条 UPDATE 置 resolved，行数计入「关闭」。"""
    cur = FakeCursor(positions=MISS_POSITIONS, open_rows=[2, 3])
    res = ga.process_rule(cur, CONC_RULE, dedup_hours=24, dry_run=False)

    assert res["outcome"] == "quiet"
    assert res["closed"] == 2
    assert cur.inserts == []
    assert len(cur.updates) == 1
    sql, params = cur.updates[0]
    assert "status = 'resolved'" in sql and "resolved_at = NOW()" in sql
    assert "WHERE rule_id = %s AND status = 'open'" in sql
    assert params == (3,)
    assert cur.open_rows == []


def test_no_input_does_not_close():
    """「无输入 / 结构性缺输入」→ 绝不关闭（负控：注坏成"无输入也关闭"必须翻红）。"""
    cur = FakeCursor(trades=[], open_rows=[9])
    res = ga.process_rule(cur, LOSS_RULE, dedup_hours=24, dry_run=False)

    assert res["outcome"] == "skipped"
    assert "无输入" in res["reason"]
    assert cur.updates == [], "无输入时绝不能把告警置 resolved（数据断供 != 条件消失）"
    assert cur.inserts == []
    assert res["closed"] == 0
    assert cur.open_rows == [9]


def test_dry_run_writes_nothing():
    """--dry-run → 既不发 INSERT 也不发 UPDATE，关闭行数只预估。"""
    cur = FakeCursor(positions=HIT_POSITIONS, open_rows=[7, 5])
    hit_res = ga.process_rule(cur, CONC_RULE, dedup_hours=24, dry_run=True)
    assert hit_res["outcome"] == "reused"
    assert hit_res["closed"] == 1, "dry-run 也要能预估会关闭几行"
    assert cur.inserts == [] and cur.updates == []

    cur2 = FakeCursor(positions=MISS_POSITIONS, open_rows=[2, 3])
    quiet_res = ga.process_rule(cur2, CONC_RULE, dedup_hours=24, dry_run=True)
    assert quiet_res["outcome"] == "quiet"
    assert quiet_res["closed"] == 2
    assert cur2.inserts == [] and cur2.updates == []
    assert cur2.open_rows == [2, 3], "dry-run 不得改动任何状态"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
