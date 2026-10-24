#!/usr/bin/env python3
"""从 uv.lock 派生 requirements.lock，并提供一致性校验。

## 为什么需要（2026-10-24）

本仓有**两个锁文件**：
  · `uv.lock`            —— 真相源（uv 解析的完整图，含 marker/hash）
  · `requirements.lock`  —— 派生视图（pip freeze 风格 `name==version`，无 marker）
CI 的 `lock-audit` 两个都扫。于是两个文件必须同步，但**此前没有任何工具维护派生文件**：
它是手工生成的一次性产物，改依赖时只改 uv.lock → 派生文件留在旧版本 →
lock-audit 持续报"已修复的漏洞"（实测 2026-10-24：uv.lock 已升 aiohttp 3.14.5，
requirements.lock 仍是 3.14.3，CI 照旧判红）。

这正是「依赖清单多真源」的典型后果：**门禁读的是哪一份，决定了它是假绿还是假红。**

## 用法

    python3 scripts/sync_requirements_lock.py            # 重写 requirements.lock
    python3 scripts/sync_requirements_lock.py --check    # 只校验，不一致则 exit 1

`--check` 适合放进 CI / pre-commit：改依赖时忘了同步，会当场失败而不是等 audit 报红。

## 格式约定（刻意保守）

保留派生文件的既有格式，不引入 uv export 的 marker：
  · 两行头注（含包数）
  · `name==version`，按包名排序
  · 保留根项目自身那一行（`--no-emit-project` 会把它排除，需单独补回）
去掉 marker 是有意的：CI 的 audit 脚本按 `name==version` 解析，marker 会让它漏包或报错。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"
HEADER = "# Synced from uv.lock (uv-lock -> pinned requirements)"
_NAME_VER = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)")


def _uv_export() -> dict[str, str]:
    """uv.lock → {包名小写: 版本}（去掉 marker，不排序）。"""
    proc = subprocess.run(
        [
            "uv",
            "export",
            "--all-extras",
            "--format",
            "requirements-txt",
            "--no-hashes",
            "--no-annotate",
            "--no-emit-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"uv export 失败（rc={proc.returncode}）：{proc.stderr[:400]}")
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _NAME_VER.match(line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def _parse_lock() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _NAME_VER.match(line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def _project_row() -> str:
    """根项目自身那一行（形如 `quant-trading-system==0.2.0`）。

    `uv export --no-emit-project` 会跳过它，但派生文件历史上含这一行
    （别处可能按它做版本断言），保留以维持格式稳定。
    """
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        m = _NAME_VER.match(line.strip())
        if m and m.group(1).lower().replace("_", "-") == "quant-trading-system":
            return f"{m.group(1)}=={m.group(2)}"
    return ""


def drift() -> dict[str, tuple[str | None, str | None]]:
    cur, want = _parse_lock(), _uv_export()
    return {k: (cur.get(k), want.get(k)) for k in set(cur) | set(want) if cur.get(k) != want.get(k)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不一致 exit 1")
    args = ap.parse_args()

    d = drift()
    # 根项目行是派生视图特有的一行，不算漂移
    d.pop("quant-trading-system", None)

    if args.check:
        if not d:
            print(f"OK requirements.lock 与 uv.lock 一致（{len(_parse_lock())} 包）")
            return 0
        print(f"FAIL 派生锁文件与 uv.lock 有 {len(d)} 处不一致：", file=sys.stderr)
        for k, (a, b) in sorted(d.items()):
            print(f"  {k:28} 现行={a or '(缺)':14} uv.lock={b or '(缺)'}", file=sys.stderr)
        print("修法：python3 scripts/sync_requirements_lock.py", file=sys.stderr)
        return 1

    if not d:
        print(f"无需改动（{len(_parse_lock())} 包已一致）")
        return 0

    want = _uv_export()
    proj = _project_row()
    if proj:
        want["quant-trading-system"] = proj.split("==", 1)[1]

    lines = [HEADER, f"# synced packages: {len(want)}"]
    lines += [f"{name}=={ver}" for name, ver in sorted(want.items())]
    LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已重写 requirements.lock：{len(want)} 包（原 {len(_parse_lock())}）")
    for k, (a, b) in sorted(d.items()):
        print(f"  {k:28} {a or '(缺)':14} → {b or '(缺)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
