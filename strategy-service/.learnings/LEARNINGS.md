# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20250620-001] urllib.urlopen mock 模式匹配

**Logged**: 2026-06-20T15:20:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
Mock `urllib.request.urlopen` 时，必须匹配生产代码的调用模式：非 `with` 上下文管理器模式应使用 `mock_urlopen.return_value = mock_response`，而非 `mock_urlopen.return_value.__enter__.return_value = mock_response`。

### Details
`_fetch_index_via_tencent` 使用 `resp = urllib.request.urlopen(url, timeout=5)`（无 `with` 语句），但测试 mock 了 `__enter__`，导致 mock 不生效。修复后 4 个测试通过。

### Resolution
- **Resolved**: 2026-06-20T15:20:00+08:00
- **Procedure**: 将 `mock_urlopen.return_value.__enter__.return_value = mock_response` 改为 `mock_urlopen.return_value = mock_response`
- **Files**: `tests/test_data_service.py` (4处修改)

---
