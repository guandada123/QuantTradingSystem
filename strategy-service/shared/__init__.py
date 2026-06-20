"""
strategy-service/shared 桥接包

通过 __path__ 扩展技术将 QTS 根目录的 shared/ 包暴露给 strategy-service 的
import 系统，使得 `from shared.xxx import ...` 解析到根目录的真实实现。

- 本地保留的存根（auth / middleware / rate_limiter / ws_protocol）用于测试环境
- 已删除的重复文件（exceptions / structured_log）自动回退到 QTS_ROOT/shared/
"""

import os as _os

_THIS_DIR = _os.path.realpath(_os.path.dirname(__file__))
_QTS_ROOT = _os.path.realpath(_os.path.join(_THIS_DIR, "..", ".."))
_ROOT_SHARED = _os.path.join(_QTS_ROOT, "shared")

# 将 QTS 根 shared/ 加入 __path__，使子包查找（shared.quote_provider 等）
# 能穿透到根目录的真正实现
if _os.path.isdir(_ROOT_SHARED) and _ROOT_SHARED not in __path__:
    __path__.append(_ROOT_SHARED)  # type: ignore[attr-defined]
