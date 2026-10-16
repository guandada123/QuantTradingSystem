#!/usr/bin/env python3
"""QTS 依赖与共享包影响面门禁（2026-10-16 加）

为什么要有它（由 10-16 事故反查得出）：
  10-13 的 PyJWT 安全迁移（36d91f95）只改了 strategy-service 的依赖清单，
  execution-service / ai-scheduler 的 constraints 仍锁 python-jose；
  两镜像又都构建于迁移之前 → execution-service 因 `import jwt` 失败而崩溃循环
  3 天（重启 115 次）。根因有两条，本门禁针对这两条：
    A1 依赖真源分散在三份清单、且无一致性校验；
    A2 shared/ 被多个服务安装，但改 shared/ 时没有任何机制提示要重建谁。

判定口径（刻意区分级别，避免一上来就卡死 CI）：
  ❌ 阻断：shared/ 依赖的包在**任一消费者清单中缺失** —— 这正是本次事故的
     失败模式（依赖缺失 → 运行期 import 直接崩），必须挡住。
  ⚠️ 仅提示：同一包在各清单中的版本漂移 —— 目前跨服务版本差异是被容忍的既有
     状态，统一版本需要连带重建镜像，属独立决策，故只提示不阻断。
  ℹ️ 提示：本次变更若涉及 shared/，列出需重建的服务清单。

用法：
    python3 scripts/check_dependency_consistency.py
    python3 scripts/check_dependency_consistency.py --changed shared/auth.py ...
退出码：0 = 通过（可能有警告）；1 = 存在必须处理的问题。
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 三份依赖清单（本仓依赖真源）
PIN_FILES = [
    "strategy-service/requirements.pinned.txt",
    "execution-service/constraints.txt",
    "ai-scheduler/constraints.txt",
]


def norm(name: str) -> str:
    """包名归一化：PEP 503。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_pins(path: Path) -> dict[str, str]:
    """抽取 `name==version` 条目（忽略注释、-r/-c 引用行）。

    🔴 必须识别 extras 语法（如 `PyJWT[crypto]==2.15.1`）：不带 extras 分支时该行
       会被整体跳过 → 明明锁着 PyJWT 却被判成「缺失」
       （2026-10-16 由可证伪测试击破后发现）。
    """
    pins: dict[str, str] = {}
    if not path.exists():
        return pins
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?\s*==\s*([^\s;#]+)", line)
        if m:
            pins[norm(m.group(1))] = m.group(2)
    return pins


def base_name(spec: str) -> str:
    """从 'pyjwt[crypto]>=2.10.0' 取包名 'pyjwt'。"""
    return norm(re.split(r"[<>=!;\[\s]", spec, maxsplit=1)[0])


def parse_shared_deps() -> list[str]:
    r"""读 pyproject.toml 里 shared extra 声明的依赖（shared/ 包需要的包）。

    🔴 用**真正的 TOML 解析器**，不要用正则：非贪婪的 `\[(.*?)\]` 会在
       `pyjwt[crypto]` 的内层 `]` 处截断，直接漏掉 pyjwt —— 而 pyjwt 恰是本次
       事故的主角（2026-10-16 由可证伪测试击破后改用 tomllib）。
    """
    pf = ROOT / "pyproject.toml"
    if not pf.exists():
        return []
    text = pf.read_text(encoding="utf-8", errors="ignore")
    try:
        import tomllib  # py>=3.11

        data = tomllib.loads(text)
    except ImportError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore

            data = tomllib.loads(text)
        except Exception:
            return []
    except Exception:
        return []
    try:
        deps = data["project"]["optional-dependencies"]["shared"]
    except Exception:
        deps = []
    return [base_name(d) for d in deps if isinstance(d, str)]


def check_missing(deps: list[str], tables: dict[str, dict[str, str]]) -> list[str]:
    """shared 依赖在任一清单中缺失 → 阻断级问题。"""
    problems = []
    for dep in deps:
        missing = [f for f, t in tables.items() if dep and dep not in t]
        if missing:
            problems.append(
                f"  · shared/ 依赖缺失：{dep} 未出现在 {', '.join(sorted(missing))} "
                f"→ 该服务的镜像会缺少它（本次 PyJWT 事故即此类）"
            )
    return problems


def check_drift(tables: dict[str, dict[str, str]]) -> list[str]:
    """同名包跨清单版本漂移 → 提示级。"""
    merged: dict[str, dict[str, str]] = {}
    for f, t in tables.items():
        for name, ver in t.items():
            merged.setdefault(name, {})[f] = ver
    warns = []
    for name, src in sorted(merged.items()):
        if len(src) >= 2 and len(set(src.values())) > 1:
            detail = "、".join(f"{Path(f).parent.name}@{v}" for f, v in sorted(src.items()))
            warns.append(f"  · 版本漂移：{name}（{detail}）")
    return warns


def shared_consumers() -> list[str]:
    """按 Dockerfile 的 `COPY shared/` 判定哪些服务依赖 shared/ 包。"""
    out = []
    for df in sorted(ROOT.glob("*/Dockerfile")):
        text = ""
        with contextlib.suppress(Exception):
            text = df.read_text(encoding="utf-8", errors="ignore")
        if not text:
            continue
        if re.search(r"^\s*COPY\s+shared/\s", text, re.M):
            out.append(df.parent.name)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changed", nargs="*", default=[])
    args = ap.parse_args()

    tables = {f: parse_pins(ROOT / f) for f in PIN_FILES}
    deps = parse_shared_deps()

    print("== shared/ 依赖是否在所有消费者的清单中都存在（阻断级）==")
    print(f"  shared extra 声明：{', '.join(deps) if deps else '（未解析到）'}")
    problems = check_missing(deps, tables)
    print("\n".join(problems) if problems else "  ✓ 全部存在")

    warns = check_drift(tables)
    print(f"\n== 跨清单版本漂移（提示级，共 {len(warns)} 处）==")
    print("\n".join(warns) if warns else "  ✓ 无漂移")

    consumers = shared_consumers()
    print("\n== shared/ 的消费者（改 shared/ 需重建这些服务的镜像）==")
    print("  " + (", ".join(consumers) or "（未发现）"))

    if any(c.replace("\\", "/").startswith("shared/") for c in args.changed):
        print(
            "\n⚠️ 本次变更涉及 shared/ → 需重新 build + 重建以下服务的容器："
            f"\n   {', '.join(consumers)}"
            "\n   （shared 的改动不会自动进入已有镜像）"
        )

    if problems:
        print("\n❌ 存在阻断级问题：shared/ 依赖缺失")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
