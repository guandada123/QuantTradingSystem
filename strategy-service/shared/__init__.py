"""
strategy-service/shared 包

通过 __path__ 扩展技术将 QTS 根目录的 shared/ 包暴露给 import 系统，
使得 from shared.quote_provider import ... 能解析到 QTS_ROOT/shared/quote_provider/
中的真实实现（TushareQuoteProvider, TdxQuoteProvider 等），
避免本地存根导致 import 遮蔽。
"""

import os as _os

_THIS_DIR = _os.path.realpath(_os.path.dirname(__file__))
_QTS_ROOT = _os.path.realpath(_os.path.join(_THIS_DIR, "..", ".."))
_ROOT_SHARED = _os.path.join(_QTS_ROOT, "shared")

# 将 QTS 根 shared/ 加入 __path__，使子包查找（shared.quote_provider 等）
# 能穿透到根目录的真正实现
if _os.path.isdir(_ROOT_SHARED) and _ROOT_SHARED not in __path__:
    __path__.append(_ROOT_SHARED)  # type: ignore[attr-defined]
