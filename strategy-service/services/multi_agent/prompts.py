"""
多智能体协作框架 — 提示词加载

从 YAML 配置文件加载智能体提示词，无包内依赖，安全提前加载。
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ============================================
# 从 YAML 加载智能体提示词
# ============================================


def _load_prompts() -> dict[str, str]:
    """从 multi_agent_prompts.yaml 加载所有智能体提示词"""
    # 此文件位于 services/multi_agent/prompts.py
    # .parent.parent = services/
    prompts_path = Path(__file__).resolve().parent.parent / "prompts" / "multi_agent_prompts.yaml"
    try:
        raw = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.error(f"提示词YAML加载失败: {e}")
        raise RuntimeError(f"无法加载提示词配置: {prompts_path}") from e
    data: dict[str, str] = raw
    return data


_PROMPTS = _load_prompts()

# 共享系统提示词（固定前缀→100% KV Cache 命中）
BASE_SYSTEM = _PROMPTS["base_system"].strip()

# 合成各智能体的完整 system prompt
# 4 位分析师继承 base_system，2 位辩论研究员使用独立提示词
SYSTEM_PROMPTS = {
    "fundamental": f"{BASE_SYSTEM}\n{_PROMPTS['fundamental'].strip()}",
    "technical": f"{BASE_SYSTEM}\n{_PROMPTS['technical'].strip()}",
    "money_flow": f"{BASE_SYSTEM}\n{_PROMPTS['money_flow'].strip()}",
    "sentiment": f"{BASE_SYSTEM}\n{_PROMPTS['sentiment'].strip()}",
    "bull_debate": _PROMPTS["bull_debate"].strip(),
    "bear_debate": _PROMPTS["bear_debate"].strip(),
}
