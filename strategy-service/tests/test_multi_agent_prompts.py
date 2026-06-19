"""
测试多智能体提示词加载模块
Cover services/multi_agent/prompts.py 中未覆盖的分支：
- _load_prompts FileNotFoundError (line 26)
- _load_prompts YAMLError (lines 26-28)
- 异常 → RuntimeError (line 28)
"""

from pathlib import Path
from unittest.mock import patch

import pytest

# 先正常导入以触发模块级 _PROMPTS = _load_prompts()
from services.multi_agent.prompts import SYSTEM_PROMPTS, _load_prompts
import yaml


class TestLoadPromptsErrors:
    """测试 _load_prompts() 异常路径"""

    def test_file_not_found_raises_runtime_error(self):
        """YAML 文件不存在 → raise RuntimeError (line 26, 28)"""
        # 直接 patch read_text 触发 FileNotFoundError
        with patch.object(Path, "read_text", side_effect=FileNotFoundError("not found")):
            with pytest.raises(RuntimeError, match="无法加载提示词"):
                _load_prompts()

    def test_yaml_error_raises_runtime_error(self):
        """YAML 解析失败 → raise RuntimeError (lines 26-28)"""
        with patch.object(Path, "read_text", return_value="invalid: yaml: : broken"):
            with patch.object(yaml, "safe_load", side_effect=yaml.YAMLError("parse error")):
                with pytest.raises(RuntimeError, match="无法加载提示词"):
                    _load_prompts()


class TestSystemPromptsLoaded:
    """验证模块级提示词成功加载"""

    def test_system_prompts_has_all_keys(self):
        """SYSTEM_PROMPTS 包含所有预期角色 (line 39-46)"""
        expected_keys = {
            "fundamental",
            "technical",
            "money_flow",
            "sentiment",
            "bull_debate",
            "bear_debate",
        }
        assert expected_keys.issubset(SYSTEM_PROMPTS.keys())

    def test_base_system_present_in_analyst_prompts(self):
        """基础提示词嵌入在分析师提示词中"""
        assert "base_system" in _load_prompts()
